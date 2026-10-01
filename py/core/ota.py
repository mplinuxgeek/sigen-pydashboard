"""Over-the-air updates.

Firmware (POST /api/ota): a MicroPython .bin streamed into the inactive OTA slot, set as the next boot image; the new image
confirms itself after OTA_CONFIRM_S of stable uptime or the bootloader rolls back (same scheme as the ESP-IDF build).
Python application (POST /api/ota/py): a .tar of the py/ tree staged in /ota_new, applied over the running files with a
backup in /ota_bak; boot.py rolls back automatically if the new code fails to stay up for 3 boots.
"""
import asyncio
import json
import os
import sys

from . import http

OTA_CONFIRM_S = 10
APP_ENTRIES = ("board.py", "main.py", "boot.py", "core", "ui", "www", "features")
BLOCK = 4096


def _exists(p):
    try:
        os.stat(p)
        return True
    except OSError:
        return False


def _isdir(p):
    try:
        return bool(os.stat(p)[0] & 0x4000)
    except OSError:
        return False


def _rm_tree(p):
    try:
        if _isdir(p):
            for n in os.listdir(p):
                _rm_tree(p + "/" + n)
            os.rmdir(p)
        else:
            os.remove(p)
    except OSError:
        pass


async def _rm_tree_async(p):
    """Like _rm_tree but yields between files, so deleting the backup of a big update does not freeze the UI."""
    try:
        if _isdir(p):
            for n in os.listdir(p):
                await _rm_tree_async(p + "/" + n)
            os.rmdir(p)
        else:
            os.remove(p)
    except OSError:
        pass
    await asyncio.sleep_ms(0)


def _mkdirs(path):
    cur = ""
    for part in path.strip("/").split("/"):
        cur += "/" + part
        if not _exists(cur):
            os.mkdir(cur)


def _copy_tree(src, dst):
    if _isdir(src):
        _mkdirs(dst)
        for n in os.listdir(src):
            _copy_tree(src + "/" + n, dst + "/" + n)
    else:
        with open(src, "rb") as f, open(dst, "wb") as g:
            while True:
                chunk = f.read(2048)
                if not chunk:
                    break
                g.write(chunk)


# ---- firmware slots -----------------------------------------------------------------------------------------
def _partitions():
    try:
        import esp32
        run = esp32.Partition(esp32.Partition.RUNNING)
        return esp32, run
    except Exception:
        return None, None


def info():
    """Shape of GET /api/ota and the firmware card of /api/system."""
    esp32, run = _partitions()
    running, inactive, state, inactive_ver = "factory", "none", "valid", "n/a"
    if run is not None:
        try:
            running = run.info()[4]
            nxt = run.get_next_update()
            inactive = nxt.info()[4]
            inactive_ver = "unknown"
        except Exception:
            pass
    v = sys.implementation.version
    from . import api
    return {"project_name": api.PROJECT, "version": api.VERSION,
            "idf_version": "MicroPython v%d.%d.%d" % v[:3], "built": sys.version.split(" on ")[-1].split(";")[0],
            "running_partition": running, "image_state": state, "inactive_slot": inactive,
            "inactive_version": inactive_ver, "running_slot": running}


def firmware_slot_available():
    esp32, run = _partitions()
    if run is None:
        return False
    try:
        run.get_next_update()
        return True
    except Exception:
        return False


async def upload_firmware(req, app):
    esp32, run = _partitions()
    try:
        target = run.get_next_update()
    except Exception:
        return http.err(409, "no OTA slot: this device runs a single-slot partition table (flash the OTA layout over USB once)")
    size = target.info()[3]
    if req.length <= 0 or req.length > size:
        return http.err(413, "image does not fit the OTA slot (%d bytes)" % size)
    app.services["poller"].pause(True)
    app.log.info("ota: receiving %d bytes into %s" % (req.length, target.info()[4]))
    block = 0
    buf = b""
    first = True
    got = 0
    try:
        while got < req.length:
            chunk = await req.read(2048)
            if not chunk:
                break
            got += len(chunk)
            buf += chunk
            while len(buf) >= BLOCK:
                if first:
                    if buf[0] != 0xE9:
                        raise ValueError("not an ESP32 app image (bad magic byte)")
                    first = False
                target.writeblocks(block, buf[:BLOCK])
                block += 1
                buf = buf[BLOCK:]
            await asyncio.sleep_ms(0)
        if got != req.length:
            raise ValueError("upload truncated (%d of %d bytes)" % (got, req.length))
        if buf:
            target.writeblocks(block, buf + b"\xff" * (BLOCK - len(buf)))
        target.set_boot()
    except Exception as e:
        app.services["poller"].pause(False)
        app.log.error("ota: firmware update failed: %r" % (e,))
        return http.err(400, str(e))
    app.log.info("ota: firmware written (%d bytes), rebooting into it" % got)

    async def later():
        await asyncio.sleep_ms(800)
        from . import system
        system.reboot(app, "Firmware OTA")
    asyncio.create_task(later())
    return {"ok": True, "bytes": got, "rebooting": True}


