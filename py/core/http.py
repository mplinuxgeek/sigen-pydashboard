"""Small asyncio HTTP server: route table, JSON helpers, token auth with per-IP throttle, streamed request bodies.

    srv = Server(app)
    srv.route("GET", "/api/x", handler)                  # open
    srv.route("POST", "/api/y", handler, auth=True)      # needs the admin token: X-OTA-Token header (or ?token=)
    srv.route("POST", "/api/z", handler, auth=True, stream=True)   # body not read: use await req.read(n) / req.length
    srv.fallback = handler                                # anything without a route (captive portal redirect)

A handler is a plain function or coroutine taking `req` and returning a dict/list (JSON 200),
(status, content_type, body) or (status, content_type, body, {extra: headers}).  Errors are {"error": "..."}.
"""
import asyncio
import json
import time

PORT = 80
READ_TIMEOUT_S = 8
MAX_BODY = 32768
AUTH_FAILS, AUTH_WINDOW_S, AUTH_LOCK_S = 5, 60, 300

_REASONS = {200: "OK", 204: "No Content", 302: "Found", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
            404: "Not Found", 405: "Method Not Allowed", 409: "Conflict", 413: "Payload Too Large", 429: "Too Many Requests",
            500: "Internal Server Error", 503: "Service Unavailable"}


def unquote(s):
    if "%" not in s and "+" not in s:
        return s
    s = s.replace("+", " ")
    out = bytearray()
    parts = s.split("%")
    out += parts[0].encode()
    for p in parts[1:]:
        try:
            out.append(int(p[:2], 16))
            out += p[2:].encode()
        except ValueError:
            out += b"%" + p.encode()
    return out.decode()


def parse_query(qs):
    q = {}
    for pair in qs.split("&"):
        if pair:
            k, _, v = pair.partition("=")
            q[unquote(k)] = unquote(v)
    return q


class Request:
    def __init__(self, method, path, query, headers, reader, length, peer):
        self.method, self.path, self.query, self.headers = method, path, query, headers
        self.reader, self.length, self.peer = reader, length, peer
        self.body = b""
        self._left = length

    async def read(self, n=4096):
        """Streamed body: up to n bytes (b'' at the end)."""
        n = min(n, self._left)
        if n <= 0:
            return b""
        d = await self.reader.read(n)
        self._left -= len(d)
        return d

    def json(self):
        return json.loads(self.body) if self.body else {}

    def form(self):
        return parse_query(self.body.decode())


def constant_time_eq(a, b):
    if len(a) != len(b):
        return False
    r = 0
    for x, y in zip(a.encode(), b.encode()):
        r |= x ^ y
    return r == 0


