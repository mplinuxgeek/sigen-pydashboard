# ESP LCD MicroPython Skeleton

MicroPython + LVGL on the Waveshare ESP32-S3-Touch-LCD-7 (800x480). Bring-up skeleton: build, flash, run, then add your app in `py/`.

Port of `../p4python` (Guition JC1060P470C, ESP32-P4) to the S3 board that `../sigen-dashboard` (ESP-IDF) runs on.
Goal: keep internal SRAM free by running code/rodata and the whole Python + LVGL heap from PSRAM.

```
build.sh              build firmware (IDF 5.5.4, needs `install.sh esp32s3` once) -> micropython/ports/esp32/build-ESP32_GENERIC_S3
board_s3_7/           board def: mpconfigboard.*, sdkconfig.board, partitions.csv (8MB: 4MB app + 4MB FAT), lv_conf.h
usermod/rgb_lcd/      C module: 800x480 RGB panel, 2 PSRAM framebuffers + SRAM bounce buffers, present(), vsync stats
py/board.py           CH422G expander (backlight/reset), GT911 touch, LVGL double-buffered DIRECT flush, main loop
py/main.py            bring-up demo: memory / vsync stats, touch dot, slider
py/deploy.sh          copy py/ to the board (PORT=/dev/ttyACM1)
```

Flash: `python -m esptool --chip esp32s3 -p /dev/ttyACM1 -b 460800 write_flash @flash_args` from the build dir
(if the FAT area holds foreign data: `erase_region 0x410000 0x3F0000`).

## Memory (measured, demo running)
| | free |
|---|---|
| Internal SRAM (366 KB heap) | 230 KB, largest block 156 KB |
| PSRAM (5.7 MB heap after 1.5 MB framebuffers + XIP code) | 4.1 MB |
| Python heap (in PSRAM) | 4.1 MB |

Enablers (`board_s3_7/sdkconfig.board`): `SPIRAM_FETCH_INSTRUCTIONS` + `SPIRAM_RODATA` (code/rodata from PSRAM),
`LCD_RGB_ISR_IRAM_SAFE` (panel keeps scanning during flash writes), MicroPython's GC heap and LVGL (`LV_STDLIB_MICROPYTHON`) in PSRAM.

## Notes
* `rgb_lcd.vsync_waits(n)`: vsyncs `present()` waits for (driver default 2, board.py sets 2). 1 doubled the animation frame rate (13 -> 26 fps) with 0 vsync glitches; but showed glitching while dragging a slider, so `board.init()` sets 2.
* Backlight is on/off only (CH422G output, no PWM). Touch reset + LCD reset also on the CH422G.
* Do not override `BUILD=` in make: it leaks into the mpy-cross sub-make and breaks the link (`mp_module_string`).
* Panel: 13.5 MHz pclk (ST7262 HSYNC period spec), 20-row bounce buffers (see sigen-dashboard sdkconfig.defaults history for why not 32).
* Not ported yet: the Shelly-specific `core/ui/features` app framework, custom fonts, camera/audio (P4-only hardware).

## Vendored trees (not tracked in this repo)
`micropython/` (v1.29.0, commit 0fd6c57) and `lv_binding_micropython/` (+ its `lvgl`, `pycparser` submodules) are plain copies
from `../p4python` with local patches, saved in `patches/` (`micropython-esp32.patch`: extra IDF components + LVGL soft-reset
restart in main.c; `lv_binding-gen_mpy.patch`: callback exceptions no longer unwind through LVGL). Re-clone them and apply the
patches to rebuild elsewhere; the `esp_video`/camera bits in the patch header are P4-only and can be dropped.
