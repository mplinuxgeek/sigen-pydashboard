#!/bin/bash
# Copy the Python side to the board over USB (needs mpremote: pip install mpremote).   PORT=/dev/ttyACM0 ./scripts/deploy.sh
. "$(dirname "$0")/common.sh"
cd "$(dirname "$0")/../py"
find_port
P="mpremote connect $PORT resume"
$P fs cp board.py main.py boot.py : || exit 1
for d in core ui www; do [ -d $d ] && { $P fs rm -r :$d 2>/dev/null; $P fs cp -r $d : || exit 1; }; done
$P exec "import machine; machine.RTC().datetime(($(date -u +'%Y, %-m, %-d, 0, %-H, %-M, %-S, 0')))"
echo "Done. Reset the board to start the new code (python3 -m esptool --chip esp32s3 -p $PORT --after hard_reset chip_id)."
