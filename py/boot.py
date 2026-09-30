# Runs before main.py. Safety net for Python OTA updates (features/maintenance/ota):
# an update leaves /ota_pending; if the new code fails to run stably for 3 boots the old files are restored.
import os


def _exists(p):
    try:
        os.stat(p)
        return True
    except OSError:
        return False


def _copy_tree(src, dst):
    for name in os.listdir(src):
        s, d = src + "/" + name, (dst + "/" + name) if dst else name
        if os.stat(s)[0] & 0x4000:
            try:
                os.mkdir(d)
            except OSError:
                pass
            _copy_tree(s, d)
        else:
            with open(s, "rb") as f, open(d, "wb") as g:
                while True:
                    chunk = f.read(2048)
                    if not chunk:
                        break
                    g.write(chunk)


def _rm_tree(p):
    try:
        for name in os.listdir(p):
            q = p + "/" + name
            if os.stat(q)[0] & 0x4000:
                _rm_tree(q)
            else:
                os.remove(q)
        os.rmdir(p)
    except OSError:
        pass


try:
    if _exists("/ota_pending"):
        import json
        with open("/ota_pending") as f:
            st = json.load(f)
        st["n"] = st.get("n", 0) + 1
        try:                                   # a failed new version must not sit at the REPL forever
            from machine import WDT
            WDT(timeout=120000)
        except Exception:
            pass
        if st["n"] > 3 and _exists("/ota_bak"):
            print("[E] OTA: new version failed to run, rolling back")
            _copy_tree("/ota_bak", "")
            _rm_tree("/ota_bak")
            os.remove("/ota_pending")
            import machine
            machine.reset()
        else:
            with open("/ota_pending", "w") as f:
                json.dump(st, f)
except Exception as e:
    print("[E] boot.py:", e)
