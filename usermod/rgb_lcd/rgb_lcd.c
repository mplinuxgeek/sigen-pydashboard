// MicroPython module driving the 800x480 parallel-RGB panel (ST7262) of the Waveshare ESP32-S3-Touch-LCD-7.
// Two RGB565 frame buffers live in PSRAM; the LCD peripheral streams them through internal-SRAM bounce buffers.
// The backlight, panel reset and touch reset sit on a CH422G I/O expander, driven from Python (board.py).
//
//   import rgb_lcd
//   fb0, fb1 = rgb_lcd.init()          # memoryviews of the two frame buffers
//   ...render into fbN...
//   rgb_lcd.present(N, y1, y2)         # make it the scan-out buffer, blocks until it is on screen

#include <string.h>

#include "py/runtime.h"
#include "py/obj.h"
#include "py/objarray.h"

#include "esp_log.h"
#include "esp_err.h"
#include "esp_cache.h"
#include "esp_timer.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_panel_rgb.h"
#include "esp_attr.h"
#include "driver/gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"

#define LCD_H_RES 800
#define LCD_V_RES 480
// 13.5 MHz keeps HSYNC period (820 px) inside the ST7262 datasheet's 55..65 us window (60.7 us).
#define LCD_PIXEL_CLOCK_HZ 13500000
// Rows of the internal-SRAM bounce buffers (x2). 20 rows = 64 KB; the frame buffers stay in PSRAM.
#ifndef LCD_BOUNCE_ROWS
#define LCD_BOUNCE_ROWS 20
#endif

static bool s_inited;
static esp_lcd_panel_handle_t s_panel;
static void *s_fbs[2];
static const size_t s_fb_size = LCD_H_RES * LCD_V_RES * 2;
static SemaphoreHandle_t s_vsync_sem;
static int s_vsync_waits = 2;   // vsyncs present() waits for after switching buffers (see vsync_waits())

// Frame-interval watchdog: ~37 Hz refresh (27 ms). A refresh that takes much longer means the bounce-buffer refill was
// starved (flash/PSRAM contention) - the cause of a rolled/shifted frame on screen.
static volatile uint32_t s_vs_frames, s_vs_glitches, s_vs_max_us;
static int64_t s_vs_last;

static bool IRAM_ATTR on_vsync(esp_lcd_panel_handle_t panel, const esp_lcd_rgb_panel_event_data_t *edata, void *user_ctx) {
    BaseType_t woken = pdFALSE;
    int64_t now = esp_timer_get_time();
    if (s_vs_last) {
        uint32_t dt = (uint32_t)(now - s_vs_last);
        if (dt > s_vs_max_us) {
            s_vs_max_us = dt;
        }
        if (dt > 40000 || dt < 15000) {
            s_vs_glitches++;
        }
    }
    s_vs_last = now;
    s_vs_frames++;
    xSemaphoreGiveFromISR(s_vsync_sem, &woken);
    return woken == pdTRUE;
}

