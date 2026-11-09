#!/usr/bin/env python3
"""
report_svg.py -- small, dependency-free SVG toolkit for the PlasBench report.

Everything returns plain strings, uses no JavaScript and is tested by parsing the output as XML. Circular figures follow
the convention of genome-map viewers (CGView, Proksee): position 0 at the top, positions increase clockwise.

Contents
  polar / bp_to_deg           coordinates
  split_wrapped               an interval that crosses the origin of a circular molecule becomes two
  sector_path / ring_path     annular sectors and full rings
  arrow_path                  a gene arrow that follows the circle, head at the downstream end
  nice_ticks / kb_label       a scale along the molecule
  place_labels                collision-free label placement with leader lines (no two label boxes overlap)
  svg_open / svg_close        the <svg> wrapper with <title> and <desc> (accessible, scales with its container)
  OKABE_ITO / CLASS_COLOURS   a colour-blind-safe palette keyed by feature class

Standard library only.
"""
import hashlib
import html
import math

OKABE_ITO = {
    "black": "#000000", "orange": "#E69F00", "sky": "#56B4E9", "green": "#009E73", "yellow": "#F0E442",
    "blue": "#0072B2", "vermillion": "#D55E00", "purple": "#CC79A7", "grey": "#999999",
}
# Feature classes drawn on plasmid maps. Hatch/shape (strand arrows, block rings) carries meaning too; colour is never the only channel.
CLASS_COLOURS = {
    "replication": "#882255",
    "amr": OKABE_ITO["vermillion"],
    "mobile": OKABE_ITO["sky"],
    "transfer": OKABE_ITO["blue"],
    "metal": OKABE_ITO["orange"],
    "integrase": OKABE_ITO["purple"],
    "maintenance": OKABE_ITO["green"],
    "other": "#8c8c8c",
}
CLASS_LABELS = {
    "replication": "Replication", "amr": "Antimicrobial resistance", "mobile": "Mobile element / IS",
    "transfer": "Conjugation / transfer", "metal": "Metal / biocide resistance", "integrase": "Integrase",
    "maintenance": "Maintenance", "other": "Other genes",
}
TWO_PI = 2 * math.pi


def esc(value):
    return html.escape(str(value), quote=True)


def num(x, digits=2):
    """Compact, locale-free number for SVG attributes (no scientific notation, no trailing zeros)."""
    if x != x or x in (float("inf"), float("-inf")):
        raise ValueError(f"non-finite coordinate: {x}")
    text = f"{x:.{digits}f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def bp_to_deg(position, length):
    """Position along a circular molecule -> degrees clockwise from the top (0 <= deg < 360)."""
    if length <= 0:
        return 0.0
    return (position % length) / length * 360.0


def polar(cx, cy, r, deg):
    """Degrees clockwise from the top -> (x, y) in SVG coordinates."""
    rad = math.radians(deg)
    return cx + r * math.sin(rad), cy - r * math.cos(rad)


def split_wrapped(start, end, length):
    """Intervals on a circular molecule of `length` bp as [(s, e), ...] in [0, length].

    start < end: one interval. start > end: the feature crosses the origin and is split in two.
    start == end, or anything with a non-positive length, is empty; an interval at least `length` long is the whole molecule.
    """
    if length <= 0:
        return []
    if start == end:
        return []
    if end - start >= length and end > start:
        return [(0, length)]
    start, end = start % length if start >= length else start, end % length if end > length else end
    if start < end:
        return [(max(0, start), min(length, end))]
    parts = []
    if start < length:
        parts.append((start, length))
    if end > 0:
        parts.append((0, end))
    return parts


def sector_path(cx, cy, r_in, r_out, a0, a1):
    """Annular sector from a0 to a1 degrees (clockwise). A sweep of 360 degrees or more is drawn as a full ring."""
    sweep = a1 - a0
    if sweep <= 0:
        return ""
    if sweep >= 359.999:
        return ring_path(cx, cy, r_in, r_out)
    large = 1 if sweep > 180 else 0
    x0, y0 = polar(cx, cy, r_out, a0)
    x1, y1 = polar(cx, cy, r_out, a1)
    x2, y2 = polar(cx, cy, r_in, a1)
    x3, y3 = polar(cx, cy, r_in, a0)
    return (f"M{num(x0)} {num(y0)}A{num(r_out)} {num(r_out)} 0 {large} 1 {num(x1)} {num(y1)}"
            f"L{num(x2)} {num(y2)}A{num(r_in)} {num(r_in)} 0 {large} 0 {num(x3)} {num(y3)}Z")


