#!/bin/bash
# Restore a backup made by ./backup.sh onto the board over USB (settings, WiFi, token, app, monthly totals, history).
# The firmware is not touched. Everything currently in those partitions is overwritten.
#   ./restore.sh DIR [--yes]         (PORT=/dev/ttyACM0 to choose the port)
#   ./restore.sh DIR --full [--yes]  write flash-full.bin at 0x0 instead (firmware too; needs a --full backup)
# Typical use: ./backup.sh && ./flash.sh dist/sigen-pydashboard-factory.bin && ./restore.sh backups/<that backup>
set -e
. "$(dirname "$0")/scripts/common.sh"
DIR=${1:-}; shift || true
[ -n "$DIR" ] && [ -f "$DIR/MANIFEST" ] || { echo "Usage: $0 BACKUP_DIR [--full] [--yes]" >&2; exit 2; }
FULL=0; YES=0
for a in "$@"; do case $a in --full) FULL=1;; --yes) YES=1;; *) echo "Unknown option $a" >&2; exit 2;; esac; done
find_port
# verify the files against the manifest before touching the board
while read -r name off size sum; do
    [ -f "$DIR/$name.bin" ] || { echo "Missing $DIR/$name.bin" >&2; exit 1; }
    [ "$(sha256sum "$DIR/$name.bin" | cut -d' ' -f1)" = "$sum" ] || { echo "Checksum mismatch: $name.bin (backup damaged?)" >&2; exit 1; }
done < "$DIR/MANIFEST"
if [ $FULL = 1 ]; then
    [ -f "$DIR/flash-full.bin" ] || { echo "$DIR has no flash-full.bin (back up with --full)" >&2; exit 1; }
    ARGS=(0x0 "$DIR/flash-full.bin"); WHAT="the ENTIRE flash (firmware included)"
else
    ARGS=()
    for p in nvs history vfs; do read -r off _ < <(part_info $p); ARGS+=("$off" "$DIR/$p.bin"); done
    WHAT="settings, WiFi, token, app, monthly totals and history"
fi
if [ $YES = 0 ]; then
    read -r -p "Overwrite $WHAT on $PORT with $DIR? [y/N] " ans
    [ "$ans" = y ] || [ "$ans" = Y ] || { echo "Cancelled."; exit 1; }
fi
run_esptool --chip esp32s3 -p "$PORT" -b 921600 write_flash "${ARGS[@]}"
echo "Restored. The board restarts by itself."
