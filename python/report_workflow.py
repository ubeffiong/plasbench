#!/usr/bin/env python3
"""
report_workflow.py -- the PlasBench workflow figure, drawn once as docs/images/workflow.svg for the README.

The figure used to be a section of the HTML report. It describes how the pipeline is built, not what one run produced, so it
lives in the README now and the report no longer carries it. The figure has three panels:

  a  inputs (isolate short reads, complete reference genome) and truth construction
  b  short-read assembly and the tools, grouped by class
  c  scoring layers, statistics and the recommendation

One colour per stage family, and every box also carries its name and a one-line description, so the figure reads in greyscale.
The SVG is well-formed XML and scales through its viewBox.

  python python/report_workflow.py --out docs/images/workflow.svg     write the figure
  python python/report_workflow.py --check docs/images/workflow.svg   exit 1 if the file differs from what this module draws
  render_svg()                                                        the figure as a string

Standard library only.
"""
import argparse
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import report_svg as sv  # noqa: E402

# family -> (fill, stroke, name). Fill is light so dark text always reads; stroke is the saturated colour.
FAMILIES = {
    "inputs": ("#dbe9f7", "#1f5a99", "Inputs"),
    "truth": ("#d5eee8", "#0f7a68", "Truth construction"),
    "tools": ("#fbe5c8", "#a35c05", "Assembly and tools"),
    "scoring": ("#e6dcf3", "#6a3fa0", "Scoring layers"),
    "stats": ("#dcefd0", "#3b7d1e", "Statistics"),
    "output": ("#ececec", "#444444", "Recommendation and report"),
}
INK = "#1a1a1a"
FIGURE_TITLE = "PlasBench workflow: inputs, truth, tools, scoring, statistics and recommendation"

TRUTH_STEPS = [
    ("Evidence labels", "replicon, relaxase, AMR and IS evidence"),
    ("Reference tiers", "how far the reference can be trusted"),
    ("Labelling schemes", "alternative plasmid-labelling rules"),
    ("Dimer check", "corrects doubled circular plasmids"),
    ("Repeat content", "flags repeat-rich plasmids"),
    ("Depth anomalies", "truth read-depth outliers"),
]
TOOL_GROUPS = [
    ("Binning", "e.g. mob_recon, gplas2, flye_mob"),
    ("Reassembly", "e.g. plasmidSPAdes, plassembler, hybracter"),
    ("Classifiers", "e.g. platon, geNomad, PlasmidHunter"),
    ("Trivial baselines", "reference points a real tool must beat"),
    ("Optional adapters", "plsMD and PlasBin-flow output"),
]
SCORING_LAYERS = [
    ("Reference-base", "per-base recall, precision and F1 against the reference"),
    ("Contig-level", "per-contig labels with an independent k-mer cross-check"),
    ("Bin-level", "bin F1, best-match and split/join dissimilarity"),
    ("AMR placement", "is each resistance gene on the right plasmid"),
    ("Copy number", "plasmid copy-number concordance"),
    ("Assembly adequacy", "could the reads support the plasmid at all"),
]
STAT_STEPS = [
    ("Cluster bootstrap, sign-flip permutation, Wilcoxon, Holm", "paired comparisons between tools", 270),
    ("Rank robustness", "does the order survive other choices", 160),
    ("Database leakage screens", "overlap with tools' reference databases", 170),
]


def _wrap(content, width_px, size):
    """Greedy word wrap using a conservative average glyph width of 0.56 em (bold text is given a smaller width_px)."""
    per_line = max(6, int(width_px / (size * 0.56)))
    lines, current = [], ""
    for word in str(content).split():
        trial = (current + " " + word).strip()
        if len(trial) <= per_line or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _box(x, y, w, h, family, title, lines=(), title_size=12.5, size=11.5):
    fill, stroke, _ = FAMILIES[family]
    out = [f"<rect x='{sv.num(x)}' y='{sv.num(y)}' width='{sv.num(w)}' height='{sv.num(h)}' rx='10' ry='10' "
           f"fill='{fill}' stroke='{stroke}' stroke-width='2' class='wf-box'/>"]
    cy = y + 8 + title_size
    for ln in _wrap(title, w - 16, title_size * 1.08):
        out.append(sv.text(x + w / 2, cy, ln, size=title_size, anchor="middle", weight="bold", fill=INK))
        cy += title_size + 2
    for text_line in lines:
        for ln in _wrap(text_line, w - 14, size):
            out.append(sv.text(x + w / 2, cy + 2, ln, size=size, anchor="middle", fill=INK))
            cy += size + 2.5
    return "".join(out)


def _frame(x, y, w, h, family, label):
    _, stroke, _ = FAMILIES[family]
    return (f"<rect x='{sv.num(x)}' y='{sv.num(y)}' width='{sv.num(w)}' height='{sv.num(h)}' rx='14' ry='14' fill='none' "
            f"stroke='{stroke}' stroke-width='1' class='wf-frame'/>" + sv.text(x + 12, y + 17, label, size=12, weight="bold", fill=stroke))


