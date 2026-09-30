"""Timezone support for MicroPython (no tz database): fixed UTC offset + a DST rule per zone.

The RTC holds UTC (set by NTP). now() returns the local time tuple for the configured zone.
Settings: region.country (ISO code) and region.zone (city name), default Australia/Adelaide.
"""
import time

from . import settings

# rule: None = no DST, else one of AU, NZ, US, EU (see _dst_window)
# COUNTRIES: code -> (display name, [(city, standard offset minutes, rule, abbrev std, abbrev dst)])
COUNTRIES = {
    "AU": ("Australia", [
        ("Adelaide", 570, "AU", "ACST", "ACDT"), ("Sydney", 600, "AU", "AEST", "AEDT"),
        ("Melbourne", 600, "AU", "AEST", "AEDT"), ("Canberra", 600, "AU", "AEST", "AEDT"),
        ("Hobart", 600, "AU", "AEST", "AEDT"), ("Brisbane", 600, None, "AEST", ""),
        ("Darwin", 570, None, "ACST", ""), ("Perth", 480, None, "AWST", ""),
        ("Broken Hill", 570, "AU", "ACST", "ACDT")]),
    "NZ": ("New Zealand", [("Auckland", 720, "NZ", "NZST", "NZDT")]),
    "US": ("United States", [
        ("New York", -300, "US", "EST", "EDT"), ("Chicago", -360, "US", "CST", "CDT"),
        ("Denver", -420, "US", "MST", "MDT"), ("Phoenix", -420, None, "MST", ""),
        ("Los Angeles", -480, "US", "PST", "PDT"), ("Anchorage", -540, "US", "AKST", "AKDT"),
        ("Honolulu", -600, None, "HST", "")]),
    "CA": ("Canada", [
        ("Toronto", -300, "US", "EST", "EDT"), ("Winnipeg", -360, "US", "CST", "CDT"),
        ("Edmonton", -420, "US", "MST", "MDT"), ("Vancouver", -480, "US", "PST", "PDT")]),
    "GB": ("United Kingdom", [("London", 0, "EU", "GMT", "BST")]),
    "IE": ("Ireland", [("Dublin", 0, "EU", "GMT", "IST")]),
    "DE": ("Germany", [("Berlin", 60, "EU", "CET", "CEST")]),
    "FR": ("France", [("Paris", 60, "EU", "CET", "CEST")]),
    "ES": ("Spain", [("Madrid", 60, "EU", "CET", "CEST")]),
    "IT": ("Italy", [("Rome", 60, "EU", "CET", "CEST")]),
    "NL": ("Netherlands", [("Amsterdam", 60, "EU", "CET", "CEST")]),
    "JP": ("Japan", [("Tokyo", 540, None, "JST", "")]),
    "SG": ("Singapore", [("Singapore", 480, None, "SGT", "")]),
    "IN": ("India", [("Kolkata", 330, None, "IST", "")]),
    "ZA": ("South Africa", [("Johannesburg", 120, None, "SAST", "")]),
}
DEFAULT_COUNTRY = "AU"
DEFAULT_ZONE = "Adelaide"


def country_codes():
    return sorted(COUNTRIES, key=lambda c: COUNTRIES[c][0])


def get_region():
    return settings.get("region.country", DEFAULT_COUNTRY), settings.get("region.zone", DEFAULT_ZONE)


def set_region(country, zone):
    settings.set("region.country", country)
    settings.set("region.zone", zone)


def _zone(country, zone):
    entry = COUNTRIES.get(country)
    if entry:
        for z in entry[1]:
            if z[0] == zone:
                return z
        return entry[1][0]
    z = COUNTRIES[DEFAULT_COUNTRY][1][0]
    return z


# ---- DST rules -------------------------------------------------------------------------------
def _weekday(y, m, d):
    return time.gmtime(time.mktime((y, m, d, 0, 0, 0, 0, 0)))[6]      # Monday=0 ... Sunday=6


def _nth_sunday(y, m, n):
    """n-th Sunday of the month (n=1..4), or the last one if n == -1."""
    if n > 0:
        first = 1 + (6 - _weekday(y, m, 1)) % 7
        return first + 7 * (n - 1)
    dim = (31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)[m - 1]
    return dim - (_weekday(y, m, dim) - 6) % 7


def _epoch(y, m, d, h):
    return time.mktime((y, m, d, h, 0, 0, 0, 0))


def _dst_active(utc, std_min, rule, y):
    """True if DST is in effect at UTC time `utc` for local-year y."""
    off = std_min * 60
    if rule == "AU":     # 02:00 standard on first Sunday Oct -> 03:00 daylight (02:00 std) first Sunday Apr
        start, end = _epoch(y, 10, _nth_sunday(y, 10, 1), 2) - off, _epoch(y, 4, _nth_sunday(y, 4, 1), 2) - off
        return utc >= start or utc < end
    if rule == "NZ":     # last Sunday Sep 02:00 std -> first Sunday Apr 02:00 std
        start, end = _epoch(y, 9, _nth_sunday(y, 9, -1), 2) - off, _epoch(y, 4, _nth_sunday(y, 4, 1), 2) - off
        return utc >= start or utc < end
    if rule == "US":     # second Sunday Mar 02:00 std -> first Sunday Nov 01:00 std
        start, end = _epoch(y, 3, _nth_sunday(y, 3, 2), 2) - off, _epoch(y, 11, _nth_sunday(y, 11, 1), 1) - off
        return start <= utc < end
    if rule == "EU":     # last Sunday Mar 01:00 UTC -> last Sunday Oct 01:00 UTC
        start, end = _epoch(y, 3, _nth_sunday(y, 3, -1), 1), _epoch(y, 10, _nth_sunday(y, 10, -1), 1)
        return start <= utc < end
    return False


def offset_info(utc=None):
    """(offset seconds, abbreviation, is_dst) for the configured zone at `utc` (default now)."""
    if utc is None:
        utc = time.time()
    country, zone = get_region()
    _city, std, rule, a_std, a_dst = _zone(country, zone)
    y = time.gmtime(utc + std * 60)[0]
    dst = bool(rule) and _dst_active(utc, std, rule, y)
    return (std + (60 if dst else 0)) * 60, (a_dst if dst else a_std), dst


def utc_label(offset_s):
    m = offset_s // 60
    sign = "+" if m >= 0 else "-"
    m = abs(m)
    return "UTC%s%d" % (sign, m // 60) + (":%02d" % (m % 60) if m % 60 else "")


def now():
    """Local time tuple (like time.localtime) or None while the clock is not set."""
    utc = time.time()
    if time.gmtime(utc)[0] < 2024:
        return None
    off, _abbr, _dst = offset_info(utc)
    return time.gmtime(utc + off)
