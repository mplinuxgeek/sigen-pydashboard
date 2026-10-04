#!/usr/bin/env python3
"""Capture the panel's screens as PNGs and, if you like, an animated GIF tour, over its HTTP API.

  scripts/capture_screens.py 192.168.1.50                       every screen into ./screenshots/
  scripts/capture_screens.py 192.168.1.50 -o docs/img --gif     into docs/img, plus docs/img/tour.gif
  scripts/capture_screens.py 192.168.1.50 --skip system         leave out the Info / Settings / WiFi screens
  scripts/capture_screens.py 192.168.1.50 --record 30           film whichever screen is showing for 30 s (GIF only)

Needs: pip install requests pillow   (pillow only for GIFs)

Files are named after what the panel says it is showing (POST /api/swipe answers with the view name: "dashboard", "flow",
"graph", "monthly", "system/info", ... and "/" becomes "-"), so a new screen appears here on its own. The walk starts at the
first screen (swipe right until nothing moves) and goes left until nothing moves.

The Flow screen has three views. With the admin token (--token, or PANEL_TOKEN in the environment) the script taps the
Today and Month buttons through the diagnostics endpoint and saves flow-now.png, flow-today.png and flow-month.png;
without it only the live view is captured, as flow.png.

Privacy: the Info, Settings and WiFi screens show serial numbers, the admin token, MAC and network names. Use --skip system
for anything you will publish.

The panel returns to the Dashboard by itself after 30 s without a touch; a full capture takes well under that.
"""
import argparse
import io
import os
import sys
import time

try:
    import requests
except ImportError:
    sys.exit("The 'requests' package is required: pip install requests")

DEFAULT_PORT = 80
DEFAULT_OUTPUT_DIR = "screenshots"
REQUEST_TIMEOUT = 15
DEFAULT_SETTLE_S = 3.5                    # the page dots at the bottom fade 3 s after a swipe; the Graph / Flow screens also redraw and work out data
FLOW_SETTLE_S = {"today": 7.0, "month": 14.0}    # the Flow totals add up the stored history in the background
DEFAULT_GIF_NAME = "tour.gif"
DEFAULT_RECORD_GIF_NAME = "record.gif"
DEFAULT_GIF_DELAY_MS = 3000
GIF_COLORS = 128
KEEPALIVE_INTERVAL_S = 10

# Flow mode buttons (panel pixels): landscape 800x480 and portrait 480x800
FLOW_BUTTONS = {
    (800, 480): {"now": (574, 26), "today": (655, 26), "month": (738, 26)},
    (480, 800): {"now": (288, 26), "today": (355, 26), "month": (433, 26)},
}


def log(msg):
    print(msg)


def warn(msg):
    print("warning: " + msg, file=sys.stderr)


def api(session, base, method, path, **kw):
    resp = session.request(method, base + path, timeout=REQUEST_TIMEOUT, **kw)
    resp.raise_for_status()
    return resp


def swipe(session, base, direction):
    """One step left, right, or 'none' (stay, but count as a touch). Returns (view, changed)."""
    d = api(session, base, "POST", "/api/swipe", params={"dir": direction}).json()
    return d["view"], d["changed"]


def current_view(session, base):
    return api(session, base, "GET", "/api/view").json()["view"]


def screenshot(session, base):
    return api(session, base, "GET", "/api/screenshot").content


def safe_name(view):
    return "".join(c if (c.isalnum() or c in "-_. ") else "-" for c in view.replace("/", "-"))


def save(png, out_dir, prefix, name):
    path = os.path.join(out_dir, "%s%s.png" % (prefix, safe_name(name)))
    with open(path, "wb") as f:
        f.write(png)
    log("  %-18s -> %s (%s bytes)" % (name, path, format(len(png), ",")))
    return path


def png_size(png):
    return int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")


def skipped(view, skip):
    return any(view.startswith(s) or view.split("/")[0] == s for s in skip)


def flow_modes(session, base, token, png0, out_dir, prefix, settle_s):
    """Tap Today and Month on the Flow screen and capture them; returns [(name, png)], then taps Now again."""
    buttons = FLOW_BUTTONS.get(png_size(png0))
    if not buttons:
        warn("unknown screen size %s: only the live Flow view is captured" % (png_size(png0),))
        return []
    headers = {"X-OTA-Token": token}

    def tap(mode):
        x, y = buttons[mode]
        api(session, base, "POST", "/api/bench/tap", params={"x": x, "y": y}, headers=headers)
    out = []
    for mode in ("today", "month"):
        tap(mode)
        time.sleep(FLOW_SETTLE_S[mode])
        png = screenshot(session, base)
        save(png, out_dir, prefix, "flow-" + mode)
        out.append(("flow-" + mode, png))
    tap("now")
    time.sleep(settle_s)
    return out


def capture_all(host, port, out_dir, prefix, go_home, settle_s, token, skip):
    base = "http://%s:%d" % (host, port)
    os.makedirs(out_dir, exist_ok=True)
    session = requests.Session()
    if go_home:
        for _ in range(20):                          # swipe right until nothing moves: the first screen
            view, changed = swipe(session, base, "right")
            if not changed:
                break
        else:
            warn("never reached the first screen; capturing from here")
    else:
        view = current_view(session, base)
    frames, written, seen = [], [], set()
    for _ in range(21):
        if view in seen:
            warn("%s came round again: the UI moved mid-walk, stopping here" % view)
            break
        seen.add(view)
        time.sleep(settle_s)
        if not skipped(view, skip):
            png = screenshot(session, base)
            if view == "flow" and token:
                written.append(save(png, out_dir, prefix, "flow-now"))
                frames.append(("flow-now", png))
                for name, extra in flow_modes(session, base, token, png, out_dir, prefix, settle_s):
                    written.append(os.path.join(out_dir, "%s%s.png" % (prefix, name)))
                    frames.append((name, extra))
            else:
                written.append(save(png, out_dir, prefix, view))
                frames.append((view, png))
        view, changed = swipe(session, base, "left")
        if not changed:
            break
    return written, frames


