"""Display preferences and the small pure helpers behind the dashboard's top bar and number formats.

Settings keys: ui.clock24 (true), ui.date_fmt ("dmy" | "mdy" | "iso"), ui.kw_dec (1 or 2), ui.contrast (false).
Everything that needs no hardware is a plain function so it can be tested on the host."""
from . import settings

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
FIT_CHARS = 40                         # characters the summary label shows without being cut off (landscape bar, 16 pt)
NOISE_KW = 0.15                        # flows below this are meter noise, not "importing"
STALE_S = 100                          # a poll cycle is ~35 s: three missed cycles make the data stale


def clock24():
    return bool(settings.get("ui.clock24", True))


def date_fmt():
    v = settings.get("ui.date_fmt", "dmy")
    return v if v in ("dmy", "mdy", "iso") else "dmy"


def kw_decimals():
    return 1 if settings.get("ui.kw_dec", 2) == 1 else 2


def high_contrast():
    return bool(settings.get("ui.contrast", False))


def fmt_clock(h, m, use24=True):
    if use24:
        return "%02d:%02d" % (h, m)
    return "%d:%02d %s" % (h % 12 or 12, m, "AM" if h < 12 else "PM")


def fmt_date(wd, d, mo, y, style="dmy"):
    """wd 0 = Monday, mo 1-12."""
    if style == "iso":
        return "%04d-%02d-%02d" % (y, mo, d)
    if style == "mdy":
        return "%s %s %d" % (DAYS[wd], MONTHS[mo - 1], d)
    return "%s %d %s" % (DAYS[wd], d, MONTHS[mo - 1])


def fmt_kw(v, decimals=2):
    return "%.*f kW" % (decimals, v)


def summary(alive, age_s, soc, batt_kw, pv_kw, load_kw, grid_kw, grid_on, self_pct, dec=1):
    """One sentence for the dashboard bar and its tone: ("ok" | "warn" | "bad" | "idle"). self_pct is today's share of the load
    met without the grid (None = unknown). Keep it short: the bar has room for FIT_CHARS characters."""
    if age_s is None:
        return "Waiting for the inverter...", "idle"
    if not alive or age_s > STALE_S:
        return "No fresh data (last %s): check Settings" % _age(age_s), "warn"
    if grid_on is False:
        return "Off-grid: running on battery and solar", "bad"
    chg = batt_kw > NOISE_KW
    if grid_kw > NOISE_KW:
        main = "Importing %.*f kW" % (dec, grid_kw) + (" + charging battery" if chg else " from the grid")
    elif grid_kw < -NOISE_KW:
        main = "Exporting %.*f kW" % (dec, -grid_kw) + (" + charging battery" if chg else " to the grid")
    elif batt_kw < -NOISE_KW:
        main = "Running on battery"
    elif pv_kw > NOISE_KW:
        main = "Running on solar"
    else:
        main = "Idle"
    if self_pct is not None:                                 # the share of today's load met without the grid, if it fits
        for tail in (" | %d%% self-powered today", " | %d%% self-powered"):
            if len(main) + len(tail % self_pct) <= FIT_CHARS:
                main += tail % self_pct
                break
    return main, "ok"


def _age(s):
    s = int(s)
    return "%ds ago" % s if s < 90 else "%dm ago" % (s // 60)
