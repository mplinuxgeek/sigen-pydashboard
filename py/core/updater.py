"""Update the Python app from GitHub Releases.

The release workflow attaches `sigen-pydashboard-app.tar` (the py/ tree) to every release. This module asks the GitHub API
for the latest release, compares its tag with core/version.py, and on request downloads the tar over HTTPS (certificate chain
checked against core/certs.py), verifies its SHA-256 (the digest GitHub publishes for the asset), stages it and hands it to
the same apply-with-rollback code as a manual upload (core/ota.py). Nothing is installed without an explicit request; the
daily check only records that an update exists.

Settings: update.repo (default DEFAULT_REPO, any "owner/name"), update.auto (default true: daily check, notify only),
update.api (default https://api.github.com; an http:// URL skips TLS, for mirrors and tests), update.asset (file name).
HTTP: GET /api/update, POST /api/update/check, /api/update/install, /api/update/config (the POSTs need the admin token).
"""
import asyncio
import binascii
import hashlib
import json
import os
import time

from . import http, ota, version

DEFAULT_REPO = "mplinuxgeek/sigen-pydashboard"
DEFAULT_API = "https://api.github.com"
ASSET = "sigen-pydashboard-app.tar"
SUMS = "SHA256SUMS"
CHECK_FIRST_S, CHECK_EVERY_S = 300, 86400
MAX_JSON = 262144

state = {"status": "idle",            # idle | checking | installing
         "checked": None,             # time.ticks_ms() of the last successful check (see snapshot() for "ago")
         "latest": None, "available": False, "notes": "", "size": 0,
         "progress": 0, "error": None, "url": None, "sha256": None, "sums_url": None}


def parse_version(v):
    """'v1.2.3-rc1' -> (1, 2, 3); unparsable parts count as 0."""
    out = []
    for part in str(v).lstrip("vV").split("-")[0].split(".")[:3]:
        try:
            out.append(int(part))
        except ValueError:
            out.append(0)
    while len(out) < 3:
        out.append(0)
    return tuple(out)


def firmware_api():
    try:
        import rgb_lcd
        return rgb_lcd.API
    except (ImportError, AttributeError):
        return 0


def needs_firmware_api(text):
    for line in text.split("\n"):
        if line.startswith("NEEDS_FW_API"):
            try:
                return int(line.split("=")[1].split("#")[0])
            except ValueError:
                return 0
    return 0


# ---- minimal HTTP(S) client -----------------------------------------------------------------------------------
def _ssl_context():
    import ssl
    from . import certs
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.verify_mode = ssl.CERT_REQUIRED
    for pem in certs.ROOTS:
        ctx.load_verify_locations(cadata=pem)
    return ctx


def _split(url):
    scheme, _, rest = url.partition("://")
    netloc, slash, path = rest.partition("/")
    host, port = netloc, 443 if scheme == "https" else 80
    if ":" in netloc:
        host, _, p = netloc.partition(":")
        port = int(p)
    return scheme, host, port, "/" + path, netloc


_step = [""]                         # what the HTTP client was doing, for error messages


class _Body:
    """Response body reader: Content-Length, chunked or until close."""
    def __init__(self, r, headers):
        self.r = r
        self.chunked = "chunked" in headers.get("transfer-encoding", "")
        self.left = int(headers["content-length"]) if "content-length" in headers else None
        self.chunk_left = 0
        self.done = False

    async def read(self, n):
        if self.done:
            return b""
        if self.chunked:
            if self.chunk_left == 0:
                line = await self.r.readline()
                while line in (b"\r\n", b"\n"):
                    line = await self.r.readline()
                size = int(line.split(b";")[0].strip() or b"0", 16)
                if size == 0:
                    self.done = True
                    return b""
                self.chunk_left = size
            data = await self.r.read(min(n, self.chunk_left))
            if not data:
                raise OSError("connection closed")
            self.chunk_left -= len(data)
            return data
        if self.left is not None:
            if self.left <= 0:
                self.done = True
                return b""
            data = await self.r.read(min(n, self.left))
            if not data:
                raise OSError("download truncated")
            self.left -= len(data)
            return data
        data = await self.r.read(n)
        if not data:
            self.done = True
        return data