def record(host, port, seconds, settle_s):
    """Re-capture the screen that is showing for `seconds`; each frame carries the time it really took, so playback is true."""
    base = "http://%s:%d" % (host, port)
    session = requests.Session()
    log("  recording %s for %gs ..." % (current_view(session, base), seconds))
    frames, deadline = [], time.monotonic() + seconds
    prev, next_keepalive = time.monotonic(), time.monotonic()
    while time.monotonic() < deadline:
        if time.monotonic() >= next_keepalive:
            swipe(session, base, "none")
            next_keepalive = time.monotonic() + KEEPALIVE_INTERVAL_S
        png = screenshot(session, base)
        now = time.monotonic()
        if frames:
            frames[-1] = (frames[-1][0], (now - prev) * 1000)
        frames.append((png, None))
        prev = now
        if settle_s:
            time.sleep(settle_s)
    if frames:
        known = [d for _, d in frames[:-1] if d]
        frames[-1] = (frames[-1][0], sum(known) / len(known) if known else None)
    return frames


def write_gif(frames, path, delay_ms, scale):
    """frames: [(png_bytes, duration_ms or None)]. One frame per screen, `delay_ms` each unless a duration is given."""
    try:
        from PIL import Image, ImageFile
    except ImportError:
        sys.exit("GIF output needs pillow: pip install pillow")
    ImageFile.LOAD_TRUNCATED_IMAGES = True          # the panel's PNG encoder ends its zlib stream in a way Pillow calls truncated
    if not frames:
        warn("nothing captured, no GIF written")
        return None
    images, durations = [], []
    for png, ms in frames:
        img = Image.open(io.BytesIO(png)).convert("RGB")
        if scale != 1.0:
            img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
        images.append(img.convert("P", palette=Image.ADAPTIVE, colors=GIF_COLORS))
        durations.append(int(ms or delay_ms))
    images[0].save(path, save_all=True, append_images=images[1:], duration=durations, loop=0, optimize=True, disposal=2)
    log("  GIF: %d frame(s), %dx%d -> %s (%s bytes)" % (len(images), images[0].width, images[0].height, path,
                                                         format(os.path.getsize(path), ",")))
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("host", help="panel IP address or name")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("-o", "--output-dir", default=DEFAULT_OUTPUT_DIR, help="where to write the PNGs (default: screenshots/)")
    ap.add_argument("--prefix", default="", help="prepended to every file name")
    ap.add_argument("--no-home", action="store_true", help="start from the screen showing now instead of the first one")
    ap.add_argument("--settle", type=float, default=DEFAULT_SETTLE_S, metavar="SECONDS", help="pause after each swipe")
    ap.add_argument("--token", default=os.environ.get("PANEL_TOKEN"), help="admin token (default: $PANEL_TOKEN); enables the Flow Today/Month captures")
    ap.add_argument("--skip", default="", metavar="NAMES", help="comma-separated screens to leave out, e.g. system")
    ap.add_argument("--gif", nargs="?", const=True, default=False, metavar="FILE", help="also write a GIF tour (default: <output-dir>/tour.gif)")
    ap.add_argument("--record", type=float, metavar="SECONDS", help="film the screen that is showing, write only a GIF")
    ap.add_argument("--gif-delay", type=int, default=DEFAULT_GIF_DELAY_MS, metavar="MS", help="how long each screen is held in the tour")
    ap.add_argument("--gif-scale", type=float, default=1.0, metavar="FACTOR", help="scale frames, e.g. 0.75")
    a = ap.parse_args()
    skip = [s.strip() for s in a.skip.split(",") if s.strip()]
    log("Capturing from http://%s:%d ..." % (a.host, a.port))
    try:
        if a.record is not None:
            path = a.gif if isinstance(a.gif, str) else os.path.join(a.output_dir, a.prefix + DEFAULT_RECORD_GIF_NAME)
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            return 0 if write_gif(record(a.host, a.port, a.record, a.settle), path, a.gif_delay, a.gif_scale) else 1
        written, frames = capture_all(a.host, a.port, a.output_dir, a.prefix, not a.no_home, a.settle, a.token, skip)
        if a.gif:
            path = a.gif if isinstance(a.gif, str) else os.path.join(a.output_dir, a.prefix + DEFAULT_GIF_NAME)
            if not write_gif([(png, None) for _n, png in frames], path, a.gif_delay, a.gif_scale):
                return 1
    except requests.exceptions.HTTPError as e:
        detail = ""
        try:
            detail = ": " + e.response.json().get("error", "")
        except ValueError:
            pass
        print("error: %s %s returned %s%s" % (e.response.request.method, e.response.request.url, e.response.status_code, detail), file=sys.stderr)
        return 1
    except requests.exceptions.RequestException as e:
        print("error: could not reach %s:%d -- %s" % (a.host, a.port, e), file=sys.stderr)
        return 1
    log("Captured %d screen(s) into %s/" % (len(written), a.output_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
