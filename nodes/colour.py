"""Colour check and Match to Reference, done the way a colourist would.

Nothing is segmented: every measurement is a hue / saturation / luminance range,
and every fix is a Photoshop adjustment layer the panel builds (Hue/Saturation
colour ranges, Blend If, Levels), named for what it changes, so it can be seen,
tuned or deleted.

The targets are CommonPoint's ("Fresh Angle to Perceiving Color"), measured on
the article's own images. Hues are Photoshop HSB degrees, levels are fractions
of white; Blend If values are Photoshop's 0-255.
"""

import base64
import io

import numpy as np

# Sky: the bright cyan-blue range. Aim 210 for the upper sky, 203 near the horizon
# (lighter), interpolated by luminosity between their two fill colours.
SKY_HUES = (150, 270)
SKY_LUM = 100 / 255
SKY_PASS = (195, 225)
SKY_AIM = ((116 / 255, 210), (169 / 255, 203))
# Foliage: yellow-green to green-blue in the midtones (from 50, to leave out wood).
FOLIAGE_HUES = (50, 160)
FOLIAGE_LUM = (15 / 255, 200 / 255)
FOLIAGE_PASS = (70, 120)
FOLIAGE_AIM = 82
FOLIAGE_SPREAD = 30  # widest acceptable middle half (25th to 75th percentile)
# Levels: the darkest 0.5% at most 10%; the 98th percentile between 75 and 91%.
BLACKS_MAX = 0.10
BLACKS_AIM = 0.03
WHITES_PASS = (0.75, 0.91)
WHITES_AIM = (0.80, 0.89)  # where a fix lands when too dull / too bright
# Green-magenta offset of neutral pixels. CommonPoint's own good renders reach 5.6
# in the highlights (light bounced off foliage), so the line is a little above.
TINT_MAX = 6 / 255
# Share of the blacks (or whites) that may be strongly coloured: their good renders
# measure 0.07-0.31; a broken white balance, 1.0.
COLOURFUL_MAX = 0.5
SHARE = 0.03  # a range must cover this much of the image to be judged

# Photoshop's Hue/Saturation colour ranges: slot index, name, centre.
RANGES = [(1, "Reds", 0), (2, "Yellows", 60), (3, "Greens", 120), (4, "Cyans", 180), (5, "Blues", 240), (6, "Magentas", 300)]
# Match to Reference moves hues and saturation at most this far, to stay natural.
MATCH_HUE = 15
MATCH_SAT = 25
MATCH_TINT = 25 / 255
# Mids follow the reference only this far (Levels gamma): scenes differ in content.
MATCH_GAMMA = (0.75, 1.35)

MAX_PIXELS = 1_000_000


class Pixels:
    """An RGB image as Photoshop HSB plus luminosity (Blend If's "Gray"), all 0-1
    except hue (degrees), flattened and subsampled to about a megapixel."""

    def __init__(self, rgb):
        a = np.asarray(rgb)
        a = a.astype(np.float32) / 255 if a.dtype == np.uint8 else a.astype(np.float32)
        a = a[..., :3]
        step = max(1, int(np.ceil(np.sqrt(a.shape[0] * a.shape[1] / MAX_PIXELS))))
        a = a[::step, ::step].reshape(-1, 3)
        self.rgb = a
        r, g, b = a[:, 0], a[:, 1], a[:, 2]
        mx = a.max(axis=1)
        mn = a.min(axis=1)
        c = mx - mn
        self.v = mx
        self.chroma = c
        self.s = np.where(mx > 0, c / np.maximum(mx, 1e-6), 0)
        safe = np.maximum(c, 1e-6)
        h = np.where(mx == r, ((g - b) / safe) % 6, np.where(mx == g, (b - r) / safe + 2, (r - g) / safe + 4))
        self.h = np.where(c > 0, h * 60, 0) % 360
        self.lum = 0.3 * r + 0.59 * g + 0.11 * b
        # Only pixels with real colour have a hue worth counting; greys don't.
        self.weight = np.where((self.s >= 0.15) & (c >= 0.08), c, 0)
        self.count = len(a)


def decode(data):
    """A base64 PNG (or raw bytes) as an RGB uint8 array."""
    from PIL import Image

    raw = base64.b64decode(data) if isinstance(data, str) else data
    return np.asarray(Image.open(io.BytesIO(raw)).convert("RGB"))


