# Changelog

## Unreleased

## 0.2.3 (2026-10-04)
* Dashboard: new top bar (clock and date, status icons with tap-for-details, update dot, how old the last reading is, a one-sentence summary) and the four cards tightened to fit below it, in landscape and portrait. Data older than ~100 s dims the cards.
* Tap the clock for a brightness dialog (pinned until Auto or the next schedule change).
* Graph: day totals under the title; tap the chart to read the values at that time.
* Monthly: tap a month for its totals and the change on the same month last year.
* Info: last reading and link state, WiFi signal, last reset reason; update dialog shows the release notes and has a *Later* button.
* Display options: 12/24-hour clock, date format, power digits, high-contrast text.
* Web: Display Format card and a "Save image" button for the day's charts.
* API: display fields in `/api/settings`; diagnostics `/api/bench/tap`.

## 0.2.2 (2026-10-04)
* Info screen: uptime now counts days ("2d 4h"), "Last sync" and the update status say how long ago they were ("Up to date (checked 3m ago)").

## 0.2.1 (2026-10-04)
* Info screen shows the panel's IP address and network name.
* Web interface rework: per-day chart loading (0.3 s instead of 13 s), Updates tab (GitHub check/install, app upload), WiFi scan/join, Modbus connection test, backlight curve editor, Panel View, token lock indicator, accessibility.
* `scripts/release.sh` cuts releases the same way every time.
* Boot splash (logo, progress bar, status line) shown as soon as the display is up; it stays until WiFi is connected and the web server is listening.
* Update the Python app from GitHub Releases: Info > Check Updates / Install, daily notify-only check, `/api/update*`.
* `build.sh` retries when the LVGL binding link fails on a fresh configure.

## 0.2.0
First public version of the MicroPython port.
* Full dashboard, graph, monthly, info, settings and WiFi screens; landscape and portrait.
* Modbus polling, 31-day history ring, monthly/billing totals, SNTP and time zones, WiFi provisioning.
* HTTP API and web page compatible with the C firmware; OTA for firmware and for the Python app.
* Rendering: SRAM draw strips, 32 KB instruction cache, single frame buffer, animated page slides (landscape).
* Settings page polish, faster Graph and Settings navigation, no UI stalls from backfill or OTA clean-up.
