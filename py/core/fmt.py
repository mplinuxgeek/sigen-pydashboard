"""Small text formatters shared by the screens (no hardware, unit-tested on the host)."""


def duration(s):
    """Elapsed seconds as a short string: 45s, 3m 20s, 5h 07m, 2d 4h."""
    s = max(0, int(s))
    if s < 60:
        return "%ds" % s
    if s < 3600:
        return "%dm %ds" % (s // 60, s % 60)
    if s < 86400:
        return "%dh %02dm" % (s // 3600, s % 3600 // 60)
    return "%dd %dh" % (s // 86400, s % 86400 // 3600)


def ago(s):
    """'just now', '45s ago', '3m ago', '5h ago', '2d ago' (one unit, rounded down)."""
    s = max(0, int(s))
    if s < 10:
        return "just now"
    if s < 60:
        return "%ds ago" % s
    if s < 3600:
        return "%dm ago" % (s // 60)
    if s < 86400:
        return "%dh ago" % (s // 3600)
    return "%dd ago" % (s // 86400)