def offset(h, centre):
    """Hue h relative to centre, in -180..180."""
    return (np.asarray(h) - centre + 180) % 360 - 180


def in_hues(h, lo, hi):
    return offset(h, lo) % 360 <= (hi - lo) % 360


def wquantile(values, weights, q):
    order = np.argsort(values)
    v = values[order]
    cum = np.cumsum(weights[order])
    return float(np.interp(np.asarray(q) * cum[-1], cum, v))


def hue_stats(px, mask, centre):
    """Weighted hue percentiles of the masked pixels, unwrapped around centre."""
    w = px.weight * mask
    if (w > 0).sum() < px.count * SHARE:
        return None
    sel = w > 0
    d = offset(px.h[sel], centre)
    q = [wquantile(d, w[sel], p) + centre for p in (0.1, 0.25, 0.5, 0.75, 0.9)]
    return {"p10": q[0], "p25": q[1], "median": q[2], "p75": q[3], "p90": q[4], "share": float(sel.mean()), "sel": sel, "w": w}


def to_hex(rgb):
    return "#" + "".join(f"{int(round(min(1, max(0, x)) * 255)):02X}" for x in rgb)


def hsb_rgb(h, s, v):
    h = (h % 360) / 60
    c = v * s
    x = c * (1 - abs(h % 2 - 1))
    r, g, b = [(c, x, 0), (x, c, 0), (0, c, x), (0, x, c), (x, 0, c), (c, 0, x)][int(h) % 6]
    m = v - c
    return (r + m, g + m, b + m)


def swatches(px, stats, target):
    """The range's typical colour now and with its hue at target, as hex."""
    sel, w = stats["sel"], stats["w"][stats["sel"]]
    s = float(np.average(px.s[sel], weights=w))
    v = float(np.average(px.v[sel], weights=w))
    return [to_hex(hsb_rgb(stats["median"], s, v)), to_hex(hsb_rgb(target, s, v))]


def deg(h):
    return f"{round(h) % 360}°"


def nearest_slot(h):
    return min(RANGES, key=lambda r: abs(offset(h, r[2])))


def hue_range(lo, hi, hue, ramp=20, saturation=0):
    """One Hue/Saturation colour range: full effect from lo to hi, fading over ramp."""
    slot = nearest_slot((lo + offset(hi, lo) / 2))
    ramps = [round(x) % 360 for x in (lo - ramp, lo, hi, hi + ramp)]
    return {"slot": slot[0], "slotName": slot[1], "ramps": ramps, "hue": int(round(hue)), "saturation": int(round(saturation)), "lightness": 0}


def hue_sat(name, ranges=(), master=None, blend_if=None):
    return {"kind": "hueSat", "name": name, "ranges": list(ranges), "master": master, "blendIf": blend_if, "blendMode": "normal"}


def levels(name, channels, blend_mode="normal"):
    return {"kind": "levels", "name": name, "channels": channels, "blendMode": blend_mode}


def fit_levels(low, high, mid=None, gammas=(0.33, 3.0)):
    """Levels (inputs, gamma, outputs; all 0-1) taking low[0] to low[1], high[0] to
    high[1], and with mid, mid[0] to mid[1]."""
    (x1, y1), (x2, y2) = low, high
    a = (y2 - y1) / max(x2 - x1, 1e-6)
    a = max(a, 1e-3)
    c = y1 - a * x1
    ib = max(0.0, -c / a)
    iw = min(1.0, (1 - c) / a)
    ob, ow = a * ib + c, a * iw + c
    gamma = 1.0
    # Gamma moves every point but the input ends, so fit it and the inputs in turn.
    for _ in range(40 if mid else 0):
        t = (mid[0] - ib) / max(iw - ib, 1e-6)
        u = (mid[1] - ob) / max(ow - ob, 1e-6)
        if not (0 < t < 1 and 0 < u < 1):
            break
        gamma = float(np.clip(np.log(t) / np.log(u), *gammas))
        t1, t2 = (float(np.clip((y - ob) / max(ow - ob, 1e-6), 0, 1)) ** gamma for y in (y1, y2))
        if t2 - t1 < 1e-6:
            break
        span = (x2 - x1) / (t2 - t1)
        ib = max(0.0, x1 - t1 * span)
        iw = min(1.0, ib + span)
    return {"input": [ib, iw], "gamma": gamma, "output": [ob, ow]}


