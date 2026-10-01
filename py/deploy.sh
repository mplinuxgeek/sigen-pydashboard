#!/bin/bash
# Copy the Python side to the board. Usage: PORT=/dev/ttyACM1 ./deploy.sh
cd "$(dirname "$0")"
PORT=${PORT:-$(for p in /dev/ttyACM*; do udevadm info -q property -n $p 2>/dev/null | grep -q "ID_MODEL_ID=55d3" && echo $p; done | head -1)}
P="mpremote connect $PORT resume"
$P fs cp board.py main.py boot.py : || exit 1
for d in core ui features www; do [ -d $d ] && { $P fs rm -r :$d 2>/dev/null; $P fs cp -r $d : || exit 1; }; done
$P exec "import machine; machine.RTC().datetime(($(date -u +'%Y, %-m, %-d, 0, %-H, %-M, %-S, 0')))"
# Reset with: python -m esptool --chip esp32s3 -p $PORT --after hard_reset chip_id
