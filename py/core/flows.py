"""Where the energy goes: split solar, battery, grid and home power into the six flows the Flow screen draws.

Edges: sh solar->home, sb solar->battery, sg solar->grid (export), gh grid->home, gb grid->battery, bg battery->grid
(export), bh battery->home. All values are kW (or kWh when summed). The split is a priority rule, not a measurement:
solar serves the home first, then charges the battery, then exports; the battery serves what the home still needs;
the grid fills the rest. It always respects the measured totals (import, export, charge, discharge)."""
import asyncio

EDGES = ("sh", "sb", "sg", "gh", "gb", "bg", "bh")
INTERVAL_H = 300 / 3600.0


def split(pv, load, batt, grid):
    """pv, load >= 0; batt > 0 charging, < 0 discharging; grid > 0 importing, < 0 exporting."""
    pv, load = max(pv, 0.0), max(load, 0.0)
    chg, dis = max(batt, 0.0), max(-batt, 0.0)
    imp, exp = max(grid, 0.0), max(-grid, 0.0)
    sh = min(pv, load)
    sb = min(pv - sh, chg)
    sg = min(pv - sh - sb, exp)
    need = load - sh
    bh = min(dis, need)
    gh = min(imp, need - bh)
    bg = min(dis - bh, exp - sg)
    gb = min(imp - gh, chg - sb)
    return {"sh": sh, "sb": sb, "sg": sg, "gh": gh, "gb": gb, "bg": bg, "bh": bh}


def nodes(pv, load, batt, grid):
    """Per-node figures for the same instant: solar, home, grid in/out, battery in/out."""
    return {"solar": max(pv, 0.0), "home": max(load, 0.0), "g_in": max(grid, 0.0), "g_out": max(-grid, 0.0),
            "b_in": max(batt, 0.0), "b_out": max(-batt, 0.0)}


async def totals(hist, t0, t1):
    """Energy (kWh) per edge and per node over [t0, t1) from the 5-minute history. Yields now and then, so the UI keeps drawing."""
    from . import timeutil as T
    lo = T.bisect_left(hist.ts, hist.n, t0)
    hi = T.bisect_left(hist.ts, hist.n, t1)
    out = {k: 0.0 for k in EDGES}
    node = {"solar": 0.0, "home": 0.0, "g_in": 0.0, "g_out": 0.0, "b_in": 0.0, "b_out": 0.0}
    for n, i in enumerate(range(lo, hi)):
        if n & 255 == 255:
            await asyncio.sleep_ms(0)
        if not hist.ts[i]:
            continue
        pv, load, batt, grid = hist.pv[i] / 1000, hist.load[i] / 1000, hist.batt[i] / 1000, hist.grid[i] / 1000
        for k, v in split(pv, load, batt, grid).items():
            out[k] += v * INTERVAL_H
        for k, v in nodes(pv, load, batt, grid).items():
            node[k] += v * INTERVAL_H
    out.update(node)
    out["samples"] = max(hi - lo, 0)
    return out