def ring_path(cx, cy, r_in, r_out):
    """A full annulus (even-odd fill)."""
    return (f"M{num(cx - r_out)} {num(cy)}A{num(r_out)} {num(r_out)} 0 1 1 {num(cx + r_out)} {num(cy)}"
            f"A{num(r_out)} {num(r_out)} 0 1 1 {num(cx - r_out)} {num(cy)}Z"
            f"M{num(cx - r_in)} {num(cy)}A{num(r_in)} {num(r_in)} 0 1 0 {num(cx + r_in)} {num(cy)}"
            f"A{num(r_in)} {num(r_in)} 0 1 0 {num(cx - r_in)} {num(cy)}Z")


def arrow_path(cx, cy, r_in, r_out, a0, a1, forward=True, head_deg=None, head_frac=0.32):
    """A gene arrow along the circle between a0 and a1 degrees. The head is at a1 for the forward strand and at a0 for the reverse.

    The head is `head_deg` degrees long (default: a third of the span, at most 4 degrees) and a feature shorter than the head is a
    triangle. The head is wider than the shaft so the strand is readable at small sizes.
    """
    sweep = a1 - a0
    if sweep <= 0:
        return ""
    head = head_deg if head_deg is not None else min(4.0, sweep * head_frac)
    head = min(head, sweep)
    mid = (r_in + r_out) / 2.0
    half = (r_out - r_in) / 2.0
    flare = half * 1.25
    if forward:
        base = a1 - head
        # the shaft is 62% of the ring height; the head flares beyond the full height
        shaft_out, shaft_in = mid + half * 0.62, mid - half * 0.62
        d = [f"M{num(polar(cx, cy, shaft_out, a0)[0])} {num(polar(cx, cy, shaft_out, a0)[1])}"]
        if base > a0:
            large = 1 if (base - a0) > 180 else 0
            x, y = polar(cx, cy, shaft_out, base)
            d.append(f"A{num(shaft_out)} {num(shaft_out)} 0 {large} 1 {num(x)} {num(y)}")
        x, y = polar(cx, cy, mid + flare, base)
        d.append(f"L{num(x)} {num(y)}")
        x, y = polar(cx, cy, mid, a1)
        d.append(f"L{num(x)} {num(y)}")
        x, y = polar(cx, cy, mid - flare, base)
        d.append(f"L{num(x)} {num(y)}")
        x, y = polar(cx, cy, shaft_in, base)
        d.append(f"L{num(x)} {num(y)}")
        if base > a0:
            large = 1 if (base - a0) > 180 else 0
            x, y = polar(cx, cy, shaft_in, a0)
            d.append(f"A{num(shaft_in)} {num(shaft_in)} 0 {large} 0 {num(x)} {num(y)}")
        d.append("Z")
        return "".join(d)
    base = a0 + head
    shaft_out, shaft_in = mid + half * 0.62, mid - half * 0.62
    x, y = polar(cx, cy, mid, a0)
    d = [f"M{num(x)} {num(y)}"]
    x, y = polar(cx, cy, mid + flare, base)
    d.append(f"L{num(x)} {num(y)}")
    x, y = polar(cx, cy, shaft_out, base)
    d.append(f"L{num(x)} {num(y)}")
    if a1 > base:
        large = 1 if (a1 - base) > 180 else 0
        x, y = polar(cx, cy, shaft_out, a1)
        d.append(f"A{num(shaft_out)} {num(shaft_out)} 0 {large} 1 {num(x)} {num(y)}")
    x, y = polar(cx, cy, shaft_in, a1)
    d.append(f"L{num(x)} {num(y)}")
    if a1 > base:
        large = 1 if (a1 - base) > 180 else 0
        x, y = polar(cx, cy, shaft_in, base)
        d.append(f"A{num(shaft_in)} {num(shaft_in)} 0 {large} 0 {num(x)} {num(y)}")
    x, y = polar(cx, cy, mid - flare, base)
    d.append(f"L{num(x)} {num(y)}")
    d.append("Z")
    return "".join(d)


def nice_ticks(length, target=10):
    """Round tick positions (bp) along a molecule: the 1, 2 or 5 x 10^k bp spacing that gives a tick count closest to `target`."""
    if length <= 0 or target <= 0:
        return 0, []
    raw = length / target
    magnitude = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    candidates = [f * m for m in (magnitude, magnitude * 10) for f in (1, 2, 5)]
    step = min(candidates, key=lambda c: abs(length / c - target))
    step = max(1, int(step))
    return step, list(range(0, length, step))


def kb_label(position):
    """'0', '20 kb', '1.5 kb', '2 Mb' for a position in bp."""
    if position == 0:
        return "0"
    if position >= 1_000_000:
        return f"{position / 1_000_000:g} Mb"
    if position >= 1_000:
        return f"{position / 1_000:g} kb"
    return f"{position} bp"


