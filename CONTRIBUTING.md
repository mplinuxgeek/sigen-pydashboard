# Contributing

Issues and pull requests are welcome.

* Host tests (no hardware): `cd py && python3 -m unittest discover tests`; `python3 -m pyflakes py` should stay clean
  (apart from the Viper `ptr8/ptr16/ptr32` annotations). CI runs both.
* UI and rendering changes need a real board: check them with `./scripts/shot.sh`, and `./scripts/bench.sh` for redraw timing. Please say
  which board and orientation you tested.
* Keep the loop responsive: nothing in a handler should block for more than a few ms (the UI loop logs stalls over 300 ms at
  `/api/logs`). Yield with `await asyncio.sleep_ms(0)` in long loops.
* Changes to `patches/` must still apply to the commits pinned in `versions.env`.
* Match the surrounding code style; comments explain why, not what.
