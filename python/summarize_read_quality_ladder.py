#!/usr/bin/env python3
"""Summarize PlasBench score rows from a deterministic read-quality-ladder
experiment (structural clone of summarize_depth_ladder.py; x-axis is
min_length, the rung's length threshold, rather than depth)."""

import argparse
import csv
import html
import statistics
from collections import defaultdict
from pathlib import Path


METRICS = ("precision", "recall", "f1", "plasmid_recall")
COLORS = ("#006d77", "#e76f51", "#457b9d", "#7b2cbf", "#588157", "#bc6c25")


def read_tsv(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def number(value, label):
    try:
        return float(value)
    except (TypeError, ValueError):
        raise SystemExit(f"ERROR: invalid numeric {label}: {value!r}")


def write_svg(summary, out, metric):
    by_tool = defaultdict(list)
    for row in summary:
        if row[metric]:
            by_tool[row["tool"]].append((number(row["min_length"], "min_length"), number(row[metric], metric)))
    if not by_tool:
        raise SystemExit(f"ERROR: no {metric} observations available for SVG")
    width, height, left, bottom, top = 960, 560, 86, 80, 48
    plot_w, plot_h = width - left - 45, height - top - bottom
    lengths = sorted({x for values in by_tool.values() for x, _ in values})
    min_x, max_x = min(lengths), max(lengths)

    def xpos(value):
        return left + plot_w / 2 if min_x == max_x else left + (value - min_x) * plot_w / (max_x - min_x)

    def ypos(value):
        return top + (1 - max(0, min(1, value))) * plot_h

    bits = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        f'<title id="title">Mean {html.escape(metric.replace("_", " "))} by read-length rung</title>',
        '<desc id="desc">Each line is a tool. Points are cohort means at deterministic filtlong-filtered read-length rungs.</desc>',
        '<rect width="100%" height="100%" fill="#fffdf7"/>',
        f'<text x="{left}" y="28" font-family="sans-serif" font-size="20" font-weight="bold" fill="#16324f">Recovery versus read-length rung</text>',
        f'<text x="{left}" y="50" font-family="sans-serif" font-size="13" fill="#4b5563">Mean {html.escape(metric.replace("_", " "))} across scored samples; deterministic filtlong filtering</text>',
    ]
    for tick in range(6):
        value, y = tick / 5, ypos(tick / 5)
        bits.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_w}" y2="{y:.1f}" stroke="#d8dee4"/>')
        bits.append(f'<text x="{left - 12}" y="{y + 4:.1f}" text-anchor="end" font-family="sans-serif" font-size="12" fill="#4b5563">{value:.1f}</text>')
    for length in lengths:
        x = xpos(length)
        bits.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + plot_h}" stroke="#edf0f2"/>')
        bits.append(f'<text x="{x:.1f}" y="{top + plot_h + 24}" text-anchor="middle" font-family="sans-serif" font-size="12" fill="#4b5563">{length:g}bp</text>')
    bits.append(f'<text x="20" y="{top + plot_h / 2:.1f}" transform="rotate(-90 20 {top + plot_h / 2:.1f})" text-anchor="middle" font-family="sans-serif" font-size="13" fill="#16324f">Mean {html.escape(metric.replace("_", " "))}</text>')
    bits.append(f'<text x="{left + plot_w / 2:.1f}" y="{height - 16}" text-anchor="middle" font-family="sans-serif" font-size="13" fill="#16324f">Rung minimum read length (bp)</text>')
    for index, (tool, values) in enumerate(sorted(by_tool.items())):
        color = COLORS[index % len(COLORS)]
        values.sort()
        points = " ".join(f"{xpos(x):.1f},{ypos(y):.1f}" for x, y in values)
        bits.append(f'<polyline fill="none" stroke="{color}" stroke-width="3" points="{points}"/>')
        for x, y in values:
            bits.append(f'<circle cx="{xpos(x):.1f}" cy="{ypos(y):.1f}" r="4" fill="{color}"><title>{html.escape(tool)}: {x:g}bp, {y:.4f}</title></circle>')
        legend_y = 80 + index * 22
        bits.append(f'<line x1="{width - 205}" y1="{legend_y}" x2="{width - 185}" y2="{legend_y}" stroke="{color}" stroke-width="3"/>')
        bits.append(f'<text x="{width - 180}" y="{legend_y + 4}" font-family="sans-serif" font-size="12" fill="#263238">{html.escape(tool)}</text>')
    bits.append('</svg>')
    Path(out).write_text("\n".join(bits) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scores", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out-prefix", required=True)
    parser.add_argument("--metric", choices=METRICS, default="f1")
    args = parser.parse_args()
    manifest = {row["sample_id"]: row for row in read_tsv(args.manifest)}
    if not manifest:
        raise SystemExit("ERROR: read-quality-ladder manifest has no rows")
    collected = defaultdict(lambda: defaultdict(list))
    for row in read_tsv(args.scores):
        source = manifest.get(row.get("sample"))
        if source is None:
            continue
        for metric in METRICS:
            if row.get(metric, ""):
                collected[(row["tool"], source["min_length"])][metric].append(number(row[metric], metric))
    if not collected:
        raise SystemExit("ERROR: none of the score samples appear in the read-quality-ladder manifest")
    output = []
    for (tool, min_length), values in sorted(collected.items(), key=lambda item: (item[0][0], number(item[0][1], "min_length"))):
        row = {"tool": tool, "min_length": f"{number(min_length, 'min_length'):g}", "n_scored": str(len(values["f1"]))}
        for metric in METRICS:
            row[metric] = f"{statistics.mean(values[metric]):.6f}" if values[metric] else ""
        output.append(row)
    prefix = Path(args.out_prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    with Path(str(prefix) + ".summary.tsv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("tool", "min_length", "n_scored", *METRICS), delimiter="\t")
        writer.writeheader(); writer.writerows(output)
    write_svg(output, str(prefix) + ".recovery.svg", args.metric)
    print(f"Wrote {prefix}.summary.tsv and {prefix}.recovery.svg")


if __name__ == "__main__":
    main()