def apply_levels(x, lv):
    """Photoshop's Levels formula, for tests and for predicting a result."""
    (ib, iw), g, (ob, ow) = lv["input"], lv["gamma"], lv["output"]
    t = np.clip((np.asarray(x) - ib) / max(iw - ib, 1e-6), 0, 1)
    return ob + (ow - ob) * t ** (1 / g)


def levels_255(lv):
    """Levels in Photoshop's units: 0-255 integers and a gamma with two decimals."""
    return {"input": [round(v * 255) for v in lv["input"]], "gamma": round(lv["gamma"], 2), "output": [round(v * 255) for v in lv["output"]]}


def pct(x):
    return f"{round(x * 100)}%"


def finding(key, title, status, text, swatch=None):
    out = {"key": key, "title": title, "status": status, "text": text}
    if swatch:
        out["swatches"] = swatch
    return out


# --- measurements ---


def sky(px):
    mask = in_hues(px.h, *SKY_HUES) & (px.lum >= SKY_LUM)
    stats = hue_stats(px, mask, 210)
    if stats:
        (l1, a1), (l2, a2) = SKY_AIM
        aims = np.interp(px.lum[stats["sel"]], [l1, l2], [a1, a2])
        stats["aim"] = float(np.average(aims, weights=stats["w"][stats["sel"]]))
    return stats


def foliage(px):
    mask = in_hues(px.h, *FOLIAGE_HUES) & (px.lum >= FOLIAGE_LUM[0]) & (px.lum <= FOLIAGE_LUM[1])
    return hue_stats(px, mask, 105)


def tone(px):
    lum = px.lum
    return {
        "black": float(np.quantile(lum, 0.005)),
        "mid": float(np.quantile(lum, 0.5)),
        "white": float(np.quantile(lum, 0.98)),
        "crushed": float((px.v <= 1 / 255).mean()),
        "clipped": float((px.rgb.max(axis=1) >= 254 / 255).mean()),
    }


ZONES = [("shadows", 0.08, 1 / 3), ("midtones", 1 / 3, 2 / 3), ("highlights", 2 / 3, 0.92)]


def neutrals(px):
    """Mean R, G, B and luminosity of near-grey pixels in each tonal zone."""
    grey = px.s < 0.12
    out = {}
    for name, lo, hi in ZONES:
        sel = grey & (px.lum >= lo) & (px.lum < hi)
        if sel.sum() >= px.count * 0.01:
            r, g, b = px.rgb[sel].mean(axis=0)
            out[name] = {"rgb": [float(r), float(g), float(b)], "lum": float(px.lum[sel].mean()), "tint": float(g - (r + b) / 2)}
    return out


def colourful_extremes(px):
    """Share of the blacks and of the whites that is strongly coloured."""
    out = {}
    for name, sel in (("blacks", px.lum < 0.1), ("whites", px.lum > 0.9)):
        if sel.sum() >= px.count * 0.01:
            out[name] = float(((px.s[sel] > 0.4) & (px.chroma[sel] > 0.05)).mean())
    return out


def range_stats(px):
    """Typical hue and saturation in each of Photoshop's six colour ranges."""
    out = {}
    for slot, name, centre in RANGES:
        mask = np.abs(offset(px.h, centre)) <= 30
        sel = (px.weight * mask) > 0
        if sel.sum() >= px.count * 0.01:
            w = px.weight[sel]
            out[name] = {"slot": slot, "centre": centre, "hue": wquantile(offset(px.h[sel], centre), w, 0.5) + centre, "saturation": float(np.average(px.s[sel], weights=w)), "share": float(sel.mean())}
    return out


# --- the colour check ---


