# Changelog

## 0.2.0
First public version of the MicroPython port.
* Full dashboard, graph, monthly, info, settings and WiFi screens; landscape and portrait.
* Modbus polling, 31-day history ring, monthly/billing totals, SNTP and time zones, WiFi provisioning.
* HTTP API and web page compatible with the C firmware; OTA for firmware and for the Python app.
* Rendering: SRAM draw strips, 32 KB instruction cache, single frame buffer, animated page slides (landscape).
* Settings page polish, faster Graph and Settings navigation, no UI stalls from backfill or OTA clean-up.
