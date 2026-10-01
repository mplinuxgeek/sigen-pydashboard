#!/bin/bash
# First flash over USB (bootloader, partition table, firmware). Later updates go over WiFi (see README).
#   ./flash.sh            uses the first serial port found, or PORT=/dev/ttyACM0 ./flash.sh
. "$(dirname "$0")/scripts/common.sh"
find_port
B="$(cd "$(dirname "$0")" && pwd)/micropython/ports/esp32/build-ESP32_GENERIC_S3"
[ -f "$B/flash_args" ] || { echo "Nothing built yet: run ./build.sh first." >&2; exit 1; }
cd "$B" && python3 -m esptool --chip esp32s3 -p "$PORT" write_flash @flash_args
