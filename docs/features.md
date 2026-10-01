# Features

## Dashboard
Home screen laid out as four quadrants — **Battery, Solar, Load, Grid** — each showing live power, a fill bar, and daily totals. Battery shows SOC%/kWh, charge/discharge status, cell temperature, and a time-to-full/time-to-empty estimate; Solar shows what percentage of current household load it's directly covering; Grid shows import/export direction and on/off-grid status (idle state reads "STANDBY", matching the battery quadrant). Solar, Load, and Grid also show a Month-to-Date total alongside today's, tracking the current **billing cycle** rather than the calendar month — see Billing cycle below.

Navigation across all screens is touch-driven via horizontal swipe tabs: **Dashboard**, **Graph**, **Monthly**, and **System** (which itself holds Info/Settings/WiFi sub-tabs).

All of a poll cycle's Modbus readings are applied to the dashboard atomically — the UI never shows a mix of some quadrants refreshed against the newest reading and others still on the previous cycle's.

## Modbus polling
Polls the SigenStor plant registers on a cycle: battery SOC, battery charge/discharge power, rated capacity, and average cell temperature; PV power; grid power; load power; PV/load daily totals; grid on/off-grid status; and lifetime grid import/export counters (used to derive daily grid import/export, since Sigenergy exposes no dedicated daily grid register — this baseline is only reset by an actual midnight rollover, guarded against being corrupted by the clock still reading the 1970 epoch during early boot before SNTP completes).

## History
A background task samples SOC, battery/PV/grid/load power every 5 minutes (31 days' retention) into a dedicated flash partition. Swiping to the **Graph** tab renders a combined midnight-to-midnight chart displaying battery, solar, load, and grid metrics with 25/50/75% reference lines. Also available as JSON via `GET /api/history` (see [HTTP API](http-api.md)).

## Monthly totals
The same background task rolls up each completed day into a running per-month total (Solar, Grid Import, Grid Export, Load), retained for 36 months. The **Monthly** tab shows Solar/Grid Import/Grid Export as a grouped bar chart, six months at a time with Prev/Next paging; the in-progress month is included and marked as such. Completed months export/import as CSV via `GET /api/monthly.csv` / `POST /api/monthly/import` (the in-progress month isn't part of either).

Two converters bring in other sources' data: `./scripts/sigen_monthly_import.py` (or the device's own web UI's **History Import/Export** tab, no Python needed) for a SigenStor app "Log" export, and `./scripts/ha_import.py monthly` for Home Assistant, pulled directly via HA's REST API and a long-lived access token (no manual CSV export/download needed). Both can push straight to `/api/monthly/import`. `./scripts/ha_import.py daily` does the same for the 5-minute history `/api/history/import` expects, and `./scripts/ha_import.py sync` does both in one HA fetch. Monthly totals additionally fall back to HA's long-term statistics (its own separate, non-purged store) for any month the recorder's short-term history has already rolled off.

### Billing cycle
A separate, second running total tracks a configurable billing cycle instead of the calendar month, for households whose retailer bills on a date other than the 1st. Set via **Billing Cycle Start Day** (1-31) in Settings, on-device or in the web UI's System Sizing card — a day past the end of a shorter month (e.g. 31 in February) clamps to that month's last day. Defaults to 1, which makes the billing cycle coincide with the calendar month. Changing it takes effect immediately (the last up-to-31 days' totals are re-summed against the new boundary), no reboot needed; it does not affect the calendar-month totals used by the Monthly tab/CSV. Unlike that calendar-month total, the billing-cycle figure includes today's own contribution so far, live. Exposed as `current_billing` on `GET /api/monthly`, alongside the existing calendar-month `current`.

Each completed day's contribution to this total is committed in real time from the inverter's own daily-total registers, same as the calendar-month total. If those aren't available for a day — e.g. right after upgrading onto this feature, when nothing's been committed yet — the device automatically reconstructs it from `history_store`'s 5-minute power log instead (an estimate: power integrated over each 5-minute interval, less precise than the inverter's own register but far better than showing 0), for any day that log still covers. This also runs right after any history import (`ha_import.py daily`/CSV), so freshly imported history is reflected immediately rather than only from the next natural day-rollover.

For exact (not estimated) per-day figures — e.g. bringing a second device's day-by-day totals in line with one that's been running continuously — `./scripts/ha_import.py daily-totals` computes exact daily deltas from the same lifetime cumulative energy sensors `ha_import.py monthly` already uses for exact month-level deltas, just bucketed by day, and pushes them to `POST /api/monthly/days/import`. Unlike the 5-minute-log estimate above, these values unconditionally overwrite whatever the device already had recorded for that day (a prior real commit or a prior estimate alike), since there's no way to be more right about a day than the inverter's own register value for it.

## WiFi provisioning
On first boot (or lost credentials), the device opens an AP with a captive portal — a DNS server redirects all queries to itself so the phone/laptop's captive-portal detection pops a setup page automatically. After initial setup, an on-device WiFi manager screen lets you scan, connect, and forget networks without the portal.

A dropped link reconnects on its own, with exponential backoff from 1s to 30s, so a router reboot doesn't leave the device stranded until someone power-cycles it. Deliberate disconnects (Disconnect, Forget, or connecting to a different network) suppress the retry, so "disconnected" stays disconnected.

WiFi credentials are stored unencrypted in `settings.json` on the board's flash filesystem (no flash encryption configured). Anyone with physical UART/JTAG access to the board can read them out. Not remotely reachable, just worth knowing before handing the device to someone else or reusing it on a network you'd rather its previous owner not have lasting access to.

## Display orientation
Landscape (800×480) or portrait (480×800), switchable on-device via **Screen Orientation** in the System tab and persisted in settings — the change takes effect on restart. Every screen has a portrait layout: the dashboard's 2×2 quadrant grid becomes four stacked bands, the graph becomes three mini charts with the legend below, and the Settings form stacks above the on-screen keyboard instead of sitting beside it.

Pixels are rotated by a hand-written flush callback. The vendor BSP's own rotation support is LVGL v8-only dead code on this v9 port, and LVGL's software rotation never reaches an RGB panel driven this way.

## Settings
An on-device screen (accessible via the **Settings** tab) to view/edit the SigenStor's Modbus IP and port, plus the dashboard's sensor-refresh interval (default 15s, persisted). Inputs sit in a narrow left column with a full-size on-screen numeric keypad alongside. Changes save live and reconnect the Modbus client immediately.

## System
Accessible via the **System** tab in the swipe view. Displays network info (IP, SSID, signal RSSI, MAC), firmware version, chip hardware, system uptime, and memory usage (flash, PSRAM, free internal SRAM), along with a button to launch Wi-Fi setup.

## Time sync
SNTP against `pool.ntp.org`. On first sync, any history records taken before time was available are backfilled with correct timestamps.
