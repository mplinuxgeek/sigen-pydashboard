# Settings keys

Stored as JSON in `/settings.json` on the board's FAT filesystem (`py/core/settings.py`). Most are edited from the Settings
page or the HTTP API; the `ui.*` knobs only via `POST /api/tuning` (applied on restart).

| Key | Default | Meaning |
|---|---|---|
| `modbus.ip`, `modbus.port` | none, 502 | Inverter address (Settings page / `POST /api/settings`) |
| `modbus.skipped` | false | User chose to skip the first-run inverter prompt |
| `sizing.inverter_kw`, `sizing.solar_kw` | 25, 25 | Scale of the dashboard bars and graph |
| `billing.mode` / `.day` / `.cycle_len` / `.anchor` | 0 / 1 / 28 / 20260101 | Calendar-month or fixed N-day billing cycle |
| `tz.country` / `.zone` / `.posix` / `.label` | AU / Australia/Sydney | Time zone (POSIX TZ string drives the clock) |
| `orientation` | landscape | `landscape` or `portrait` (restart) |
| `blank.enabled`, `blank.timeout_s` | true, 120 | Screen blanking after inactivity |
| `backlight.preset`, `backlight.points` | off | PWM night-dimming curve (needs the backlight jumper) |
| `wifi.ssid`, `wifi.pass` | none | Saved network (plain text on flash) |
| `ota.token` | generated | Admin token for write endpoints (`X-OTA-Token`) |
| `system.watchdog_s` | 300 | Restart if the UI loop stalls this long (0 = off). Disabled while a `/dev_mode` file exists |
| `last_reboot` | | Reason recorded before the last deliberate reboot |
| `ui.clock24` | true | 24-hour clock in the dashboard's top bar (false = 12-hour with AM/PM) |
| `ui.date_fmt` | dmy | `dmy` "Sat 4 Oct", `mdy` "Sat Oct 4", `iso` "2026-10-04" |
| `ui.kw_dec` | 2 | Digits after the point on the big power values (1 or 2) |
| `ui.contrast` | false | Lighter secondary text (restart to apply) |
| `update.dismissed` | | Version whose "update available" dot was dismissed with *Later* |
| `update.repo` | mplinuxgeek/sigen-pydashboard | GitHub repository whose releases the panel updates from |
| `update.auto` | true | Daily check for a newer release (notify only; never installs by itself) |
| `update.asset` | sigen-pydashboard-app.tar | Release asset to download (for forks that name it differently); set via `POST /api/tuning` |
| `update.api` | https://api.github.com | API base URL. An `http://` value skips TLS (mirrors and tests); set via `POST /api/tuning` |
| `ui.partial` | true | Draw into an internal-SRAM strip buffer instead of directly into PSRAM |
| `ui.rows` | 40 (portrait 64) | Rows in that strip buffer (more = a little faster, uses more SRAM) |
| `ui.single` | true | Single frame buffer, no vsync waits (landscape only). false = tear-free double buffer |
| `ui.animate` | true | Animated page slides (landscape + `ui.single`) |