def confirm_task(app):
    """Firmware rollback cancel + Python-update confirmation once the new build has stayed up long enough."""
    async def run():
        await asyncio.sleep(OTA_CONFIRM_S)
        try:
            import esp32
            esp32.Partition.mark_app_valid_cancel_rollback()
            app.log.info("ota: stayed up %ds, firmware rollback canceled" % OTA_CONFIRM_S)
        except Exception:
            pass
        if _exists("/ota_pending"):
            await asyncio.sleep(50)
            os.remove("/ota_pending")
            await _rm_tree_async("/ota_bak")
            app.log.info("ota: Python update confirmed")
    return run


# ---- Python application update ------------------------------------------------------------------------------
async def upload_python(req, app):
    stage = "/ota_new"
    _rm_tree(stage)
    _mkdirs(stage)
    app.services["poller"].pause(True)
    buf = b""
    got = 0
    files = 0
    try:
        async def need(n):
            nonlocal buf, got
            while len(buf) < n:
                chunk = await req.read(2048)
                if not chunk:
                    raise ValueError("archive truncated")
                buf += chunk
                got += len(chunk)
        while True:
            await need(512)
            hdr, buf = buf[:512], buf[512:]
            if hdr == b"\x00" * 512:
                break
            name = hdr[0:100].split(b"\x00")[0].decode()
            prefix = hdr[345:500].split(b"\x00")[0].decode()
            if prefix:
                name = prefix + "/" + name
            name = name.lstrip("./")
            size = int((hdr[124:136].split(b"\x00")[0].strip() or b"0"), 8)
            typ = hdr[156:157]
            if ".." in name.split("/") or name.startswith("/"):
                raise ValueError("unsafe path in archive: %s" % name)
            if typ == b"5":
                if name:
                    _mkdirs(stage + "/" + name.rstrip("/"))
                continue
            if typ not in (b"0", b"\x00"):
                await need(size + (-size) % 512)
                buf = buf[size + (-size) % 512:]
                continue
            d = name.rpartition("/")[0]
            if d:
                _mkdirs(stage + "/" + d)
            left = size
            with open(stage + "/" + name, "wb") as f:
                while left > 0:
                    await need(min(left, 512))
                    n = min(left, len(buf))
                    f.write(buf[:n])
                    buf = buf[n:]
                    left -= n
            pad = (-size) % 512
            await need(pad)
            buf = buf[pad:]
            files += 1
            if files % 8 == 0:
                await asyncio.sleep_ms(0)
        # drain whatever trailing padding the client still sends
        while got < req.length:
            if not await req.read(2048):
                break
        if not (_exists(stage + "/main.py") and _exists(stage + "/board.py")):
            raise ValueError("archive must contain main.py and board.py at its top level")
    except Exception as e:
        _rm_tree(stage)
        app.services["poller"].pause(False)
        app.log.error("ota: python update rejected: %r" % (e,))
        return http.err(400, str(e))
    # apply: back up the running tree, then replace it entry by entry
    _rm_tree("/ota_bak")
    _mkdirs("/ota_bak")
    for name in APP_ENTRIES:
        if _exists(name):
            _copy_tree(name, "/ota_bak/" + name)
    for name in os.listdir(stage):
        _rm_tree(name)
        _copy_tree(stage + "/" + name, name)
    _rm_tree(stage)
    with open("/ota_pending", "w") as f:
        json.dump({"n": 0}, f)
    app.log.info("ota: python update installed (%d files), rebooting" % files)

    async def later():
        await asyncio.sleep_ms(800)
        from . import system
        system.reboot(app, "Python OTA")
    asyncio.create_task(later())
    return {"ok": True, "files": files, "rebooting": True}


def register(app, server):
    async def ota_post(req):
        return await upload_firmware(req, app)

    async def py_post(req):
        return await upload_python(req, app)

    def ota_get(req):
        i = info()
        return {"project_name": i["project_name"], "version": i["version"], "idf_version": i["idf_version"],
                "running_partition": i["running_partition"], "built": i["built"]}

    def version(req):
        i = info()
        return {"version": i["version"], "running_slot": i["running_slot"], "inactive_version": i["inactive_version"],
                "inactive_slot": i["inactive_slot"]}
    server.route("GET", "/api/ota", ota_get)
    server.route("GET", "/api/version", version)
    server.route("POST", "/api/ota", ota_post, auth=True, stream=True)
    server.route("POST", "/api/ota/py", py_post, auth=True, stream=True)
