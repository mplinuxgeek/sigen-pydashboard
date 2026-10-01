#!/bin/bash
# Flash the board over USB.
#   ./flash.sh                       flash what ./build.sh built (bootloader, partitions, firmware); then ./py/deploy.sh for the app
#   ./flash.sh sigen-pydashboard-factory.bin   flash a release's factory image (everything, at 0x0); erases settings and history
# Port: first serial device found, or PORT=/dev/ttyACM0 ./flash.sh
. "$(dirname "$0")/scripts/common.sh"
find_port
if [ -n "${1:-}" ]; then
    [ -f "$1" ] || { echo "No such file: $1" >&2; exit 1; }
    case "$1" in *factory*) ;; *) echo "Refusing: only a *-factory.bin image may be written at 0x0 (the -ota.bin file is an app image)." >&2; exit 1;; esac
    python3 -m esptool --chip esp32s3 -p "$PORT" -b 921600 write_flash 0x0 "$1"
    exit
fi
B="$(cd "$(dirname "$0")" && pwd)/micropython/ports/esp32/build-ESP32_GENERIC_S3"
[ -f "$B/flash_args" ] || { echo "Nothing built yet: run ./build.sh first." >&2; exit 1; }
cd "$B" && python3 -m esptool --chip esp32s3 -p "$PORT" write_flash @flash_args