async def _request(url, accept="*/*", timeout=25):
    """GET url following redirects; returns (status, headers, body, writer). The caller closes the writer."""
    for _ in range(6):
        scheme, host, port, path, netloc = _split(url)
        _step[0] = "tls setup"
        ctx = _ssl_context() if scheme == "https" else None
        _step[0] = "connect to " + host
        r, w = await asyncio.wait_for(asyncio.open_connection(host, port, ssl=ctx), timeout)
        _step[0] = "request to " + host
        w.write(("GET %s HTTP/1.1\r\nHost: %s\r\nUser-Agent: sigen-pydashboard/%s\r\nAccept: %s\r\nConnection: close\r\n\r\n"
                 % (path, netloc, version.VERSION, accept)).encode())
        await asyncio.wait_for(w.drain(), timeout)
        _step[0] = "response from " + host
        status = int((await asyncio.wait_for(r.readline(), timeout)).split(b" ")[1])
        headers = {}
        while True:
            line = await asyncio.wait_for(r.readline(), timeout)
            if line in (b"\r\n", b"\n", b""):
                break
            k, _, v = line.decode().partition(":")
            headers[k.strip().lower()] = v.strip()
        if status in (301, 302, 303, 307, 308) and "location" in headers:
            w.close()
            await w.wait_closed()
            loc = headers["location"]
            url = loc if "://" in loc else "%s://%s%s" % (scheme, netloc, loc)
            continue
        return status, headers, _Body(r, headers), w
    raise OSError("too many redirects")


async def _read_all(body, limit):
    data = b""
    while True:
        chunk = await body.read(2048)
        if not chunk:
            return data
        data += chunk
        if len(data) > limit:
            raise ValueError("response too large")


# ---- check / install -------------------------------------------------------------------------------------------
def _repo(app):
    return app.settings.get("update.repo", DEFAULT_REPO)


async def check(app):
    if state["status"] != "idle":
        return state
    state["status"], state["error"] = "checking", None
    w = None
    try:
        api = app.settings.get("update.api", DEFAULT_API)
        status, _h, body, w = await _request("%s/repos/%s/releases/latest" % (api, _repo(app)), "application/vnd.github+json")
        if status == 404:
            raise ValueError("no release published yet")
        if status != 200:
            raise ValueError("GitHub answered %d" % status)
        d = json.loads(await _read_all(body, MAX_JSON))
        assets = {a["name"]: a for a in d.get("assets", [])}
        want = app.settings.get("update.asset", ASSET)
        if want not in assets:
            raise ValueError("release %s has no %s" % (d.get("tag_name"), want))
        a = assets[want]
        dig = a.get("digest") or ""
        state.update(latest=d["tag_name"].lstrip("vV"), notes=(d.get("body") or "")[:400], size=a.get("size", 0),
                     url=a["browser_download_url"], sha256=dig[7:] if dig.startswith("sha256:") else None,
                     sums_url=assets[SUMS]["browser_download_url"] if SUMS in assets else None, checked=time.ticks_ms())
        state["available"] = parse_version(state["latest"]) > parse_version(version.VERSION)
        app.log.info("update: latest %s, running %s%s" % (state["latest"], version.VERSION,
                                                         " (update available)" if state["available"] else ""))
    except Exception as e:
        state["error"] = _why(e)
        app.log.warn("update: check failed: %s\n%s" % (state["error"], _trace(e)))
    finally:
        if w:
            w.close()
        state["status"] = "idle"
    return state


def _trace(e):
    import io
    import sys
    b = io.StringIO()
    sys.print_exception(e, b)
    return b.getvalue()[-400:]


def _why(e):
    s = str(e)
    if isinstance(e, OSError):
        s = "%s (%s)" % (s or "network error", _step[0])
    return " ".join((s or e.__class__.__name__).split())[:100]


