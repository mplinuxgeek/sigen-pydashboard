# Publishing checklist

Work through the phases in order. `[x]` = done, `[ ]` = open, `[?]` = needs a decision from the owner.

## Phase 1 - Reproducible build (blocker)
A fresh clone must be able to produce the firmware.
- [x] Identify and verify the upstream pins (MicroPython v1.29.0 `0fd6c57`; lv_binding_micropython `0a86adf`, LVGL `c033a98`,
      pycparser `3cf6bf5`); both patches apply cleanly to them.
- [ ] `versions.env` holds the pins; `setup.sh` clones them, applies `patches/` and fetches the ESP32 port submodules.
- [ ] `build.sh` uses `$IDF_PATH` (or `~/esp/esp-idf-*`), fails with a clear message, and runs `setup.sh` if the trees are missing.
- [ ] Drop unused leftover fonts; keep only the fonts the project builds from `fonts/`.
- [ ] Clean the patch headers (P4-only camera notes) and document what each patch does.
- [ ] Prove it: fresh clone -> `setup.sh` -> `build.sh` -> identical-size firmware.

## Phase 2 - Scripts free of personal defaults
- [ ] `scripts_ota.sh`, `shot.sh`, `bench.sh`, `py/deploy.sh`: take `PANEL_HOST`, `PANEL_TOKEN`, `PORT` from the environment
      or arguments, print usage, no `/tmp/sd_token` or `192.168.1.x` defaults.
- [ ] A shared `scripts/common.sh` for host/token/port handling.
- [ ] Flash helper (`flash.sh`) so the README does not hard-code `ttyACM1`.

## Phase 3 - Licences and attribution
- [ ] `LICENSE` (MIT) for this project's own code.
- [ ] `THIRD_PARTY.md`: MicroPython, lv_binding_micropython, LVGL, Chart.js, Material Design Icons, tz data, Montserrat.
- [ ] README disclaimer: unofficial, not affiliated with Sigenergy; trademarks belong to their owners.
- [?] Confirm the licence of the web page / API inherited from the original `sigen-dashboard` project.
- [?] Decide whether to rewrite commit author details before publishing.

## Phase 4 - README and docs
- [ ] Rewrite README: what it is, hardware list, screenshots, quick start (setup, build, flash, first boot), OTA, layout.
- [ ] Remove stale claims (RAM figures, "backlight not exercised"), and `../sibling` links.
- [ ] Screenshots in `docs/img/`.
- [ ] `docs/architecture.md`: boot flow, rendering modes, storage, OTA.
- [ ] `docs/http-api.md`: add `/api/tuning` and `/api/bench/render`.
- [ ] Security notes (open setup AP, plain HTTP, WiFi password stored in clear, token model).

## Phase 5 - Code tidy
- [ ] Remove unused imports (`portal.py`, `modbus.py`) and other `pyflakes` findings.
- [ ] Remove the old `DEBUG` prints and dead paths in `board.py`.
- [ ] Real version string (`py/core/version.py`) reported by `/api/version`.
- [ ] Settings key reference (`ui.*`) documented.

## Phase 6 - Tests and CI
- [ ] More host tests: tz, modbus register decoding, history ring, monthly backfill, settings.
- [ ] `.github/workflows/ci.yml`: unit tests + `pyflakes` on every push.
- [ ] Fuller `.gitignore`.
- [ ] `CONTRIBUTING.md` (short) and `CHANGELOG.md`.

## Phase 7 - Release
- [?] Publish prebuilt firmware `.bin` as GitHub release assets? (needs a flashing guide; saves cloning ~500 MB)
- [?] Repository name, description, topics.
- [ ] Final pass: fresh clone, follow the README literally, on a real board.