def _arrow(x1, y1, x2, y2):
    """A line with an explicit triangular head (markers are not drawn by every SVG renderer)."""
    length = math.hypot(x2 - x1, y2 - y1) or 1.0
    ux, uy = (x2 - x1) / length, (y2 - y1) / length
    bx, by = x2 - 9 * ux, y2 - 9 * uy
    left = (bx - 4.5 * uy, by + 4.5 * ux)
    right = (bx + 4.5 * uy, by - 4.5 * ux)
    return (f"<line x1='{sv.num(x1)}' y1='{sv.num(y1)}' x2='{sv.num(bx)}' y2='{sv.num(by)}' stroke='#333' stroke-width='2'/>"
            f"<polygon points='{sv.num(x2)},{sv.num(y2)} {sv.num(left[0])},{sv.num(left[1])} {sv.num(right[0])},{sv.num(right[1])}' fill='#333'/>")


def _panel_label(y, letter, title):
    """Panel letter and title on a white backing, so a connector passing behind it never strikes through the words."""
    width = 40 + 6.6 * len(title)
    return (f"<rect x='8' y='{sv.num(y - 17)}' width='{sv.num(width)}' height='24' fill='#ffffff'/>"
            + sv.text(12, y, letter, size=18, weight="bold", fill=INK) + sv.text(32, y, title, size=13, fill=INK))


def render_svg():
    W, H = 1000, 700
    parts = [sv.svg_open(W, H, FIGURE_TITLE,
                         "A three-panel schematic of the pipeline: a, inputs and truth construction; b, short-read assembly and "
                         "the tools; c, scoring layers, statistics and the recommendation.", css_class="wf-figure"),
             f"<rect x='0' y='0' width='{W}' height='{H}' fill='#ffffff'/>"]

    # panel a ---------------------------------------------------------------------------------------------------
    parts.append(_panel_label(22, "a", "Inputs and truth"))
    parts.append(_box(20, 40, 215, 112, "inputs", "Isolate short reads", ["paired Illumina reads of one isolate"]))
    parts.append(_box(255, 40, 215, 112, "inputs", "Complete reference genome",
                      ["long-read or hybrid assembly, chromosome plus plasmids"]))
    parts.append(_frame(500, 32, 480, 150, "truth", "Truth construction"))
    for i, (label, line) in enumerate(TRUTH_STEPS):
        parts.append(_box(512 + (i % 3) * 156, 52 + (i // 3) * 60, 148, 52, "truth", label, [line], title_size=11.5, size=9.5))
    parts.append(_arrow(470, 96, 498, 96))
    parts.append(_arrow(127, 152, 127, 232))

    # panel b ---------------------------------------------------------------------------------------------------
    parts.append(_panel_label(212, "b", "Short-read assembly and tools"))
    parts.append(_box(20, 236, 215, 118, "tools", "Short-read assembly", ["trim, assemble, standardise"]))
    parts.append(_frame(255, 226, 725, 150, "tools", "Tools, grouped by class"))
    bw = (725 - 24 - 8 * (len(TOOL_GROUPS) - 1)) / len(TOOL_GROUPS)
    for i, (label, line) in enumerate(TOOL_GROUPS):
        parts.append(_box(267 + i * (bw + 8), 252, bw, 112, "tools", label, [line], title_size=12, size=10.5))
    parts.append(_arrow(235, 295, 253, 295))
    parts.append(_arrow(617, 376, 617, 404))

    # panel c ---------------------------------------------------------------------------------------------------
    parts.append(_panel_label(398, "c", "Scoring, statistics and recommendation"))
    bw = (960 - 5 * 10) / len(SCORING_LAYERS)
    for i, (label, line) in enumerate(SCORING_LAYERS):
        parts.append(_box(20 + i * (bw + 10), 406, bw, 118, "scoring", label, [line], title_size=12, size=10.5))
    parts.append(_arrow(500, 526, 500, 552))
    parts.append(_frame(20, 556, 650, 100, "stats", "Statistics"))
    sx = 30
    for label, line, w in STAT_STEPS:
        parts.append(_box(sx, 576, w, 72, "stats", label, [line], title_size=11, size=9.5))
        sx += w + 8
    parts.append(_arrow(670, 606, 700, 606))
    parts.append(_box(702, 566, 278, 80, "output", "Recommendation and report",
                      ["advisory, withheld when the evidence is thin", "one self-contained HTML report"], size=10.5))

    # legend ----------------------------------------------------------------------------------------------------
    lx, ly = 20, 672
    for key in ("inputs", "truth", "tools", "scoring", "stats", "output"):
        fill, stroke, name = FAMILIES[key]
        parts.append(f"<rect x='{lx}' y='{ly + 1}' width='12' height='12' rx='3' fill='{fill}' stroke='{stroke}' stroke-width='2'/>")
        parts.append(sv.text(lx + 18, ly + 12, name, size=11, fill=INK))
        lx += 18 + 6.4 * len(name) + 26
    parts.append(sv.svg_close())
    return "".join(parts)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--out", help="write the figure to this SVG file")
    group.add_argument("--check", help="exit 1 if this SVG file differs from the figure this module draws")
    args = ap.parse_args(argv)
    svg = render_svg() + "\n"
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(svg)
        print(f"Wrote {args.out}")
        return 0
    try:
        with open(args.check, encoding="utf-8", newline="") as handle:
            current = handle.read()
    except OSError as exc:
        print(f"cannot read {args.check}: {exc}", file=sys.stderr)
        return 1
    if current != svg:
        print(f"{args.check} is out of date; run: python python/report_workflow.py --out {args.check}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
