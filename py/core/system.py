"""Reboot and factory reset."""
import os
import time

import machine

from . import store


def reboot(app, reason="requested"):
    app.settings.set("last_reboot", reason)
    app.log.info("system: rebooting (%s)" % reason)
    from . import log
    log.persist()
    time.sleep_ms(300)
    machine.reset()


def factory_reset(app):
    app.log.warn("system: factory reset")
    app.services["history"].clear()
    for k in ("m_prog", "m_months", "m_days"):
        store.erase(k)
    try:
        os.remove("/settings.json")
    except OSError:
        pass
    try:
        os.remove("/lastlog.txt")
    except OSError:
        pass
    time.sleep_ms(300)
    machine.reset()