def check(image):
    """Findings for the colour check and the adjustment layers that fix the failing
    ones: {findings: [...], layers: [...]}, layers bottom to top."""
    px = Pixels(image)
    findings, layers = [], []

    t = tone(px)
    lo = (t["black"], BLACKS_AIM) if t["black"] > BLACKS_MAX else (t["black"], t["black"])
    if t["white"] > WHITES_PASS[1]:
        hi = (t["white"], WHITES_AIM[1])
    elif t["white"] < WHITES_PASS[0]:
        hi = (t["white"], WHITES_AIM[0])
    else:
        hi = (t["white"], t["white"])
    findings.append(finding("blacks", "Blacks", "warn" if t["black"] > BLACKS_MAX else "ok",
                            f"Darkest pixels at {pct(t['black'])}" + (f": raised, aim near {pct(BLACKS_AIM)} (pass up to {pct(BLACKS_MAX)})." if t["black"] > BLACKS_MAX else f" (pass up to {pct(BLACKS_MAX)}).")))
    white_ok = WHITES_PASS[0] <= t["white"] <= WHITES_PASS[1]
    findings.append(finding("whites", "Whites", "ok" if white_ok else "warn",
                            f"Whites (98th percentile) at {pct(t['white'])}" + (f" (pass {pct(WHITES_PASS[0])}–{pct(WHITES_PASS[1])})." if white_ok else f": {'too dull' if t['white'] < WHITES_PASS[0] else 'too bright'}, pass {pct(WHITES_PASS[0])}–{pct(WHITES_PASS[1])}.")))
    if lo[0] != lo[1] or hi[0] != hi[1]:
        lv = fit_levels(lo, hi)
        parts = []
        if lo[0] != lo[1]:
            parts.append(f"blacks {pct(lo[0])}→{pct(lo[1])}")
        if hi[0] != hi[1]:
            parts.append(f"whites {pct(hi[0])}→{pct(hi[1])}")
        layers.append(levels("Levels: " + ", ".join(parts), {"composite": levels_255(lv)}, "luminosity"))
    if t["crushed"] > 0.01:
        findings.append(finding("crushed", "Crushed shadows", "warn", f"{t['crushed'] * 100:.1f}% of the image is pure black: shadow detail is lost. Fix it in the render or grade, not here."))
    if t["clipped"] > 0.01:
        findings.append(finding("clipped", "Blown highlights", "warn", f"{t['clipped'] * 100:.1f}% of the image is clipped white. Fix it in the render or grade, not here."))

    n = neutrals(px)
    tinted = {k: z for k, z in n.items() if abs(z["tint"]) > TINT_MAX}
    if not n:
        findings.append(finding("tint", "Green / magenta", "skip", "Too few neutral pixels to judge."))
    elif not tinted:
        findings.append(finding("tint", "Green / magenta", "ok", "Neutrals read neutral."))
    else:
        desc = ", ".join(f"{k} {'green' if z['tint'] > 0 else 'magenta'} {abs(z['tint']) * 255:.0f}" for k, z in tinted.items())
        findings.append(finding("tint", "Green / magenta", "warn", f"Neutral pixels lean {desc} (levels of 255). Warm/cool is fine; green or magenta reads unnatural."))
        layers.append(neutralise(n))

    for name, share in colourful_extremes(px).items():
        if share > COLOURFUL_MAX:
            findings.append(finding("sat_" + name, f"Colourful {name}", "warn", f"{round(share * 100)}% of the {name} are strongly coloured; saturation belongs in the midtones."))
            blend = [0, 0, 25, 45] if name == "blacks" else [210, 230, 255, 255]
            layers.append(hue_sat(f"Desaturate {name} (sat −40)", master={"hue": 0, "saturation": -40, "lightness": 0}, blend_if=blend))

    s = sky(px)
    if not s:
        findings.append(finding("sky", "Sky", "skip", "No bright cyan-blue area big enough to be a daytime sky."))
    else:
        ok = SKY_PASS[0] <= s["median"] <= SKY_PASS[1]
        findings.append(finding("sky", "Sky", "ok" if ok else "warn",
                                f"Bright blues at {deg(s['median'])}, aim {deg(s['aim'])} (pass {SKY_PASS[0]}–{SKY_PASS[1]}°)" + ("." if ok else f": {'too green-cyan' if s['median'] < SKY_PASS[0] else 'too purple'}."),
                                swatches(px, s, s["aim"])))
        if not ok:
            shift = float(np.clip(s["aim"] - s["median"], -40, 40))
            lo_h = max(s["p10"] - 5, SKY_HUES[0])
            hi_h = min(s["p90"] + 5, SKY_HUES[1])
            rng = hue_range(lo_h, hi_h, shift)
            # Blend If: only where the image underneath is bright, fading in from 80 to 100.
            layers.append(hue_sat(f"Sky hue {deg(s['median'])}→{deg(s['median'] + shift)} (Hue/Sat {rng['slotName']}, Blend If 80–100)", [rng], blend_if=[80, 100, 255, 255]))

    f = foliage(px)
    if not f:
        findings.append(finding("foliage", "Foliage", "skip", "No yellow-green to green-blue midtones big enough to be foliage."))
    else:
        ok = FOLIAGE_PASS[0] <= f["median"] <= FOLIAGE_PASS[1]
        target = f["median"] if ok else f["median"] + float(np.clip(FOLIAGE_AIM - f["median"], -30, 30))
        findings.append(finding("foliage", "Foliage", "ok" if ok else "warn",
                                f"Greens at {deg(f['median'])}, aim about {FOLIAGE_AIM}° (pass {FOLIAGE_PASS[0]}–{FOLIAGE_PASS[1]}°)" + ("." if ok else f": {'too yellow' if f['median'] < FOLIAGE_PASS[0] else 'too blue-green'}."),
                                swatches(px, f, FOLIAGE_AIM if not ok else f["median"])))
        blend = [0, 0, 200, 230]  # leave bright highlights alone
        if not ok:
            shift = target - f["median"]
            rng = hue_range(max(f["p10"], FOLIAGE_HUES[0]), min(f["p90"], FOLIAGE_HUES[1]), shift, ramp=15)
            layers.append(hue_sat(f"Foliage hue {deg(f['median'])}→{deg(target)} (Hue/Sat {rng['slotName']}, Blend If 200–230)", [rng], blend_if=blend))
        spread = f["p75"] - f["p25"]
        if spread > FOLIAGE_SPREAD:
            findings.append(finding("spread", "Foliage spread", "warn", f"The middle half of the greens spans {spread:.0f}° ({deg(f['p25'])}–{deg(f['p75'])}); keep foliage in one hue (under {FOLIAGE_SPREAD}°)."))
            # Pinch both sides halfway toward the middle, after the hue layer's shift.
            d = target - f["median"]
            m, p10, p25, p75, p90 = (f[k] + d for k in ("median", "p10", "p25", "p75", "p90"))
            up, down = (m - p25) / 2, (p75 - m) / 2
            layers.append(hue_sat(f"Foliage spread {spread:.0f}°→~{spread / 2:.0f}° (Hue/Sat, both sides toward {deg(m)})",
                                  [hue_range(p10 - 10, m - 8, up, ramp=8), hue_range(m + 8, p90 + 10, -down, ramp=8)], blend_if=blend))
        else:
            findings.append(finding("spread", "Foliage spread", "ok", f"The middle half of the greens spans {spread:.0f}° (under {FOLIAGE_SPREAD}°)."))

    return {"findings": findings, "layers": layers}


