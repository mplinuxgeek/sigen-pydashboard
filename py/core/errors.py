"""Error capture: turns uncaught-exception tracebacks (e.g. from LVGL callbacks, printed by the firmware)
into Admin > Log / /api/logs entries, and helpers to describe exceptions compactly."""
import io
import sys

from . import log


def describe(exc):
    """'ValueError: boom (ui/x.py:42 in fn)' - the last traceback frame plus the exception."""
    buf = io.StringIO()
    sys.print_exception(exc, buf)
    return _summarise(buf.getvalue().split("\n"))


def _summarise(lines):
    frame = ""
    final = ""
    for ln in lines:
        s = ln.strip()
        if s.startswith("File "):
            frame = s
        elif s and not s.startswith("Traceback") and not s.startswith("Exception in") and ln[:1] != " ":
            final = s
    where = ""
    if frame:                                     # File "ui/x.py", line 42, in fn
        try:
            path = frame.split('"')[1]
            rest = frame.split("line ")[1]
            num, _, fn = rest.partition(", in ")
            where = " (%s:%s in %s)" % (path, num.strip(), fn.strip())
        except IndexError:
            where = " (%s)" % frame
    return (final or "exception") + where


def _nice(name):
    """'lv_timer_create_timer_xcb' -> 'timer create timer callback'"""
    n = name
    for a in ("lv_", "_xcb", "_cb", "_callback"):
        n = n.replace(a, " ")
    return n.strip().replace("_", " ") + " callback"


_count = 0


def _hook(name, exc):
    """Called by the LVGL binding when a Python callback raised (the exception was already printed)."""
    global _count
    _count += 1
    try:
        log.error(("%s: %s" % (_nice(name), describe(exc)))[:170])
    except Exception:
        pass


def install():
    """Route exceptions from LVGL callbacks (timers, events, flush/read callbacks) into the log."""
    try:
        import lvgl as lv
        lv.set_error_hook(_hook)
    except Exception as e:
        log.warn("errors: hook not installed: %r" % (e,))


def count():
    return _count
