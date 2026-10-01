# Architecture

## Process model
MicroPython runs one `asyncio` loop. `main.py` wires the services and starts the tasks; `board.py` runs the LVGL loop
(`lv.task_handler()` every ~2 ms, 10 ms refresh and touch timers). Nothing blocks for long: Modbus, HTTP, history writes and
imports yield between steps, and the loop logs a warning when it is held for more than 300 ms (`/api/logs`).

```
boot.py        Python-update rollback guard (restores the previous app after 3 failed boots)
main.py        settings -> board.init -> services (wifi, ntp, modbus, history, monthly, http, ota, backlight, blank) -> UI shell
board.py       RGB panel + CH422G expander + GT911 touch + LVGL display/indev glue, render modes, page slide
core/          logic with no widgets (unit-tested on the host where it does not need hardware)
ui/            LVGL screens; shell.py is the page navigator (swipe, dots, idle return)
www/           landing page, history chart, Chart.js, setup portal, tzdata.json
```

## Memory
Code, read-only data, the Python heap, LVGL's heap and both frame buffers live in the 8 MB octal PSRAM
(`SPIRAM_FETCH_INSTRUCTIONS`, `SPIRAM_RODATA`); internal SRAM keeps the interpreter's hot data, DMA/bounce buffers, the LVGL
draw buffer and WiFi. Typical free after boot: ~75 KB internal, ~2-3 MB PSRAM, ~3.2 MB Python heap.

## Display
`usermod/rgb_lcd` drives the 800x480 RGB panel through `esp_lcd` with two PSRAM frame buffers and bounce buffers. Modes
(`board.init`, selected by settings; timings are in the README):

| Mode | Setting | How it renders |
|---|---|---|
| partial + single buffer (default, landscape) | `ui.partial` true, `ui.single` true | LVGL draws 40-row strips into internal SRAM, `rgb_lcd.blit` copies them into the live buffer. No vsync waits: fastest, a large redraw can briefly tear |
| partial + double buffer | `ui.single` false | strips go to the back buffer, then `present()` swaps at a frame boundary (2 vsync waits) and `copy_rect` keeps both buffers equal. Tear-free |
| portrait | orientation setting | always partial; `rgb_lcd.blit_rot` rotates strips into the panel |
| direct | `ui.partial` false | LVGL renders straight into the PSRAM buffers (slowest) |

Page slides (landscape + single buffer, `ui.animate`): the new page is rendered into the spare buffer, then
`rgb_lcd.slide()` pushes it across the live one in a few eased steps (PSRAM bandwidth limits it to ~15 fps).

## Storage
| What | Where |
|---|---|
| App files | FAT filesystem in flash (`py/` copied there; OTA replaces them with a backup) |
| Settings, WiFi credentials | `settings.json` on FAT |
| 5-minute history (31 days) | raw `history` partition, ring of 32-byte records (`<IIhxx4i4x`), bisected by timestamp |
| Monthly / per-day totals, billing progress | NVS JSON blobs |
| Firmware | two 3 MB OTA slots (`board_s3_7/partitions.csv`) with rollback |

## Network
`core/wifi.py` joins the saved network or opens a setup AP (`ESP32-Setup-XXXXXX`) with a captive portal. `core/http.py` is a small
asyncio HTTP/1.1 server (route table, streamed bodies, per-IP token throttling). `core/api.py` is the route table; `GET /api`
documents it. SNTP uses `ntptime` with POSIX time zone strings (`core/tz.py`).

## Modbus
`core/modbus.py` reads the Sigenergy plant registers over Modbus TCP (unit 247 plant, 1 device info), one register block at a time,
1 s apart (a ~35 s cycle, the pacing the inverter tolerates). Values are applied to `core/state.py` atomically per cycle.

## Rendering knobs (`POST /api/tuning`)
`ui.partial` (default true), `ui.rows` (draw-buffer rows, default 40), `ui.single` (default true), `ui.animate` (default true). They take effect on restart.
