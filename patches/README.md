# Patches

Applied automatically by `../setup.sh` to the pinned upstream sources in `../versions.env`.

* `micropython-esp32.patch` (MicroPython v1.29.0)
  * `esp32_common.cmake`: adds the IDF components the RGB LCD module needs (`esp_lcd`, LEDC, GPIO, I2C, SPI drivers).
  * `dependencies.lock.esp32s3`: records ESP-IDF 5.5.4 (the version the lock file is generated against).
  * `main.c`: a soft reset (Ctrl-D, `machine.soft_reset`) while LVGL is running restarts the chip instead, because LVGL keeps
    state in C statics that cannot be re-initialised cleanly.
* `lv_binding-gen_mpy.patch` (lv_binding_micropython, `gen/gen_mpy.py`)
  * Python callbacks that raise no longer unwind through LVGL's C code (that froze the UI for good); the exception is
    printed and `lv.set_error_hook(fn)` is called instead.
  * Uses the MicroPython 1.29 `mp_obj_int_to_bytes` signature.
