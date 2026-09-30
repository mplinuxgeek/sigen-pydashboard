"""App context: event bus, background task runner with restart/backoff, shared services.

    app.log / app.settings        logging, persistent key/value store
    app.on(event, cb) / app.emit(event, *args)   tiny event bus (net.up(iface, ip) / net.down(iface) come from core.wifi)
    app.services[name] = obj      share an object between modules
    app.network                   registry of network links: up(), primary(), addresses(), urls()
    app.spawn(coro_fn)            run a background asyncio task (restarted with backoff if it crashes)
"""
import asyncio
import time

from . import errors, log, settings
from .network import Network


class App:
    def __init__(self):
        self.ui = None
        self.log = log
        self.settings = settings
        self.services = {}
        self.network = Network()      # links register here; consumers ask it (see core/network.py)
        self.features = []     # (name, ok, message) filled by the loader
        self._loading_fid = None      # "category/feature" of the feature currently in setup() (features.py sets this)
        self._handlers = {}
        self._pending = []
        self._running = False

    # ---- events ---------------------------------------------------------------------------
    def on(self, event, cb):
        self._handlers.setdefault(event, []).append(cb)

    def emit(self, event, *args):
        for cb in self._handlers.get(event, ()):
            try:
                cb(*args)
            except Exception as e:
                log.error("event %s handler failed: %r" % (event, e))

    # ---- background tasks -----------------------------------------------------------------
    def spawn(self, coro_fn, restart=True):
        """Run coro_fn() as an asyncio task (now if the loop is running, else at start).
        restart=True: if it crashes it is logged and restarted with backoff (use False for one-shot jobs)."""
        if self._running:
            asyncio.create_task(self._guard(coro_fn, restart))
        else:
            self._pending.append((coro_fn, restart))

    async def _guard(self, coro_fn, restart=True):
        name = getattr(coro_fn, "__name__", "task")
        fails = 0
        while True:
            t0 = time.ticks_ms()
            try:
                await coro_fn()
                return
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if time.ticks_diff(time.ticks_ms(), t0) > 60000:
                    fails = 0                                   # it ran fine for a while: not a crash loop
                fails += 1
                delay = min(60, 2 ** min(fails, 5))
                log.error("task %s crashed: %s%s" % (name, errors.describe(e),
                                                    ("; restarting in %ds" % delay) if restart else ""))
                if not restart:
                    return
                await asyncio.sleep(delay)

    async def start(self):
        """Coroutine passed to board.run(): launches queued tasks."""
        self._running = True
        for fn, restart in self._pending:
            asyncio.create_task(self._guard(fn, restart))
        self._pending = []
