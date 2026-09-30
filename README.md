# Sigen dashboard on MicroPython (Waveshare ESP32-S3-Touch-LCD-7)

A port of [`sigen-dashboard`](../sigen-dashboard) (ESP-IDF / C / LVGL) to MicroPython + LVGL 9, built on
[`esp-lcd-micropython-skeleton`](../esp-lcd-micropython-skeleton). It shows a Sigenergy SigenStor's live battery / solar /
load / grid power on the 800x480 touch panel, keeps 31 days of history and 36 months of totals, and serves the same HTTP API
and web page as the C firmware.

**Why:** the ESP-IDF build ran internal SRAM down to a few hundred bytes. Here the interpreter code, read-only data, the whole
Python + LVGL heap and both frame buffers live in the 8 MB PSRAM. Measured with everything running (WiFi, Modbus polling,
HTTP server, 8.8k-sample history, all screens built): **internal SRAM 158 KB free (84 KB largest block), PSRAM 3.1 MB free,
Python heap 3.6 MB free.**

## Features (all ported)
Dashboard (4 quadrants, peak markers, source-split bars) · Graph (paged day view) · Monthly (bar chart, billing cycle) ·
System Info / Settings / WiFi tabs · landscape **and portrait** · 5-minute history in a raw flash ring (31 days) · monthly and
per-day totals · SNTP + POSIX time zones (`www/tzdata.json`) · WiFi provisioning (setup AP + captive portal + on-device
WiFi manager) · screen blanking, scheduled night screen off, optional PWM backlight curve · HTTP API + landing page +
Chart.js history page · CSV import/export · **OTA** for firmware (dual slots, rollback) and for the Python app (rollback).

## Layout
```
build.sh                 build the firmware (IDF 5.5.4; `~/esp/esp-idf-v5.5.4/install.sh esp32s3` once)
board_s3_7/              board definition: sdkconfig, partitions (dual OTA + history + FAT), lv_conf.h
usermod/rgb_lcd/         C module: RGB panel, 2 PSRAM frame buffers, vsync, rotated blit for portrait
fonts/                   icon fonts (Material Design icons) compiled into LVGL
py/                      the application (copied to the board's FAT filesystem)
  boot.py                Python-update rollback guard
  board.py               display / touch / CH422G / LVGL loop, portrait rotation
  main.py                wiring + first-run flow
  core/                  logic without widgets: modbus, history, monthly, wifi, portal, http, api, ota, backlight ...
  ui/                    LVGL screens: dashboard, graph, monthly, info, settings, wifi, shell (page navigator)
  www/                   landing page, history chart, Chart.js, setup portal, tzdata.json
  tests/                 host tests: `cd py && python3 -m unittest discover tests`
patches/                 local patches to the vendored micropython / lv_binding trees
scripts_ota.sh           push py/ over the network (POST /api/ota/py)
shot.sh                  PNG screenshot over HTTP
```

## Build, flash, deploy
```
./build.sh -j8                                    # -> micropython/ports/esp32/build-ESP32_GENERIC_S3/
# first flash over USB (writes bootloader, partition table, otadata and the app into ota_0):
cd micropython/ports/esp32/build-ESP32_GENERIC_S3 && python -m esptool --chip esp32s3 -p /dev/ttyACM1 write_flash @flash_args
cd ../../../../py && ./deploy.sh                  # copy py/ to the board over USB (mpremote ... resume)
```
After that, updates need no cable:
```
curl -X POST -H "X-OTA-Token: $T" --data-binary @micropython.bin http://HOST/api/ota      # firmware (~1 min)
./scripts_ota.sh HOST TOKEN                                                                # Python app (~45 s)
```
First boot: the panel opens an AP `ESP32-Setup-XXXXXX` (open, 192.168.4.1) with a captive portal, or pick a network on the
touchscreen itself; then it asks for the inverter's IP. The admin token (`X-OTA-Token`) is generated on first boot and shown in
Settings > OTA Key.

Notes: use `mpremote ... resume` (a soft reset is fine here, but `resume` avoids killing the UI loop). Never pass `BUILD=` to
`make` (it leaks into the mpy-cross sub-make). Flash writes stall the cache: the history ring writes one 32-byte record per
5 minutes, whole sectors on import.

## Differences from the C firmware
* Modbus reads are individual registers 1 s apart (same pacing rule) so a poll cycle is ~35 s, exactly as before.
* Bulk history import is slower (about 1 min for 31 days) and `GET /api/history` takes ~20 s; the UI keeps running meanwhile.
* No core dump / LVGL lock (cooperative event loop instead of tasks). Timezone default is Australia/Sydney as before: change it in Settings.
* Firmware OTA needs the dual-slot partition layout (flash it over USB once).
* The app files live in FAT, so `main.py` etc. can be edited on the board.

## Status
Verified on hardware: WiFi join + on-device setup, live Modbus data, dashboard/graph/monthly/info/settings/WiFi screens in both
orientations (rotation direction confirmed), history + monthly import of the old device's data, HTTP API and web page, firmware
OTA and Python OTA. Not yet exercised on hardware: the phone-side captive portal, PWM backlight (needs the GPIO jumper), and a
long soak test.