class Server:
    def __init__(self, app, port=PORT):
        self.app = app
        self.port = port
        self.routes = {}
        self.fallback = None
        self.requests = 0
        self.server = None
        self._fails = {}          # ip -> [count, first_ms, locked_until_ms]

    def route(self, method, path, handler, auth=False, stream=False):
        self.routes[(method, path)] = (handler, auth, stream)

    def token(self):
        return self.app.settings.get("ota.token", "") or ""

    async def start(self):
        self.server = await asyncio.start_server(self._client, "0.0.0.0", self.port)
        self.app.log.info("http: listening on port %d" % self.port)

    def stop(self):
        if self.server:
            self.server.close()
            self.server = None

    # ---- auth throttle ----------------------------------------------------------------------
    def _locked(self, ip):
        e = self._fails.get(ip)
        return bool(e and e[2] and time.ticks_diff(e[2], time.ticks_ms()) > 0)

    def _note_fail(self, ip):
        now = time.ticks_ms()
        e = self._fails.get(ip)
        if not e or time.ticks_diff(now, e[1]) > AUTH_WINDOW_S * 1000:
            e = self._fails[ip] = [0, now, 0]
        e[0] += 1
        if e[0] >= AUTH_FAILS:
            e[2] = time.ticks_add(now, AUTH_LOCK_S * 1000)
            self.app.log.warn("http: %s locked out for %d s after %d bad tokens" % (ip, AUTH_LOCK_S, e[0]))

    # ---- connection -------------------------------------------------------------------------
    async def _client(self, reader, writer):
        try:
            req = await asyncio.wait_for(self._read_head(reader, writer), READ_TIMEOUT_S)
            if req is None:
                return
            self.requests += 1
            res = await self._dispatch(req)
            await self._send(writer, *res)
        except Exception as e:
            try:
                self.app.log.warn("http: request failed: %r" % (e,))
                await self._send(writer, 500, "application/json", json.dumps({"error": repr(e)}))
            except Exception:
                pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _read_head(self, reader, writer):
        line = await reader.readline()
        if not line:
            return None
        try:
            method, target, _ver = line.decode().strip().split(" ", 2)
        except ValueError:
            return None
        path, _, qs = target.partition("?")
        headers = {}
        while True:
            h = await reader.readline()
            if not h or h in (b"\r\n", b"\n"):
                break
            k, _, v = h.decode().partition(":")
            headers[k.strip().lower()] = v.strip()
        try:
            peer = writer.get_extra_info("peername")[0]
        except Exception:
            peer = "?"
        return Request(method, path, parse_query(qs), headers, reader, int(headers.get("content-length", "0") or 0), peer)

    async def _dispatch(self, req):
        if req.method == "OPTIONS":
            return 204, "text/plain", b"", {"Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                                            "Access-Control-Allow-Headers": "Content-Type, X-OTA-Token"}
        entry = self.routes.get((req.method, req.path))
        if entry is None:
            if self.fallback:
                return await self._call(self.fallback, req)
            if any(p == req.path for (_m, p) in self.routes):
                return err(405, "method not allowed")
            return err(404, "not found")
        handler, auth, stream = entry
        if auth:
            if self._locked(req.peer):
                return err(429, "too many failed attempts, try again later")
            given = req.headers.get("x-ota-token") or req.query.get("token") or ""
            tok = self.token()
            if not tok or not constant_time_eq(given, tok):
                self._note_fail(req.peer)
                return err(403, "missing or invalid X-OTA-Token")
        if not stream and req.length:
            if req.length > MAX_BODY:
                return err(413, "body too large")
            req.body = await req.reader.readexactly(req.length)
        return await self._call(handler, req)

    async def _call(self, handler, req):
        res = handler(req)
        if hasattr(res, "send"):            # coroutine
            res = await res
        if isinstance(res, tuple):
            return res
        return 200, "application/json", json.dumps(res)

    async def _send(self, writer, status, ctype, body, extra=None):
        streamed = hasattr(body, "__next__")            # generator of str/bytes chunks: length unknown, close-delimited
        if isinstance(body, str):
            body = body.encode()
        head = ("HTTP/1.1 %d %s\r\nContent-Type: %s\r\n" % (status, _REASONS.get(status, "OK"), ctype))
        if not streamed:
            head += "Content-Length: %d\r\n" % len(body)
        head += "Access-Control-Allow-Origin: *\r\nCache-Control: no-store\r\nConnection: close\r\n"
        if extra:
            for k, v in extra.items():
                head += "%s: %s\r\n" % (k, v)
        writer.write(head.encode() + b"\r\n")
        if streamed:
            buf = b""
            for chunk in body:
                buf += chunk.encode() if isinstance(chunk, str) else chunk
                if len(buf) >= 2048:
                    writer.write(buf)
                    await writer.drain()
                    buf = b""
            if buf:
                writer.write(buf)
                await writer.drain()
            return
        mv = memoryview(body)
        for i in range(0, len(mv), 4096):
            writer.write(mv[i:i + 4096])
            await writer.drain()


def err(status, msg):
    return status, "application/json", json.dumps({"error": msg})


def redirect(url):
    return 302, "text/plain", b"", {"Location": url}