#define CHECK(x) do { esp_err_t e_ = (x); if (e_ != ESP_OK) { \
        mp_raise_msg_varg(&mp_type_OSError, MP_ERROR_TEXT("%s failed: 0x%x"), #x, (int)e_); } } while (0)

static mp_obj_t fb_tuple(void) {
    mp_obj_t items[2] = {
        mp_obj_new_memoryview(MP_OBJ_ARRAY_TYPECODE_FLAG_RW | 'B', s_fb_size, s_fbs[0]),
        mp_obj_new_memoryview(MP_OBJ_ARRAY_TYPECODE_FLAG_RW | 'B', s_fb_size, s_fbs[1]),
    };
    return mp_obj_new_tuple(2, items);
}

static mp_obj_t rgb_lcd_init(void) {
    if (s_inited) {
        return fb_tuple();
    }

    esp_lcd_rgb_panel_config_t cfg = {
        .clk_src = LCD_CLK_SRC_DEFAULT,
        .timings = {
            .pclk_hz = LCD_PIXEL_CLOCK_HZ,
            .h_res = LCD_H_RES,
            .v_res = LCD_V_RES,
            .hsync_pulse_width = 4,
            .hsync_back_porch = 8,
            .hsync_front_porch = 8,
            .vsync_pulse_width = 4,
            .vsync_back_porch = 8,
            .vsync_front_porch = 8,
            .flags = {.pclk_active_neg = 1},
        },
        .data_width = 16,
        .num_fbs = 2,
        .bounce_buffer_size_px = LCD_H_RES * LCD_BOUNCE_ROWS,
        .dma_burst_size = 64,
        .hsync_gpio_num = GPIO_NUM_46,
        .vsync_gpio_num = GPIO_NUM_3,
        .de_gpio_num = GPIO_NUM_5,
        .pclk_gpio_num = GPIO_NUM_7,
        .disp_gpio_num = -1,
        .data_gpio_nums = {
            GPIO_NUM_14, GPIO_NUM_38, GPIO_NUM_18, GPIO_NUM_17, GPIO_NUM_10, GPIO_NUM_39, GPIO_NUM_0, GPIO_NUM_45,
            GPIO_NUM_48, GPIO_NUM_47, GPIO_NUM_21, GPIO_NUM_1, GPIO_NUM_2, GPIO_NUM_42, GPIO_NUM_41, GPIO_NUM_40,
        },
        .flags = {.fb_in_psram = 1},
    };
    CHECK(esp_lcd_new_rgb_panel(&cfg, &s_panel));
    s_vsync_sem = xSemaphoreCreateCounting(4, 0);
    esp_lcd_rgb_panel_event_callbacks_t cbs = {.on_vsync = on_vsync};
    CHECK(esp_lcd_rgb_panel_register_event_callbacks(s_panel, &cbs, NULL));
    CHECK(esp_lcd_panel_reset(s_panel));
    CHECK(esp_lcd_panel_init(s_panel));

    CHECK(esp_lcd_rgb_panel_get_frame_buffer(s_panel, 2, &s_fbs[0], &s_fbs[1]));
    for (int i = 0; i < 2; i++) {
        memset(s_fbs[i], 0, s_fb_size);
        esp_cache_msync(s_fbs[i], s_fb_size, ESP_CACHE_MSYNC_FLAG_DIR_C2M | ESP_CACHE_MSYNC_FLAG_UNALIGNED);
    }
    s_inited = true;
    return fb_tuple();
}
static MP_DEFINE_CONST_FUN_OBJ_0(rgb_lcd_init_obj, rgb_lcd_init);

// present(idx, [y1, y2]): write back rows y1..y2 of frame buffer idx, make it the scan-out buffer (the switch happens
// at a frame boundary) and block until it is really on screen, so the caller may render into the other buffer.
static mp_obj_t rgb_lcd_present(size_t n_args, const mp_obj_t *args) {
    if (!s_inited) {
        mp_raise_msg(&mp_type_RuntimeError, MP_ERROR_TEXT("call init() first"));
    }
    int idx = mp_obj_get_int(args[0]) & 1;
    int y1 = n_args > 2 ? mp_obj_get_int(args[1]) : 0;
    int y2 = n_args > 2 ? mp_obj_get_int(args[2]) : LCD_V_RES - 1;
    if (y1 < 0) {
        y1 = 0;
    }
    if (y2 >= LCD_V_RES) {
        y2 = LCD_V_RES - 1;
    }
    if (y2 >= y1) {
        // Bounce buffers are filled by the CPU (through the cache), so this is only belt and braces for the DMA path.
        esp_cache_msync((uint8_t *)s_fbs[idx] + (size_t)y1 * LCD_H_RES * 2, (size_t)(y2 - y1 + 1) * LCD_H_RES * 2,
            ESP_CACHE_MSYNC_FLAG_DIR_C2M | ESP_CACHE_MSYNC_FLAG_UNALIGNED);
    }
    while (xSemaphoreTake(s_vsync_sem, 0) == pdTRUE) {
    }
    // Buffer lies inside a driver frame buffer: only sets it as the next scan-out buffer.
    CHECK(esp_lcd_panel_draw_bitmap(s_panel, 0, 0, LCD_H_RES, LCD_V_RES, s_fbs[idx]));
    // The bounce path picks the new buffer at the start of the next frame; wait for two vsyncs to be sure.
    for (int i = 0; i < s_vsync_waits; i++) {
        xSemaphoreTake(s_vsync_sem, pdMS_TO_TICKS(100));
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(rgb_lcd_present_obj, 1, 3, rgb_lcd_present);

// vsync_waits([n]): get/set how many vsyncs present() waits for (1 or 2). 2 is the conservative default.
static mp_obj_t rgb_lcd_vsync_waits(size_t n_args, const mp_obj_t *args) {
    if (n_args) {
        int n = mp_obj_get_int(args[0]);
        s_vsync_waits = n < 0 ? 0 : (n > 4 ? 4 : n);
    }
    return mp_obj_new_int(s_vsync_waits);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(rgb_lcd_vsync_waits_obj, 0, 1, rgb_lcd_vsync_waits);

// stats() -> (refreshes, glitches, max_interval_us)
static mp_obj_t rgb_lcd_stats(void) {
    mp_obj_t t[3] = {mp_obj_new_int_from_uint(s_vs_frames), mp_obj_new_int_from_uint(s_vs_glitches),
                     mp_obj_new_int_from_uint(s_vs_max_us)};
    return mp_obj_new_tuple(3, t);
}
static MP_DEFINE_CONST_FUN_OBJ_0(rgb_lcd_stats_obj, rgb_lcd_stats);

static const mp_rom_map_elem_t rgb_lcd_globals_table[] = {
    {MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_rgb_lcd)},
    {MP_ROM_QSTR(MP_QSTR_init), MP_ROM_PTR(&rgb_lcd_init_obj)},
    {MP_ROM_QSTR(MP_QSTR_present), MP_ROM_PTR(&rgb_lcd_present_obj)},
    {MP_ROM_QSTR(MP_QSTR_vsync_waits), MP_ROM_PTR(&rgb_lcd_vsync_waits_obj)},
    {MP_ROM_QSTR(MP_QSTR_stats), MP_ROM_PTR(&rgb_lcd_stats_obj)},
    {MP_ROM_QSTR(MP_QSTR_WIDTH), MP_ROM_INT(LCD_H_RES)},
    {MP_ROM_QSTR(MP_QSTR_HEIGHT), MP_ROM_INT(LCD_V_RES)},
};
static MP_DEFINE_CONST_DICT(rgb_lcd_globals, rgb_lcd_globals_table);

const mp_obj_module_t rgb_lcd_user_cmodule = {
    .base = {&mp_type_module},
    .globals = (mp_obj_dict_t *)&rgb_lcd_globals,
};
MP_REGISTER_MODULE(MP_QSTR_rgb_lcd, rgb_lcd_user_cmodule);
