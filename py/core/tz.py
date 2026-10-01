"""Time zones from POSIX TZ strings (the same strings www/tzdata.json carries), applied to Unix-epoch seconds.

    tz.local(unix=None) -> (y, m, d, h, mi, s, wd, yd) in the configured zone, or None while the clock is unset
    tz.offset(unix)     -> seconds east of UTC (DST-aware)
    tz.day_start(unix)  -> Unix time of local midnight for the day containing `unix`
    tz.selection() / tz.select(country, zone) / tz.countries() / tz.zones(code)
Settings: tz.country, tz.zone (Olson name), tz.posix, tz.label.
"""
import json

from . import settings, timeutil as T

DEFAULT = ("AU", "Australia/Sydney", "AEST-10AEDT,M10.1.0,M4.1.0/3", "New South Wales (most areas)")
_parsed = {}
_data = None


# ---- POSIX TZ parsing -----------------------------------------------------------------------------------------
def _name(s, i):
    if s[i] == "<":
        j = s.index(">", i)
        return s[i + 1:j], j + 1
    j = i
    while j < len(s) and s[j].isalpha():
        j += 1
    return s[i:j], j


def _hms(s, i):
    """[+-]hh[:mm[:ss]] -> (seconds, next index)"""
    sign = 1
    if i < len(s) and s[i] in "+-":
        sign = -1 if s[i] == "-" else 1
        i += 1
    j = i
    while j < len(s) and (s[j].isdigit() or s[j] == ":"):
        j += 1
    parts = [int(p) for p in s[i:j].split(":")]
    while len(parts) < 3:
        parts.append(0)
    return sign * (parts[0] * 3600 + parts[1] * 60 + parts[2]), j


def _rule(s, i):
    """Mm.w.d[/time] -> ((m, w, d, secs), next index)"""
    assert s[i] == "M"
    j = i + 1
    k = j
    while k < len(s) and s[k] not in ",/":
        k += 1
    m, w, d = (int(x) for x in s[j:k].split("."))
    secs = 7200
    if k < len(s) and s[k] == "/":
        secs, k = _hms(s, k + 1)
    return (m, w, d, secs), k


def parse(posix):
    """-> (std_offset_s_east, dst_offset_s_east or None, start_rule, end_rule, std_name, dst_name)"""
    p = _parsed.get(posix)
    if p:
        return p
    s = posix
    std, i = _name(s, 0)
    off, i = _hms(s, i)
    std_off = -off
    dst = start = end = None
    dst_name = ""
    if i < len(s) and s[i] != ",":
        dst_name, i = _name(s, i)
        dst = std_off + 3600
        if i < len(s) and s[i] != ",":
            v, i = _hms(s, i)
            dst = -v
    if i < len(s) and s[i] == ",":
        start, i = _rule(s, i + 1)
        end, i = _rule(s, i + 1) if s[i] == "," else (None, i)
        if s[i:i + 1] == ",":
            end, i = _rule(s, i + 1)
    if dst is not None and start is None:          # no rule given: US rules
        start, end = (3, 2, 0, 7200), (11, 1, 0, 7200)
    p = (std_off, dst, start, end, std, dst_name)
    if len(_parsed) > 8:
        _parsed.clear()
    _parsed[posix] = p
    return p


def _rule_local_secs(y, rule):
    """Seconds since 1970-01-01T00:00 of the rule's local wall-clock instant in year y."""
    m, w, d, secs = rule
    first = T.days_from_civil(y, m, 1)
    wd = (first + 3) % 7                     # Mon=0
    want = (d + 6) % 7                       # POSIX: Sunday=0 -> Mon=0 indexing
    day = 1 + (want - wd) % 7 + 7 * (w - 1)
    if day > T.days_in_month(y, m):
        day -= 7
    return T.days_from_civil(y, m, day) * 86400 + secs


def offset_for(posix, unix):
    std_off, dst_off, start, end, _sn, _dn = parse(posix)
    if dst_off is None:
        return std_off
    y = T.civil(unix + std_off)[0]
    s = _rule_local_secs(y, start) - std_off          # start is in standard time
    e = _rule_local_secs(y, end) - dst_off            # end is in daylight time
    inside = (s <= unix < e) if s < e else (unix >= s or unix < e)
    return dst_off if inside else std_off


# ---- selection ------------------------------------------------------------------------------------------------
def selection():
    return (settings.get("tz.country", DEFAULT[0]), settings.get("tz.zone", DEFAULT[1]),
            settings.get("tz.posix", DEFAULT[2]), settings.get("tz.label", DEFAULT[3]))


def select(country, zone, posix, label):
    settings.set("tz.country", country)
    settings.set("tz.zone", zone)
    settings.set("tz.posix", posix)
    settings.set("tz.label", label)


def offset(unix=None):
    if unix is None:
        unix = T.unix_now()
    return offset_for(selection()[2], unix)


def local(unix=None):
    if unix is None:
        if not T.clock_valid():
            return None
        unix = T.unix_now()
    return T.civil(unix + offset(unix))


def day_start(unix=None):
    """Unix time of local midnight of the day containing `unix` (default now)."""
    if unix is None:
        unix = T.unix_now()
    off = offset(unix)
    y, m, d = T.civil(unix + off)[:3]
    mid = T.to_unix(y, m, d)
    return mid - offset(mid - off)                 # re-evaluate the offset at that midnight (DST change days)


def abbrev(unix=None):
    posix = selection()[2]
    std_off, dst_off, _s, _e, sn, dn = parse(posix)
    return dn if dst_off is not None and offset_for(posix, unix or T.unix_now()) == dst_off else sn


# ---- tzdata.json (country/zone picker) ------------------------------------------------------------------------
def _load():
    global _data
    if _data is None:
        with open("www/tzdata.json") as f:
            _data = json.load(f)
    return _data


def free():
    global _data, _countries
    _data = _countries = None


_countries = None


def countries():
    """[(code, name)] sorted by name (cached)"""
    global _countries
    if _countries is None:
        d = _load()
        _countries = sorted(((k, v["name"]) for k, v in d.items()), key=lambda t: t[1])
    return _countries


def zones(code):
    """[(olson, posix, label)] for a country"""
    return [(z["z"], z["p"], z["l"]) for z in _load()[code]["zones"]]


def local_to_unix(local_secs):
    """Unix time for a wall-clock reading (seconds since 1970 as if it were UTC) in the configured zone."""
    posix = selection()[2]
    guess = local_secs - parse(posix)[0]
    return local_secs - offset_for(posix, guess - offset_for(posix, guess) + parse(posix)[0])
