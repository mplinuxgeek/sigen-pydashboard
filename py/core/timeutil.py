"""Calendar maths on Unix-epoch seconds, independent of the MicroPython port's epoch (ESP32 counts from 2000)."""
import time

_EPOCH_SHIFT = 946684800 if time.gmtime(0)[0] == 2000 else 0      # seconds between 1970 and the port's epoch


def unix_now():
    return time.time() + _EPOCH_SHIFT


def set_clock(unix):
    """Set the RTC from Unix seconds (UTC)."""
    import machine
    t = civil(unix)
    machine.RTC().datetime((t[0], t[1], t[2], t[6], t[3], t[4], t[5], 0))


def clock_valid():
    return unix_now() > 1704067200          # after 2024-01-01: NTP has run at some point


def days_from_civil(y, m, d):
    """Days since 1970-01-01 for a proleptic Gregorian date (Howard Hinnant's algorithm)."""
    y -= m <= 2
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def civil_from_days(z):
    z += 719468
    era = (z if z >= 0 else z - 146096) // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + (3 if mp < 10 else -9)
    return y + (m <= 2), m, d


def civil(unix):
    """(year, month, day, hour, minute, second, weekday Mon=0, yearday) in UTC."""
    days, rem = divmod(unix, 86400)
    y, m, d = civil_from_days(days)
    wd = (days + 3) % 7                      # 1970-01-01 was a Thursday (Mon=0 -> 3)
    yd = days - days_from_civil(y, 1, 1) + 1
    return y, m, d, rem // 3600, rem % 3600 // 60, rem % 60, wd, yd


def to_unix(y, m, d, h=0, mi=0, s=0):
    return days_from_civil(y, m, d) * 86400 + h * 3600 + mi * 60 + s


def days_in_month(y, m):
    return (31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)[m - 1]
