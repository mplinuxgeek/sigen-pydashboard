"""Tiny persistent key/value store (JSON in the flash filesystem)."""
import json

PATH = "/settings.json"
_data = None


def _load():
    global _data
    if _data is None:
        try:
            with open(PATH) as f:
                _data = json.load(f)
        except (OSError, ValueError):
            _data = {}
    return _data


def get(key, default=None):
    return _load().get(key, default)


def set(key, value):
    """Store a value; a write that changes nothing costs nothing (each real write rewrites the whole file in FAT)."""
    d = _load()
    if key in d and d[key] == value:
        return
    d[key] = value
    _save()


def delete(key):
    d = _load()
    if key in d:
        del d[key]
        _save()


def _save():
    tmp = PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(_data, f)
    import os
    try:
        os.remove(PATH)
    except OSError:
        pass
    os.rename(tmp, PATH)
