# Third-party components

This project's own code is MIT licensed (see `LICENSE`). It builds on, and redistributes parts of, the following. Each keeps
its own licence.

| Component | Used for | Licence |
|---|---|---|
| [MicroPython](https://github.com/micropython/micropython) v1.29.0 | interpreter / firmware base (fetched by `setup.sh`, plus `patches/micropython-esp32.patch`) | MIT |
| [lv_binding_micropython](https://github.com/lvgl/lv_binding_micropython) | LVGL bindings for MicroPython (fetched by `setup.sh`, plus `patches/lv_binding-gen_mpy.patch`) | MIT |
| [LVGL](https://github.com/lvgl/lvgl) 9.3 | graphics library, includes the Montserrat font (SIL OFL 1.1) | MIT |
| [pycparser](https://github.com/eliben/pycparser) | binding generator | BSD-3-Clause |
| [ESP-IDF](https://github.com/espressif/esp-idf) 5.5.4 | SDK / drivers (not redistributed; installed by you) | Apache-2.0 |
| [Chart.js](https://www.chartjs.org/) 4.4.1 (`py/www/chart.min.js.gz`) | history chart on the web page | MIT |
| [Material Design Icons](https://pictogrammers.com/library/mdi/) (`fonts/lv_font_mdi_24.c`, `fonts/lv_font_load_split_16.c`: subsets) | on-screen icons | Apache-2.0 |
| [Montserrat](https://github.com/JulietaUla/Montserrat) (digit subset in `fonts/lv_font_load_split_16.c`) | text | SIL OFL 1.1 |
| IANA time zone database (`py/www/tzdata.json`, POSIX TZ strings per zone) | country / region picker | public domain |

The web page and HTTP API follow the earlier C firmware, [sigen-dashboard](https://github.com/mplinuxgeek/sigen-dashboard)
(MIT, same author).

"Sigenergy" and "SigenStor" are trademarks of their owners. This project is an independent, unofficial monitor and is not
affiliated with, endorsed by, or supported by Sigenergy. "Waveshare" is likewise a trademark of its owner.
