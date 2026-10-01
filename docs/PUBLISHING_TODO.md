# Publishing checklist

Work through the phases in order. `[x]` = done, `[ ]` = open, `[?]` = needs a decision from the owner.

## Phase 1 - Reproducible build (blocker)
A fresh clone must be able to produce the firmware.
- [x] Identify and verify the upstream pins (MicroPython v1.29.0 `0fd6c57`; lv_binding_micropython `0a86adf`, LVGL `c033a98`,
      pycparser `3cf6bf5`); both patches apply cleanly to them.
- [x] `versions.env` holds the pins; `setup.sh` clones them, applies `patches/` and fetches the ESP32 port submodules.
- [x] `build.sh` uses `$IDF_PATH` (or `~/esp/esp-idf-*`), fails with a clear message, and runs `setup.sh` if the trees are missing.
- [x] Leftover fonts: the three extra ones lived only in the git-ignored local tree; a fresh `setup.sh` never creates them.
- [x] Clean the patch headers (P4-only camera notes) and document what each patch does.
- [x] Prove it: fresh clone -> `setup.sh` -> `build.sh` succeeded (firmware 2,687,200 bytes vs 2,687,216 local; the 16 bytes are build paths).

## Phase 2 - Scripts free of personal defaults
- [x] `scripts_ota.sh`, `shot.sh`, `bench.sh`, `py/deploy.sh`: take `PANEL_HOST`, `PANEL_TOKEN`, `PORT` from the environment
      or arguments, print usage, no `/tmp/sd_token` or `192.168.1.x` defaults.
- [x] A shared `scripts/common.sh` for host/token/port handling.
- [x] Flash helper (`flash.sh`) so the README does not hard-code `ttyACM1`.

## Phase 3 - Licences and attribution
- [x] `LICENSE` (MIT) for this project's own code.
- [x] `THIRD_PARTY.md`: MicroPython, lv_binding_micropython, LVGL, Chart.js, Material Design Icons, tz data, Montserrat.
- [x] README disclaimer (in THIRD_PARTY.md; README gets it in phase 4): unofficial, not affiliated with Sigenergy; trademarks belong to their owners.
- [x] Licence of the inherited web page / API: the original `sigen-dashboard` is MIT, same author (Martin Pascoe), so no issue.
- [x] Author identity: the original sigen-dashboard already publishes "Martin Pascoe <bircoe@gmail.com>"; added `.mailmap` so earlier "martin" commits map to it (history not rewritten; GitHub ignores .mailmap, so run `git rebase --root --exec` or filter-repo before publishing if the display name matters).

## Phase 4 - README and docs
- [x] Rewrite README: what it is, hardware list, screenshots, quick start (setup, build, flash, first boot), OTA, layout.
- [x] Remove stale claims (RAM figures, "backlight not exercised"), and `../sibling` links.
- [x] Screenshots in `docs/img/` (dashboard, graph, monthly; Info/Settings/WiFi omitted because they show the serial, MAC and OTA key).
- [x] `docs/architecture.md`: boot flow, rendering modes, storage, OTA.
- [x] `docs/http-api.md`: add `/api/tuning` and `/api/bench/render`.
- [x] Security notes (open setup AP, plain HTTP, WiFi password stored in clear, token model).

## Phase 5 - Code tidy
- [x] Remove unused imports and other `pyflakes` findings (only the Viper `ptr8/ptr16/ptr32` annotations remain: false positives).
- [x] Remove the old `DEBUG` prints in `board.py`.
- [x] Real version string (`py/core/version.py`, 0.2.0) reported by `/api/version`.
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
