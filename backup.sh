#!/bin/bash
# Back up everything on the board that is NOT firmware, over USB: settings, WiFi, admin token and the Python app (vfs),
# monthly totals (nvs) and the 5-minute history. Takes about 35 seconds.
#   ./backup.sh [DIR]           default ./backups/<timestamp>/   (PORT=/dev/ttyACM0 to choose the port)
#   ./backup.sh --full [DIR]    also read the whole 8 MB flash (firmware too), about 2 minutes
# The backup contains the WiFi password and admin token in clear: keep it private (backups/ is git-ignored).
set -e
. "$(dirname "$0")/scripts/common.sh"
FULL=0
[ "${1:-}" = "--full" ] && { FULL=1; shift; }
find_port
OUT=${1:-"$(cd "$(dirname "$0")" && pwd)/backups/$(date +%Y%m%d-%H%M%S)"}
mkdir -p "$OUT"; chmod 700 "$OUT"
echo "Backing up to $OUT from $PORT"
: > "$OUT/MANIFEST"
for p in nvs history vfs; do
    read -r off size < <(part_info $p)
    run_esptool --chip esp32s3 -p "$PORT" -b 921600 read_flash "$off" "$size" "$OUT/$p.bin" >/dev/null
    echo "$p $off $size $(sha256sum "$OUT/$p.bin" | cut -d' ' -f1)" >> "$OUT/MANIFEST"
    echo "  $p ($off, $((size / 1024)) KB)"
done
if [ $FULL = 1 ]; then
    run_esptool --chip esp32s3 -p "$PORT" -b 921600 read_flash 0x0 0x800000 "$OUT/flash-full.bin" >/dev/null
    echo "flash-full 0x0 8388608 $(sha256sum "$OUT/flash-full.bin" | cut -d' ' -f1)" >> "$OUT/MANIFEST"
    echo "  full flash image"
fi
chmod 600 "$OUT"/*
echo "Done: $OUT"