def text_box(text, font_size, x, y, anchor):
    """Estimated bounding box (x0, y0, x1, y1) of a one-line label (Arial averages about 0.56 em per character)."""
    width = len(text) * font_size * 0.56
    height = font_size * 1.15
    if anchor == "end":
        x0, x1 = x - width, x
    elif anchor == "middle":
        x0, x1 = x - width / 2, x + width / 2
    else:
        x0, x1 = x, x + width
    return (x0, y - height * 0.8, x1, y + height * 0.2)


def _overlap(a, b, pad=2.0):
    return not (a[2] + pad <= b[0] or b[2] + pad <= a[0] or a[3] + pad <= b[1] or b[3] + pad <= a[1])


def place_labels(items, cx, cy, r_base, font_size, width, height, levels=4, level_step=None, max_shift_deg=14.0, avoid=()):
    """Place radial labels around a circle without overlap.

    items: list of dicts with 'angle' (degrees clockwise from the top), 'text', optional 'priority' (higher first) and 'id'.
    Each label is tried at increasing radial levels and small angular shifts until its box overlaps no earlier label, no box in
    `avoid` and stays inside (0, 0, width, height). Returns (placed, dropped): placed items gain 'x', 'y', 'anchor', 'box' and
    'leader' ((x1, y1), (x2, y2)) from the feature point on the circle `r_base`; dropped are items that found no room.
    """
    level_step = level_step if level_step is not None else font_size * 1.5
    order = sorted(enumerate(items), key=lambda p: (-(p[1].get("priority") or 0), p[1]["angle"] % 360, p[0]))
    placed, dropped, boxes = [], [], list(avoid)
    for _, item in order:
        done = False
        shifts = [0.0]
        step = max(1.0, font_size / max(r_base, 1.0) * 57.3 * 0.6)
        k = 1
        while k * step <= max_shift_deg:
            shifts += [k * step, -k * step]
            k += 1
        for level in range(levels):
            radius = r_base + font_size * 0.6 + level * level_step
            for shift in shifts:
                angle = (item["angle"] + shift) % 360
                x, y = polar(cx, cy, radius, angle)
                anchor = "start" if x >= cx else "end"
                box = text_box(item["text"], font_size, x + (3 if anchor == "start" else -3), y + font_size * 0.35, anchor)
                if box[0] < 0 or box[2] > width or box[1] < 0 or box[3] > height:
                    continue
                if any(_overlap(box, other) for other in boxes):
                    continue
                boxes.append(box)
                fx, fy = polar(cx, cy, r_base, item["angle"])
                placed.append({**item, "x": x + (3 if anchor == "start" else -3), "y": y + font_size * 0.35, "anchor": anchor,
                               "box": box, "leader": ((fx, fy), (x, y)), "level": level})
                done = True
                break
            if done:
                break
        if not done:
            dropped.append(item)
    return placed, dropped


def svg_open(width, height, title, desc="", css_class="", extra=""):
    """The opening <svg> tag with an accessible name. The figure scales with its container (viewBox, no fixed pixel size)."""
    ident = "svg-" + hashlib.sha1(f"{title}|{width}|{height}".encode("utf-8")).hexdigest()[:8]
    return (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {num(width)} {num(height)}' role='img' "
            f"aria-labelledby='{ident}-t {ident}-d' class='{esc(css_class)}' preserveAspectRatio='xMidYMid meet' {extra}>"
            f"<title id='{ident}-t'>{esc(title)}</title><desc id='{ident}-d'>{esc(desc)}</desc>")


def svg_close():
    return "</svg>"


def text(x, y, content, size=11, anchor="start", weight="normal", fill="currentColor", extra=""):
    return (f"<text x='{num(x)}' y='{num(y)}' font-size='{num(size)}' text-anchor='{anchor}' font-weight='{weight}' "
            f"fill='{fill}' font-family='Arial,Helvetica,sans-serif' {extra}>{esc(content)}</text>")


def line(x1, y1, x2, y2, stroke="#666", width=1, extra=""):
    return (f"<line x1='{num(x1)}' y1='{num(y1)}' x2='{num(x2)}' y2='{num(y2)}' stroke='{stroke}' "
            f"stroke-width='{num(width)}' {extra}/>")


def path(d, fill="none", stroke="none", width=1, title="", extra=""):
    if not d:
        return ""
    inner = f"<title>{esc(title)}</title>" if title else ""
    return (f"<path d='{d}' fill='{fill}' stroke='{stroke}' stroke-width='{num(width)}' fill-rule='evenodd' {extra}>{inner}</path>")
