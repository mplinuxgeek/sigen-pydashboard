# HTTP API

Everything the device exposes lives on the same server (port 80; asyncio HTTP server in `py/core/http.py`) and answers JSON, with CORS and `Cache-Control: no-store` on every route.

`GET /api` describes the device to whoever asked. Open it in a browser and you get a readable page — every route, which ones need the token, a copy-pasteable curl line for each gated one, and clickable links for the open GETs. Hit it with curl and the same URL returns JSON. Content negotiation picks by `Accept`, and `?format=html` / `?format=json` overrides it. Both renderings come from one table in `py/core/api.py`, so they can't drift apart.

| Method | Path | Auth | Purpose |
| :--- | :--- | :---: | :--- |
| GET | `/api` | — | Route index |
| GET | `/api/health` | — | Uptime, reset reason, version, heap, UI-lock holder |
| GET | `/api/system` | — | Full snapshot: firmware, boot, network, inverter, memory, orientation, chip |
| GET | `/api/version` | — | Running and inactive slot versions |
| GET | `/api/ota` | — | Running build info (what `scripts/ota.sh` checks) |
| POST | `/api/ota` | ✓ | Upload a MicroPython firmware `.bin` into the inactive OTA slot, then reboot into it (rolls back unless the new image stays up 10 s) |
| POST | `/api/ota/py` | ✓ | Upload the Python application (a `.tar` of `py/`), applied with a backup; `boot.py` rolls back after 3 failed boots |
| GET | `/api/auth` | ✓ | 200 when the admin token is valid (used by the web page's lock indicator) |
| GET | `/api/wifi` | — | WiFi mode, SSID, IP, signal, MAC |
| GET | `/api/wifi/scan` | ✓ | Scan for networks (a few seconds): `[{ssid, rssi, secure}]` |
| POST | `/api/wifi/connect` | ✓ | `{ssid, password}`: save and join; the panel's address may change |
| POST | `/api/modbus/test` | ✓ | `{ip, port}`: try a Modbus TCP connection and read the inverter model and serial |
| GET | `/api/tuning` | — | Current rendering knobs |
| GET | `/api/update` | — | Update status: running version, latest GitHub release, `available`, download progress, last error |
| POST | `/api/update/check` | ✓ | Ask GitHub for the latest release now |
| POST | `/api/update/install` | ✓ | Download, verify and install the release found by the last check, then reboot |
| POST | `/api/update/config` | ✓ | `{"repo": "owner/name"}` and/or `{"auto": true\|false}` (daily check) |
| POST | `/api/tuning` | ✓ | Rendering knobs `ui.partial`, `ui.rows`, `ui.single`, `ui.animate` (JSON body, `null` = default); applied on restart. See `docs/architecture.md` |
| POST | `/api/bench/render` | ✓ | Diagnostics: force and time three full-page redraws of the current page (used by `scripts/bench.sh`) |
| POST | `/api/history/clear` | ✓ | Clear the stored history |
| GET | `/api/monthly` | — | Monthly totals as JSON: `history`, `current`, `current_billing` |
| POST | `/api/factory-reset` | ✓ | Erase WiFi, Modbus, history, totals and settings, then restart |
| POST | `/api/ota-token` | ✓ | Rotate the admin token |
| POST | `/api/reset` | ✓ | Reboot |
| GET | `/api/logs?since=<seq>` | ✓ | Log ring from a cursor |
| POST | `/api/coredump/erase` | ✓ | Clear the stored panic |
| GET | `/api/history` | — | History as JSON; `?from=<unix>&to=<unix>` returns just that range (a day is ~290 records, under a second; the whole 31 days takes ~13 s) |
| GET | `/api/history.csv` | — | History as CSV |
| POST | `/api/history/import` | ✓ | **Replace** all stored history from CSV |
| GET | `/api/monthly.csv` | — | Completed months' totals (Solar/Grid Import/Grid Export/Load) as CSV |
| POST | `/api/monthly/import` | ✓ | **Replace** all completed monthly totals from CSV (the in-progress month is untouched) |
| POST | `/api/monthly/days/import` | ✓ | Overwrite the Month-to-Date day-ring with exact per-day totals from CSV (`date,solar_kwh,grid_import_kwh,grid_export_kwh,load_kwh`) — wins over any existing estimate or commit for that day |
| GET | `/api/screenshot` | — | PNG of the live screen |
| POST | `/api/swipe?dir=left\|right\|none` | — | Navigate the UI as a swipe would (`none` holds the page, resetting the idle timer); answers with the view now showing |
| GET | `/api/view` | — | Which page the UI is showing, without moving it |
| GET | `/api/backlight` | — | Backlight status: level, source, GPIO, curve, next transition |
| POST | `/api/backlight/set?percent=0-100` | ✓ | Manual brightness override (expires at the next curve transition) |
| POST | `/api/backlight/config` | ✓ | Master gate, GPIO pin, curve preset |
| POST | `/api/backlight/curve` | ✓ | Custom dimming curve, up to 8 `["HH:MM", percent]` points |
| GET | `/api/metrics` | — | Live battery/PV/grid/load readings, same values the dashboard shows |
| GET | `/api/settings` | — | Modbus/sizing/blanking/timezone/orientation snapshot (no OTA PIN — write-only) |
| POST | `/api/settings` | ✓ | Update any subset of ip+port, inverter_kw, solar_kw, ota_pin, blank_enabled, blank_timeout_s, country_code+zone |
| POST | `/api/orientation` | ✓ | Set display orientation and restart to apply |
| POST | `/api/reset-wifi-modbus` | ✓ | **Forgets** saved WiFi + Modbus config, then restarts |
| GET | `/tzdata.json` | — | Raw timezone table backing the Settings tab's Country/Region pickers |
| GET | `/`, `/index.html` | — | Device landing page: Metrics + History + History Import/Export + Info + Settings + Firmware tabs |
| GET | `/history-chart.html` | — | Interactive Chart.js graph of stored history |
| GET | `/chart.min.js` | — | Chart.js bundle used by `/history-chart.html` |

Backlight PWM dimming needs a wire jumped from a backlight pad to a spare GPIO — it doesn't exist on an unmodified board, so it defaults off (`enabled:false`) and blanking uses the stock on/off switch until the jumper is fitted and `POST /api/backlight/config {"enabled":true}` is sent. A `gpio` change is stored but only takes effect after a reboot, since rebinding the PWM peripheral live is fiddly and re-jumpering is rare; `preset` (`off`/`gentle`/`aggressive`/`custom`) and `enabled` apply immediately. `POST /api/backlight/curve` installs a custom curve and switches `preset` to `custom`.

Auth is the `X-OTA-Token` header, compared in constant time, with a per-IP throttle (5 failures in 60s → locked out for 5 minutes, `429`). Read-only telemetry is open: this is a plain-HTTP LAN device with no cert infrastructure, so the token guards against accident and casual meddling, not against someone who can already read the wire. Anything that writes, erases, reboots, or reveals a credential is gated.

Errors are always `{"error":"..."}` with a real status code. `/api/health` is deliberately answerable while the UI is wedged — it takes no locks — and reports which task is holding the LVGL mutex if one is.

See [Diagnostics](diagnostics.md) for the log-tailing/health-check endpoints in more depth, and [Deployment & OTA](deployment.md) for the OTA-specific ones.


## Differences from the original ESP-IDF firmware

* `/api/coredump/erase` is a no-op (MicroPython has no core dump partition); `/api/health`'s `lvgl_lock_*` fields are always `0`/`null` (no LVGL lock: one cooperative event loop).
* Bad token → `403` (lockout → `429`), same as before. `/api/health` and `/api/system` additionally report `py_free` / `python_free` (MicroPython heap).
* Long responses (`/api/history`, `/api/history.csv`) are streamed; expect ~20 s for a full 31-day history.