async def _expected_sha(st):
    if st["sha256"]:
        return st["sha256"]
    if not st["sums_url"]:
        return None
    status, _h, body, w = await _request(st["sums_url"])
    try:
        if status != 200:
            return None
        for line in (await _read_all(body, 8192)).decode().split("\n"):
            parts = line.split()
            if len(parts) == 2 and parts[1].lstrip("*") == ASSET:
                return parts[0]
    finally:
        w.close()
    return None


async def install(app):
    """Download, verify and install the release found by check(); reboots on success."""
    st = state
    if st["status"] != "idle" or not st["available"] or not st["url"]:
        return False
    st.update(status="installing", progress=0, error=None)
    app.services["poller"].pause(True)
    w = None
    try:
        expected = await _expected_sha(st)
        if not expected:
            raise ValueError("release has no checksum for the app file")
        status, _h, body, w = await _request(st["url"])
        if status != 200:
            raise ValueError("download answered %d" % status)
        h = hashlib.sha256()
        got = 0

        async def read(n):
            nonlocal got
            chunk = await body.read(n)
            h.update(chunk)
            got += len(chunk)
            if st["size"]:
                st["progress"] = min(99, got * 100 // st["size"])
            return chunk
        files = await ota.stage_tar(read)
        while await read(2048):                          # the tar's trailing padding: needed for the checksum
            pass
        if binascii.hexlify(h.digest()).decode() != expected.lower():
            raise ValueError("checksum mismatch: download rejected")
        with open(ota.STAGE + "/core/version.py") as f:
            need = needs_firmware_api(f.read())
        if need > firmware_api():
            raise ValueError("needs newer firmware (API %d, have %d): update the firmware first" % (need, firmware_api()))
        st["progress"] = 100
        ota.apply_staged(app, files, "GitHub update")
        app.log.info("update: installed %s" % st["latest"])
        return True
    except Exception as e:
        ota._rm_tree(ota.STAGE)
        app.services["poller"].pause(False)
        st["error"] = _why(e)
        app.log.error("update: install failed: %s" % st["error"])
        return False
    finally:
        if w:
            w.close()
        st["status"] = "idle"


async def run(app):
    """Daily check (notify only). The first one waits for WiFi and the clock."""
    await asyncio.sleep(CHECK_FIRST_S)
    while True:
        if app.settings.get("update.auto", True):
            await check(app)
        jitter = int.from_bytes(os.urandom(2), "little") % 3600
        await asyncio.sleep((3600 if state["error"] else CHECK_EVERY_S) + jitter)


def snapshot(app):
    s = dict(state)
    for k in ("url", "sums_url"):
        s.pop(k, None)
    s["checked_ago_s"] = None if s.pop("checked") is None else time.ticks_diff(time.ticks_ms(), state["checked"]) // 1000
    return {"current": version.VERSION, "repo": _repo(app), "auto": bool(app.settings.get("update.auto", True)),
            "firmware_api": firmware_api(), "state": s}


def register(app, server):
    def get(req):
        return snapshot(app)

    async def post_check(req):
        await check(app)
        return snapshot(app)

    def post_install(req):
        if state["status"] != "idle" or not state["available"]:
            return http.err(409, "no update available (run /api/update/check first)")
        asyncio.create_task(install(app))
        return {"ok": True, "started": True}

    def post_config(req):
        d = json.loads(req.body or b"{}")
        repo = d.get("repo")
        if repo is not None:
            if not isinstance(repo, str) or repo.count("/") != 1 or len(repo) > 100:
                return http.err(400, "repo must look like owner/name")
            app.settings.set("update.repo", repo)
            state.update(latest=None, available=False, url=None, sha256=None, sums_url=None, checked=None)
        if "auto" in d:
            app.settings.set("update.auto", bool(d["auto"]))
        return snapshot(app)
    server.route("GET", "/api/update", get)
    server.route("POST", "/api/update/check", post_check, auth=True)
    server.route("POST", "/api/update/install", post_install, auth=True)
    server.route("POST", "/api/update/config", post_config, auth=True)
