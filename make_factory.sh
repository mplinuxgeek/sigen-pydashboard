#!/bin/bash
# Assemble the release files from a finished ./build.sh into dist/ (the release workflow runs this too):
#   dist/sigen-pydashboard-factory.bin   8 MB, flash at 0x0: bootloader + partitions + firmware + Python app (erases settings/history)
#   dist/sigen-pydashboard-ota.bin       firmware only, for POST /api/ota (never flash at 0x0)
#   dist/sigen-pydashboard-app.tar       Python app only, for POST /api/ota/py
#   dist/SHA256SUMS
# Needs ESP-IDF (esptool); installs littlefs-python into its Python environment if missing.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/versions.env"
. "$HERE/scripts/common.sh"
load_idf
B="$HERE/micropython/ports/esp32/build-ESP32_GENERIC_S3"
[ -f "$B/flash_args" ] || { echo "Nothing built yet: run ./build.sh first." >&2; exit 1; }
python3 -c "import littlefs" 2>/dev/null || python3 -m pip install --quiet littlefs-python
D="$HERE/dist"
rm -rf "$D"; mkdir -p "$D"
python3 "$HERE/scripts/make_fs_image.py" "$D/fs.bin"
(cd "$B" && python3 -m esptool --chip esp32s3 merge_bin --fill-flash-size 8MB -o "$D/sigen-pydashboard-factory.bin" @flash_args 0x5F0000 "$D/fs.bin")
cp "$B/micropython.bin" "$D/sigen-pydashboard-ota.bin"
tar cf "$D/sigen-pydashboard-app.tar" --exclude=__pycache__ --exclude=tests --exclude=deploy.sh -C "$HERE/py" board.py main.py boot.py core ui www
rm "$D/fs.bin"
(cd "$D" && sha256sum * > SHA256SUMS && cat SHA256SUMS)
