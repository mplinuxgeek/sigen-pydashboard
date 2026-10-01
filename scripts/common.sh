# Shared helpers, sourced by the scripts in the repo root. Settings come from the environment:
#   PANEL_HOST   panel address (IP or name)                         e.g. 192.168.1.50
#   PANEL_TOKEN  admin token (Settings > OTA Key on the panel)
#   PORT         USB serial port of the board                       e.g. /dev/ttyACM0
# A host or token can also be given as the first / second argument where a script says so.

need_host() {
    [ -n "${PANEL_HOST:-}" ] || { echo "Set PANEL_HOST (the panel's IP address) or pass it as an argument." >&2; exit 2; }
}

need_token() {
    [ -n "${PANEL_TOKEN:-}" ] || { echo "Set PANEL_TOKEN (shown on the panel under Settings > OTA Key)." >&2; exit 2; }
}

# find_port: first USB serial device, preferring ones that look like an ESP32-S3 (Espressif / CH340 / CP210x bridges)
find_port() {
    if [ -n "${PORT:-}" ]; then return; fi
    for p in /dev/ttyACM* /dev/ttyUSB* /dev/cu.usbmodem* /dev/cu.usbserial*; do
        [ -e "$p" ] && { PORT=$p; return; }
    done
    echo "No serial port found. Plug the board in (USB port 'UART'), or set PORT." >&2
    exit 2
}

# load_idf: make idf.py available. Uses the environment you already exported, else $IDF_PATH, else ~/esp/esp-idf-v$IDF_VERSION.
load_idf() {
    command -v idf.py >/dev/null 2>&1 && return
    local idf=${IDF_PATH:-$HOME/esp/esp-idf-v$IDF_VERSION}
    if [ ! -f "$idf/export.sh" ]; then
        echo "ESP-IDF $IDF_VERSION not found. Install it (https://docs.espressif.com/projects/esp-idf/), run its" >&2
        echo "install.sh esp32s3, then source export.sh or set IDF_PATH." >&2
        exit 1
    fi
    . "$idf/export.sh" >/dev/null
}
