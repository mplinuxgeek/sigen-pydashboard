"""Small in-memory event log shown in Admin > Log (also echoed to the serial console)."""
import time

PERSIST_PATH = "/lastlog.txt"
PERSIST_LINES = 40
_last_persist = None
_persisted_rev = 0

MAX = 80
INFO, WARN, ERROR = 0, 1, 2
_entries = []      # (uptime_ms, level, text)
rev = 0            # bumped on every entry so views can cheaply detect changes


def add(text, level=INFO):
    global rev
    _entries.append((time.ticks_ms(), level, text))
    if len(_entries) > MAX:
        del _entries[0]
    rev += 1
    print("[%s] %s" % ("IWE"[level], text))


def info(text):
    add(text, INFO)


def warn(text):
    add(text, WARN)


def error(text):
    add(text, ERROR)


def last(n):
    """Newest first."""
    return _entries[-n:][::-1]


def since(seq):
    """Entries newer than sequence number `seq` -> (next_seq, [(seq, uptime_ms, level, text)])."""
    first = rev - len(_entries)          # sequence number of _entries[0]
    out = []
    for i, (ms, level, text) in enumerate(_entries):
        n = first + i
        if n >= seq:
            out.append((n, ms, level, text))
    return rev, out


# ---- persistence: keep the tail across reboots (a hung/rebooted panel can then be diagnosed) --------------
def restore():
    """Load the previous boot's log tail into the ring (shown with a 'prev:' prefix)."""
    try:
        with open(PERSIST_PATH) as f:
            lines = f.read().split("\n")
    except OSError:
        return
    n = 0
    for ln in lines:
        if len(ln) > 2 and ln[1] == "|" and ln[0] in "IWE":
            _entries.append((0, "IWE".index(ln[0]), "prev: " + ln[2:]))
            n += 1
    global rev
    rev += n
    if len(_entries) > MAX:
        del _entries[:len(_entries) - MAX]


def persist():
    """Write the last lines of the log to flash."""
    global _last_persist, _persisted_rev
    try:
        with open(PERSIST_PATH, "w") as f:
            for _ms, level, text in _entries[-PERSIST_LINES:]:
                if not text.startswith("prev: "):
                    f.write("%s|%s\n" % ("IWE"[level], text))
        _last_persist, _persisted_rev = time.ticks_ms(), rev
    except OSError:
        pass


def maybe_persist():
    """Cheap, flash-wear friendly: at most every 2 min after a warning/error, every 30 min otherwise."""
    now = time.ticks_ms()
    if _last_persist is None:
        persist()
        return
    if rev == _persisted_rev:
        return
    since = time.ticks_diff(now, _last_persist)
    new = _entries[-(rev - _persisted_rev):] if rev > _persisted_rev else []
    if (since > 120000 and any(e[1] >= WARN for e in new)) or since > 1800000:
        persist()
