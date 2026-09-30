"""JSON blobs in NVS (wear-levelled, unlike FAT files rewritten every few minutes)."""
import json

import esp32

_nvs = None


def _n():
    global _nvs
    if _nvs is None:
        _nvs = esp32.NVS("sigen")
    return _nvs


def get(key, default=None):
    try:
        buf = bytearray(4000)
        n = _n().get_blob(key, buf)
        return json.loads(bytes(buf[:n]))
    except (OSError, ValueError):
        return default


def put(key, obj):
    n = _n()
    n.set_blob(key, json.dumps(obj).encode())
    n.commit()


def erase(key):
    try:
        _n().erase_key(key)
        _n().commit()
    except OSError:
        pass