def neutralise(n):
    """A Levels layer on the green channel that takes the neutrals' green to the
    average of their red and blue: only the green-magenta axis moves."""
    pts = []
    for name in ("shadows", "midtones", "highlights"):
        if name in n:
            z = n[name]
            pts.append((z["rgb"][1], z["rgb"][1] - z["tint"]))
    return levels("Neutralise green/magenta (Levels, Green channel)", {"green": levels_255(levels_through(pts))})


def levels_through(pts):
    """Levels through up to three (from, to) points, darkest first."""
    pts = sorted(pts)
    if len(pts) == 1:
        (x, y), = pts
        # Gamma alone, ends fixed.
        return fit_levels((0, 0), (1, 1), (x, y))
    return fit_levels(pts[0], pts[-1], pts[1] if len(pts) == 3 else None)


# --- Match to Reference ---


def match(image, reference):
    """Adjustment layers that take image toward reference, as a colourist matches a
    shot: levels first (in Luminosity mode, so hues stay), then the balance of the
    neutrals, then hue and saturation per colour range. {findings, layers}."""
    src, ref = Pixels(image), Pixels(reference)
    findings, layers = [], []

    a, b = tone(src), tone(ref)
    lv = fit_levels((a["black"], b["black"]), (a["white"], b["white"]), (a["mid"], b["mid"]), MATCH_GAMMA)
    if max(abs(a[k] - b[k]) for k in ("black", "mid", "white")) > 2 / 255:
        mid = float(apply_levels(a["mid"], lv))
        limited = " (limited)" if abs(mid - b["mid"]) > 0.02 else ""
        text = f"blacks {pct(a['black'])}→{pct(b['black'])}, mids {pct(a['mid'])}→{pct(mid)}{limited}, whites {pct(a['white'])}→{pct(b['white'])}"
        layers.append(levels("Levels like reference: " + text, {"composite": levels_255(lv)}, "luminosity"))
        findings.append(finding("levels", "Levels", "info", text[0].upper() + text[1:] + (f"; the reference's mids are {pct(b['mid'])}." if limited else ".")))
    else:
        findings.append(finding("levels", "Levels", "ok", "Already like the reference."))

    na, nb = neutrals(src), neutrals(ref)
    zones = [z for z in ("shadows", "midtones", "highlights") if z in na and z in nb]
    if not zones:
        findings.append(finding("balance", "Balance", "skip", "Too few neutral pixels in one of the images to compare."))
    else:
        channels, moved = {}, 0.0
        for i, ch in enumerate(("red", "green", "blue")):
            pts = []
            for z in zones:
                # Each channel's offset from the zone's luminosity, as in the reference.
                delta = (nb[z]["rgb"][i] - nb[z]["lum"]) - (na[z]["rgb"][i] - na[z]["lum"])
                delta = float(np.clip(delta, -MATCH_TINT, MATCH_TINT))
                moved = max(moved, abs(delta))
                pts.append((na[z]["rgb"][i], na[z]["rgb"][i] + delta))
            channels[ch] = levels_255(levels_through(pts))
        if moved > 2 / 255:
            layers.append(levels("Balance like reference (Levels, R/G/B channels)", channels))
            findings.append(finding("balance", "Balance", "info", f"Neutrals moved up to {moved * 255:.0f} levels per channel ({', '.join(zones)})."))
        else:
            findings.append(finding("balance", "Balance", "ok", "Neutrals already balanced like the reference."))

    ra, rb = range_stats(src), range_stats(ref)
    ranges, parts = [], []
    for slot, name, centre in RANGES:
        if name not in ra or name not in rb:
            continue
        hue = float(np.clip(offset(rb[name]["hue"], ra[name]["hue"]), -MATCH_HUE, MATCH_HUE))
        sat = float(np.clip((rb[name]["saturation"] / max(ra[name]["saturation"], 1e-3) - 1) * 100, -MATCH_SAT, MATCH_SAT))
        if abs(hue) < 2 and abs(sat) < 3:
            continue
        rng = {"slot": slot, "slotName": name, "ramps": [(centre - 45) % 360, (centre - 15) % 360, (centre + 15) % 360, (centre + 45) % 360], "hue": int(round(hue)), "saturation": int(round(sat)), "lightness": 0}
        ranges.append(rng)
        parts.append(f"{name} {rng['hue']:+d}°, sat {rng['saturation']:+d}")
    if ranges:
        layers.append(hue_sat("Hue/Sat like reference: " + "; ".join(parts), ranges))
        findings.append(finding("ranges", "Colour ranges", "info", "; ".join(parts) + "."))
    else:
        findings.append(finding("ranges", "Colour ranges", "ok", "No colour range both images share differs enough to move."))
    return {"findings": findings, "layers": layers}


def register_routes():
    import asyncio

    from aiohttp import web
    from server import PromptServer

    routes = PromptServer.instance.routes

    async def run(request, fn, *keys):
        body = await request.json()
        try:
            images = [decode(body[k]) for k in keys]
        except Exception as e:
            return web.json_response({"error": f"Couldn't read the image: {e}"}, status=400)
        result = await asyncio.get_running_loop().run_in_executor(None, fn, *images)
        return web.json_response(result)

    @routes.post("/gpc_ps/colour/check")
    async def _check(request):
        return await run(request, check, "image")

    @routes.post("/gpc_ps/colour/match")
    async def _match(request):
        return await run(request, match, "image", "reference")
