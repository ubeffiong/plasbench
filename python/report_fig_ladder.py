#!/usr/bin/env python3
"""
report_fig_ladder.py -- the reconstruction ladder: from contigs to a verified plasmid, and which score judges each step.

Five steps (1 sequencing contigs, 2 contig classification and binning, 3 ordering and orientation, 4 the reconstructed plasmid,
5 reference validation). Under each step the figure names the PlasBench score layer that judges it and where in the report to look.
Three distinctions are kept explicit, in the figure and in the text:

  1. contig binning is not plasmid reconstruction (right contigs in a bin says nothing about order, orientation or joins);
  2. circularity is not proof of correctness (a circular-looking reconstruction can hold wrong joins, gaps or structural errors);
  3. 3D appearance is illustrative (the plasmid is a styled genome map, not an experimentally determined conformation).

Two of them are QUANTIFIED from this run's own files when the files allow it (counts, not guesses; otherwise "not computable: reason"):

  distinction 1  (sample, tool, plasmid) triples whose plasmid was recovered as one clean bin (outcome "perfect" in
                 <tool>.plasmid_outcomes.tsv) that still carry >= 1 structural event on that plasmid in
                 <sample>/visualization/structural_calls.json;
  distinction 2  triples whose circular truth plasmid is "recovered as complete circular" (completeness >= 0.99995 in
                 <tool>.per_plasmid.tsv, truth_circular.tsv) that still carry >= 1 structural event.
  Structural events are alignment-derived and NOT validated; an event on a plasmid may be a tool error, a real rearrangement or a
  reference error. "Complete circular" in the scoring means the plasmid is covered, not that the tool closed the circle correctly.

  python python/report_fig_ladder.py --out docs/images/reconstruction_ladder.svg     write the publication figure
  python python/report_fig_ladder.py --check docs/images/reconstruction_ladder.svg   exit 1 if the file differs from this module's drawing
  render_svg(live=None)   the figure as a string (live: payload["live"]-style counts overlaid; None gives the generic figure)
  inject(page, results_dir, data_dir, scores_path)   add the section `fig-ladder` before Recommendations

The static SVG is the no-JavaScript and print fallback; the script (assets/report/fig_ladder_*.html) makes it interactive.
Standard library only.
"""
import argparse
import glob
import json
import math
import os
import re
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import report_common as rc  # noqa: E402
import report_svg as sv  # noqa: E402
from report_workflow import FAMILIES, INK, _wrap  # noqa: E402

SID = "fig-ladder"
TITLE = "From contigs to a verified plasmid: what each score judges"
FIGURE_TITLE = "From contigs to a verified plasmid: what each PlasBench score judges"
FIGURE_DESC = ("A five-step schematic. 1 Sequencing contigs. 2 Contig classification and binning. 3 Ordering and orientation. "
               "4 Reconstructed plasmid. 5 Reference validation. Under each step: the score layer that judges it. Three notes: "
               "binning is not reconstruction, circular is not correct, and 3D appearance is illustrative.")
CIRCULAR_COVERAGE = 0.99995          # score_plasmids.py: the 'complete circular' coverage threshold
SYNTHETIC_NOTE = ("The bundled demo data are synthetic and flat: counts from them demonstrate the engine, not a biological result.")

# layer id -> (glyph, label, colour). The glyph is the non-colour channel everywhere the layer is shown.
LAYERS = [
    ("input", "◐", "Input adequacy", "#555555"),
    ("contig", "●", "Contig-level layer", "#0072B2"),
    ("bin", "■", "Bin-level scores", "#CC79A7"),
    ("struct", "▲", "Structural calls (unvalidated)", "#D55E00"),
    ("ref", "◆", "Reference-base scores", "#009E73"),
    ("feat", "★", "Features and AMR", "#B07800"),
    ("truth", "▼", "Reference tiers and truth QC", "#444444"),
]
LAYER = {k: (g, lab, col) for k, g, lab, col in LAYERS}

SECTION_LABEL = {
    "learn-adequacy": "Assembly adequacy", "assembly-quality": "Assembly quality", "contig-layer": "Contig layer",
    "bin-diagnostics": "Bin diagnostics", "learn-agreement": "Bin agreement", "plasmid-outcomes": "Per-plasmid outcomes",
    "plasmid-maps": "Plasmid maps", "quast-diagnostics": "QUAST diagnostics", "scorecard": "Scorecard",
    "leaderboard": "Leaderboard", "amr-placement": "AMR placement", "feature-preservation": "Feature preservation",
    "graded-tiers": "Graded recovery", "headline-design": "Headline design", "learn-truthqc": "Truth QC",
    "label-schemes": "Labelling schemes", "per-plasmid-detail": "Per-plasmid detail", "accuracy-dimension": "Sequence accuracy",
}

# id, title, what it is, judged-by [(layer, text)], where to look [section ids]
STEPS = [
    (1, "Sequencing contigs", "Fragmented assembly output: contigs of unknown origin, in no order and no orientation.",
     [("input", "Assembly adequacy: could the reads support it"), ("input", "Assembly QC gate")],
     ["learn-adequacy", "assembly-quality"], "inputs"),
    (2, "Contig classification and binning", "Each contig goes to Plasmid A, Plasmid B, the chromosome, or stays unassigned. Nothing is joined yet.",
     [("contig", "Contig-level layer (per-contig labels)"), ("bin", "Bin-level: bin F1, best-match, split/join dissimilarity"),
      ("bin", "Per-plasmid outcome: perfect, fragmented, merged")],
     ["contig-layer", "bin-diagnostics", "learn-agreement", "plasmid-outcomes"], "truth"),
    (3, "Ordering and orientation", "Contigs of one plasmid are ordered and oriented; overlaps are trimmed, junctions closed or left unresolved.",
     [("struct", "Structural calls: junction, inversion, relocation, deletion, duplication"),
      ("struct", "NGOC, collinear fraction (alignment-derived)")],
     ["plasmid-maps", "quast-diagnostics", "feature-preservation"], "tools"),
    (4, "Reconstructed plasmid", "One sequence with annotated features (genes, replicon, AMR). It may be circular; it may still be wrong.",
     [("ref", "Reference-base recall, precision, CPRR"), ("ref", "Complete circular recall"), ("feat", "AMR placement"),
      ("feat", "Feature preservation")],
     ["scorecard", "leaderboard", "amr-placement", "feature-preservation"], "stats"),
    (5, "Reference validation", "The reconstruction is aligned to a reference plasmid: structure, completeness and features are compared.",
     [("truth", "Reference tiers: how far the reference is trusted"), ("truth", "Truth QC: repeats, depth anomalies, dimers")],
     ["headline-design", "learn-truthqc", "label-schemes"], "output"),
]

NOTES = [
    (1, "Binning is not reconstruction",
     "A tool can put the right contigs in a plasmid's bin without ordering, orienting or joining them correctly. "
     "Bin scores judge step 2 only; steps 3 to 5 need their own checks."),
    (2, "Circular is not correct",
     "A circular-looking reconstruction can still hold wrong joins, missing regions or structural errors. "
     "'Complete circular' in the scores means the plasmid is covered; it is not proof the join is right."),
    (3, "3D appearance is illustrative",
     "The ring is a styled genome map of a sequence, not an experimentally determined conformation. "
     "Any 3D view in this report plots metrics, not structure."),
]

EVENT_WORDS = (("inter_replicon_junction", "junction"), ("inversion_junction", "inversion"), ("relocation", "relocation"),
               ("reference_deletion", "deletion"), ("reference_insertion", "insertion"), ("tandem_duplication", "duplication"))


# ------------------------------------------------------------------------------------------------ data
def _median(values):
    values = sorted(v for v in values if v is not None and math.isfinite(v))
    if not values:
        return None
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def _round(v, digits=4):
    return None if v is None or not math.isfinite(v) else round(v, digits)


def _val(k, v, f="num", n="", sec="", why="", unvalidated=False, short=""):
    """One live value. v None means 'not available' (never 0); `why` says why."""
    return {"k": k, "v": _round(v) if isinstance(v, float) else v, "f": f, "n": n, "sec": sec,
            "why": why if v is None else "", "unvalidated": bool(unvalidated), "short": short or k}


def _structural(data_dir):
    """{sample: {tool: {'events': [...], 'summary': {...}}}} from <sample>/visualization/structural_calls.json."""
    out = {}
    if not data_dir or not os.path.isdir(data_dir):
        return out
    for path in sorted(glob.glob(os.path.join(data_dir, "*", "visualization", "structural_calls.json"))):
        doc = rc.read_json(path)
        if not isinstance(doc, dict) or not isinstance(doc.get("tools"), dict):
            continue
        sample = doc.get("sample") or os.path.basename(os.path.dirname(os.path.dirname(path)))
        out[sample] = {t: {"events": list(v.get("events") or []), "summary": v.get("summary") or {}} for t, v in doc["tools"].items()
                       if isinstance(v, dict)}
    return out


def _touches(event, plasmid):
    return event.get("left_target") == plasmid or event.get("right_target") == plasmid


def distinctions(data_dir):
    """The two quantified distinctions: [{id, num, den, reason, line, detail}] (den None = not computable, with the reason)."""
    structural = _structural(data_dir)
    out = []
    # 1. perfect bins that still carry an event
    num = den = pairs_without_calls = n_files = 0
    examples = []
    for sample_dir in sorted(p for p in glob.glob(os.path.join(data_dir or "", "*")) if os.path.isdir(p)):
        sample = os.path.basename(sample_dir)
        for path in sorted(glob.glob(os.path.join(sample_dir, "*.plasmid_outcomes.tsv"))):
            tool = os.path.basename(path)[:-len(".plasmid_outcomes.tsv")]
            rows = rc.read_tsv(path) or []
            n_files += 1
            calls = structural.get(sample, {}).get(tool)
            if calls is None:
                pairs_without_calls += sum(1 for r in rows if r.get("outcome") == "perfect")
                continue
            for r in rows:
                if r.get("outcome") != "perfect":
                    continue
                den += 1
                if any(_touches(e, r.get("true_plasmid")) for e in calls["events"]):
                    num += 1
                    examples.append(f"{sample}/{tool}/{r.get('true_plasmid')}")
    if not n_files:
        out.append({"id": 1, "num": None, "den": None, "reason": "no <tool>.plasmid_outcomes.tsv files (bin-level scoring was not run)",
                    "line": "", "detail": ""})
    elif not structural:
        out.append({"id": 1, "num": None, "den": None, "reason": "no structural_calls.json (alignment-derived structural events were not produced)",
                    "line": "", "detail": ""})
    elif den == 0:
        out.append({"id": 1, "num": None, "den": None, "reason": "no plasmid was recovered as one clean bin in a tool that has structural calls",
                    "line": "", "detail": ""})
    else:
        note = f" {pairs_without_calls} clean-bin plasmid(s) of tools without structural calls are left out." if pairs_without_calls else ""
        out.append({"id": 1, "num": num, "den": den, "reason": "",
                    "line": f"{num} of {den} plasmids recovered as one clean bin still carry at least one structural event.",
                    "detail": "Counted per (sample, tool, truth plasmid); an event touches a plasmid when it is called on it in the reference."
                              " Events are alignment-derived and not validated." + note, "examples": examples[:20]})
    # 2. 'complete circular' plasmids that still carry an event
    num = den = 0
    examples = []
    have_pp = have_circ = False
    for sample_dir in sorted(p for p in glob.glob(os.path.join(data_dir or "", "*")) if os.path.isdir(p)):
        sample = os.path.basename(sample_dir)
        circ = rc.read_tsv(os.path.join(sample_dir, "truth_circular.tsv"))
        if circ is None:
            continue
        have_circ = True
        circular = {r.get("sequence_id") for r in circ}
        for path in sorted(glob.glob(os.path.join(sample_dir, "*.per_plasmid.tsv"))):
            tool = os.path.basename(path)[:-len(".per_plasmid.tsv")]
            have_pp = True
            calls = structural.get(sample, {}).get(tool)
            if calls is None:
                continue
            for r in rc.read_tsv(path) or []:
                comp = rc.number(r.get("completeness"))
                if r.get("sequence_id") in circular and comp is not None and comp >= CIRCULAR_COVERAGE:
                    den += 1
                    if any(_touches(e, r.get("sequence_id")) for e in calls["events"]):
                        num += 1
                        examples.append(f"{sample}/{tool}/{r.get('sequence_id')}")
    if not have_circ:
        out.append({"id": 2, "num": None, "den": None, "reason": "no truth_circular.tsv (circular truth is not recorded)",
                    "line": "", "detail": ""})
    elif not have_pp:
        out.append({"id": 2, "num": None, "den": None, "reason": "no <tool>.per_plasmid.tsv files", "line": "", "detail": ""})
    elif not structural:
        out.append({"id": 2, "num": None, "den": None, "reason": "no structural_calls.json (alignment-derived structural events were not produced)",
                    "line": "", "detail": ""})
    elif den == 0:
        out.append({"id": 2, "num": None, "den": None, "reason": "no circular truth plasmid was recovered as complete in a tool that has structural calls",
                    "line": "", "detail": ""})
    else:
        out.append({"id": 2, "num": num, "den": den, "reason": "",
                    "line": f"{num} of {den} plasmids recovered as complete circular still carry at least one structural event.",
                    "detail": "'Complete circular' is the scoring definition (circular truth plasmid covered to 99.995% or more), "
                              "not evidence that the tool closed the circle correctly. Events are alignment-derived and not validated.",
                    "examples": examples[:20]})
    return out


def build_payload(results_dir, data_dir, scores_path):
    """Live values for each step, the two quantified distinctions and the layer/step catalogue, as one JSON-ready dict."""
    results_dir = results_dir or ""
    data_dir = data_dir or results_dir
    scores = rc.read_tsv(scores_path) or []
    board = rc.read_tsv(os.path.join(results_dir, "benchmark.leaderboard.tsv")) or []
    feat = rc.read_tsv(os.path.join(results_dir, "benchmark.feature_preservation.tsv")) or []
    tiers = rc.read_tsv(os.path.join(results_dir, "benchmark.reference_tiers.tsv")) or []
    structural = _structural(data_dir)

    def col(name):
        return [rc.number(r.get(name)) for r in board]

    tools = sorted({r.get("tool") for r in scores if r.get("tool")})
    samples = sorted({r.get("sample") for r in scores if r.get("sample")})
    def nb(name):
        k = sum(1 for v in col(name) if v is not None)
        return k
    def over(k, unit="tool"):
        return f"over {k} {unit}" + ("" if k == 1 else "s")
    no_board = "no leaderboard in this run"

    # structural
    n_events, n_pairs, n_hit, by_type, collinear = 0, 0, 0, {}, []
    for sample, tmap in structural.items():
        for tool, d in tmap.items():
            n_pairs += 1
            s = d["summary"]
            n_events += len(d["events"])
            n_hit += 1 if d["events"] else 0
            c = rc.number(s.get("collinear_fraction"))
            if c is not None:
                collinear.append(c)
            for key, word in EVENT_WORDS:
                k = rc.number(s.get(key))
                if k:
                    by_type[word] = by_type.get(word, 0) + int(k)
    no_struct = "no structural_calls.json in this run"
    circ_n = sum(int(v) for v in [rc.number(r.get("n_complete_circular_assessed")) or 0 for r in board])
    circ_vals = [rc.number(r.get("mean_complete_circular_plasmid_recall")) if (rc.number(r.get("n_complete_circular_assessed")) or 0) > 0 else None
                 for r in board]
    outcome_keys = ("perfect", "fragmented", "merged", "fragmented_and_merged", "partial", "missed")
    outcome_tot = {k: sum(rc.number(r.get(f"total_outcome_{k}")) or 0 for r in board) for k in outcome_keys}
    n_out = sum(outcome_tot.values())
    amr_t = sum(rc.number(r.get("true_amr_gene_count")) or 0 for r in scores)
    amr_r = sum(rc.number(r.get("recovered_amr_gene_count")) or 0 for r in scores)
    f_all = [r for r in feat if r.get("feature_kind") == "all"]
    f_exp = sum(rc.number(r.get("n_expected")) or 0 for r in f_all)
    f_full = sum(rc.number(r.get("n_full_length")) or 0 for r in f_all)
    truth_pl, truth_circ = {}, {}
    for r in scores:
        s = r.get("sample")
        truth_pl[s] = max(truth_pl.get(s, 0), int(rc.number(r.get("true_plasmid_count")) or 0))
        truth_circ[s] = max(truth_circ.get(s, 0), int(rc.number(r.get("true_circular_plasmid_count")) or 0))
    tier_names = sorted({r.get("reference_tier") for r in tiers if r.get("reference_tier")})

    values = {
        1: [_val("Samples scored", len(samples) if samples else None, "int", why="no scores table", sec="scorecard", short="Samples"),
            _val("Tools scored", len(tools) if tools else None, "int", why="no scores table", sec="leaderboard", short="Tools")],
        2: [_val("Median contig F1 (length-weighted)", _median(col("mean_contig_f1_bp")), n=over(nb('mean_contig_f1_bp')),
                 sec="contig-layer", why="contig layer not scored in this run", short="Contig F1, median"),
            _val("Median bin F1 (length-weighted)", _median(col("mean_lw_bin_f1")), n=over(nb('mean_lw_bin_f1')),
                 sec="bin-diagnostics", why="bin-level scores not available", short="Bin F1, median"),
            _val("Plasmids recovered as one clean bin", outcome_tot["perfect"] if n_out else None, "int",
                 n=f"of {int(n_out)} (tool, plasmid) outcomes" if n_out else "", sec="plasmid-outcomes", why="no per-plasmid outcomes")],
        3: [_val("Structural events (all tools)", n_events if structural else None, "int", sec="plasmid-maps", why=no_struct, unvalidated=True, short="Structural events"),
            _val("(sample, tool) pairs with at least one event", n_hit if structural else None, "int",
                 n=f"of {n_pairs}" if structural else "", sec="plasmid-maps", why=no_struct, unvalidated=True, short="Pairs with an event")]
        + [_val(f"{word.capitalize()} events", by_type[word], "int", sec="plasmid-maps", unvalidated=True) for _, word in EVENT_WORDS
           if by_type.get(word)]
        + [_val("Median collinear fraction", _median(collinear) if structural else None, n=over(len(collinear), "pair"),
                sec="plasmid-maps", why=no_struct, unvalidated=True)],
        4: [_val("Median CPRR", _median(col("cprr")), n=over(nb('cprr')), sec="leaderboard", why=no_board, short="CPRR, median"),
            _val("Median reference-base recall", _median(col("mean_recall")), n=over(nb('mean_recall')), sec="scorecard", why=no_board, short="Recall, median"),
            _val("Median reference-base precision", _median(col("mean_precision")), n=over(nb('mean_precision')), sec="scorecard", why=no_board),
            _val("Median complete circular recall", _median(circ_vals), n=f"{circ_n} circular-plasmid assessments", sec="scorecard",
                 why="no circular truth plasmid was assessed"),
            _val("AMR gene recall (pooled)", amr_r / amr_t if amr_t else None, "pct", n=f"{int(amr_r)} of {int(amr_t)} genes",
                 sec="amr-placement", why="no AMR truth genes"),
            _val("Annotated features kept full length (pooled)", f_full / f_exp if f_exp else None, "pct",
                 n=f"{int(f_full)} of {int(f_exp)}", sec="feature-preservation", why="feature preservation not scored")],
        5: [_val("Reference tiers present", ", ".join(tier_names) if tier_names else None, "str", sec="headline-design",
                 why="no reference-tier table", short="Tiers"),
            _val("Truth plasmids", sum(truth_pl.values()) if truth_pl else None, "int", sec="learn-truthqc", why="no scores table", short="Truth plasmids"),
            _val("Circular truth plasmids", sum(truth_circ.values()) if truth_pl else None, "int", sec="learn-truthqc", why="no scores table")],
    }
    dist = distinctions(data_dir)
    any_data = bool(scores or board or structural)
    return {
        "schema": 1, "any_data": any_data, "synthetic_note": SYNTHETIC_NOTE,
        "layers": [{"id": k, "glyph": g, "label": lab, "colour": c} for k, g, lab, c in LAYERS],
        "steps": [{"id": sid, "title": title, "what": what, "judged": [{"layer": l, "text": t} for l, t in judged],
                   "where": [{"id": s, "label": SECTION_LABEL[s]} for s in where], "values": values[sid]}
                  for sid, title, what, judged, where, _ in STEPS],
        "notes": [{"id": i, "title": t, "text": x} for i, t, x in NOTES],
        "distinctions": dist,
    }


def live_lines(payload):
    """{step: [line, ...], 'd1': line, 'd2': line} for the static overlay (two short lines per step)."""
    out = {}
    for step in payload["steps"]:
        lines = []
        for v in step["values"][:2]:
            lines.append(f"{v['short']}: " + ("not available" if v["v"] is None else _fmt(v) + (f" {v['n']}".replace("over ", "of ") if v["n"].startswith("of ") else "")))
        out[step["id"]] = lines
    for d in payload["distinctions"]:
        out[f"d{d['id']}"] = d["line"] if d["den"] else f"This run: not computable: {d['reason']}."
    return out


def _fmt(v):
    x = v["v"]
    if isinstance(x, str):
        return x
    if v["f"] == "int":
        return str(int(round(x)))
    if v["f"] == "pct":
        return f"{x * 100:.1f}%"
    return f"{x:.3f}"


# ------------------------------------------------------------------------------------------------ drawing
W, H = 1200, 768
COL_X = [40 + i * 228 for i in range(5)]
COL_W = 208
OI_BLUE, OI_ORANGE, OI_GREEN, OI_PURPLE, OI_VERM, OI_GREY = "#0072B2", "#E69F00", "#009E73", "#CC79A7", "#D55E00", "#6b6b6b"


def _n(x):
    return sv.num(x)


def _rect(x, y, w, h, fill="none", stroke="none", sw=1, rx=0, dash="", extra=""):
    d = f" stroke-dasharray='{dash}'" if dash else ""
    return (f"<rect x='{_n(x)}' y='{_n(y)}' width='{_n(w)}' height='{_n(h)}' rx='{_n(rx)}' fill='{fill}' stroke='{stroke}' "
            f"stroke-width='{_n(sw)}'{d} {extra}/>")


def _carrow(x, y, w, h, direction, fill, stroke, dash=""):
    """A contig drawn as a pentagon arrow pointing right (+1) or left (-1)."""
    hd = min(h * 0.6, w * 0.4)
    if direction > 0:
        pts = [(x, y), (x + w - hd, y), (x + w, y + h / 2), (x + w - hd, y + h), (x, y + h)]
    else:
        pts = [(x + w, y), (x + hd, y), (x, y + h / 2), (x + hd, y + h), (x + w, y + h)]
    d = f" stroke-dasharray='{dash}'" if dash else ""
    return (f"<polygon points='{' '.join(_n(a) + ',' + _n(b) for a, b in pts)}' fill='{fill}' stroke='{stroke}' "
            f"stroke-width='1.4'{d}/>")


def _t(x, y, s, size=10, anchor="start", weight="normal", fill=INK, extra=""):
    return sv.text(x, y, s, size=size, anchor=anchor, weight=weight, fill=fill, extra=extra)


def _wrapped(x, y, s, width, size, anchor="start", weight="normal", fill=INK, gap=2.2, extra=""):
    parts, cy = [], y
    for ln in _wrap(s, width, size):
        parts.append(_t(x, cy, ln, size, anchor, weight, fill, extra))
        cy += size + gap
    return "".join(parts), cy


def _badge(x, y, n):
    return (f"<circle cx='{_n(x)}' cy='{_n(y)}' r='9' fill='#7a1d16' stroke='#ffffff' stroke-width='1.5'/>"
            + _t(x, y + 3.5, str(n), 10.5, "middle", "bold", "#ffffff"))


def _draw_contigs(x):
    parts = []
    lens = [(10, 120), (46, 80), (22, 100), (96, 70), (58, 90), (112, 80)]
    for i, (off, ln) in enumerate(lens):
        y = 116 + i * 24
        parts.append(_rect(x + off, y, ln, 16, "#c9d1d8", "#4c5963", 1.3, 3))
        parts.append(_t(x + off + ln / 2, y + 11.5, f"c{i + 1}", 9.5, "middle", "bold"))
    parts.append(_t(x + 104, 272, "no order, no orientation, origin unknown", 9, "middle", fill="#444"))
    return "".join(parts)


def _draw_bins(x):
    parts = []
    spec = [("Plasmid A", "#d3e6f5", OI_BLUE, ""), ("Plasmid B", "#fbe6c2", "#b07800", ""),
            ("Chromosome", "#e2e2e2", "#555555", ""), ("Unassigned", "#ffffff", "#777777", "4 3")]
    for i, (name, fill, stroke, dash) in enumerate(spec):
        bx, by = x + 8 + (i % 2) * 100, 112 + (i // 2) * 76
        parts.append(_rect(bx, by, 92, 66, fill, stroke, 2, 7, dash))
        parts.append(_t(bx + 46, by + 14, name, 10, "middle", "bold"))
        for j in range(2 if name != "Unassigned" else 1):
            parts.append(_rect(bx + 8 + j * 4, by + 24 + j * 18, 62 - j * 4, 13, "#ffffff", stroke, 1.3, 3, dash))
            parts.append(_t(bx + 39 + j * 2, by + 34 + j * 18, ("c1", "c4") [j] if i == 0 else ("c2", "c5")[j] if i == 1
                            else ("c3", "c6")[j] if i == 2 else "c7", 8.5, "middle"))
    parts.append(_t(x + 104, 272, "contigs grouped, not yet joined", 9, "middle", fill="#444"))
    return "".join(parts)


def _draw_path(x):
    parts = []
    y1, h = 124, 20
    parts.append(_t(x + 6, 116, "assembled path", 9, fill="#444"))
    parts.append(_carrow(x + 6, y1, 74, h, 1, "#d3e6f5", OI_BLUE))
    parts.append(_t(x + 43, y1 + 14, "c1", 9, "middle", "bold"))
    parts.append(_rect(x + 72, y1 - 3, 10, h + 6, "#ffffff", "#333", 1, 0, "2 2"))          # overlap
    parts.append(_carrow(x + 78, y1, 62, h, -1, "#fbe6c2", "#b07800"))                          # inverted contig
    parts.append(_t(x + 112, y1 + 14, "c2", 9, "middle", "bold"))
    parts.append(f"<line x1='{_n(x + 140)}' y1='{_n(y1 + h / 2)}' x2='{_n(x + 160)}' y2='{_n(y1 + h / 2)}' stroke='#7a1d16' "
                 "stroke-width='2' stroke-dasharray='3 3'/>")                                      # unresolved junction
    parts.append(_t(x + 150, y1 + h / 2 + 4, "?", 12, "middle", "bold", "#7a1d16"))
    parts.append(_carrow(x + 160, y1, 38, h, 1, "#d3e6f5", OI_BLUE))
    parts.append(_t(x + 179, y1 + 14, "c4", 9, "middle", "bold"))
    for lx, ly, s, col in ((x + 77, 168, "overlap", "#333"), (x + 112, 186, "inverted", "#b07800"), (x + 150, 204, "unresolved", "#7a1d16")):
        parts.append(f"<line x1='{_n(lx)}' y1='{_n(y1 + h + 3)}' x2='{_n(lx)}' y2='{_n(ly - 10)}' stroke='{col}' stroke-width='1'/>")
        parts.append(_t(lx, ly, s, 9, "middle", "bold", col))
    y2 = 238
    parts.append(_t(x + 6, y2 - 8, "correct order and orientation", 9, fill="#444"))
    parts.append(_carrow(x + 6, y2, 60, h - 4, 1, "#eeeeee", "#777"))
    parts.append(_carrow(x + 68, y2, 66, h - 4, 1, "#eeeeee", "#777"))
    parts.append(_carrow(x + 136, y2, 62, h - 4, 1, "#eeeeee", "#777"))
    parts.append(_t(x + 104, 278, "no layer scores order directly", 9, "middle", fill="#444"))
    return "".join(parts)


def _draw_ring(x):
    parts = []
    cx, cy, r0, r1 = x + 104, 198, 38, 52
    arcs = [(0, 128, "#d3e6f5", OI_BLUE), (128, 250, "#fbe6c2", "#b07800"), (250, 360, "#d6efe7", OI_GREEN)]
    for a0, a1, fill, stroke in arcs:
        parts.append(sv.path(sv.sector_path(cx, cy, r0, r1, a0, a1 - 1.2), fill, stroke, 1.6))
    for ang in (0, 128, 250):
        x0, y0 = sv.polar(cx, cy, r0 - 4, ang)
        x1, y1 = sv.polar(cx, cy, r1 + 4, ang)
        parts.append(f"<line x1='{_n(x0)}' y1='{_n(y0)}' x2='{_n(x1)}' y2='{_n(y1)}' stroke='#222' stroke-width='2'/>")
    parts.append(sv.path(sv.arrow_path(cx, cy, r1 + 5, r1 + 17, 24, 58, True), sv.CLASS_COLOURS["amr"], "#7a2a00", 1.2))
    ax, ay = sv.polar(cx, cy, r1 + 32, 36)
    parts.append(_t(ax, ay, "AMR gene", 9.5, "start", "bold", "#7a2a00"))
    jx, jy = sv.polar(cx, cy, r1 + 14, 250)
    parts.append(f"<polygon points='{_n(jx)},{_n(jy - 7)} {_n(jx - 6)},{_n(jy + 5)} {_n(jx + 6)},{_n(jy + 5)}' fill='#7a1d16' stroke='#fff' stroke-width='1'/>")
    parts.append(_t(x + 6, jy + 26, "join to verify", 9, "start", "bold", "#7a1d16"))
    parts.append(_t(cx, cy - 2, "circular", 10, "middle", "bold"))
    parts.append(_t(cx, cy + 10, "sequence", 10, "middle"))
    parts.append(_t(x + 104, 278, "styled genome map, not a measured 3D structure", 8.6, "middle", fill="#444"))
    return "".join(parts)


def _draw_compare(x):
    parts = []
    ry, qy, h = 128, 214, 18
    parts.append(_t(x + 6, ry - 6, "Reference", 9.5, fill="#333", weight="bold"))
    parts.append(_t(x + 6, qy + h + 13, "Reconstruction", 9.5, fill="#333", weight="bold"))
    ref = [(10, 70), (80, 50), (130, 40), (170, 28)]
    for i, (a, w) in enumerate(ref):
        parts.append(_rect(x + a, ry, w - 2, h, "#dddddd", "#444", 1.4, 2))
    rec = [(10, 70, 0), (80, 50, 1), (170, 28, 0)]
    for a, w, inv in rec:
        parts.append(_rect(x + a, qy, w - 2, h, "#d3e6f5", OI_BLUE, 1.4, 2))
    parts.append(_rect(x + 130, qy, 38, h, "none", "#7a1d16", 1.4, 2, "3 3"))
    parts.append(_t(x + 149, qy + 12.5, "gap", 9, "middle", "bold", "#7a1d16"))
    # ribbons
    parts.append(f"<polygon points='{_n(x + 10)},{_n(ry + h)} {_n(x + 78)},{_n(ry + h)} {_n(x + 78)},{_n(qy)} {_n(x + 10)},{_n(qy)}' fill='#0072B2' fill-opacity='0.18'/>")
    parts.append(f"<polygon points='{_n(x + 80)},{_n(ry + h)} {_n(x + 128)},{_n(ry + h)} {_n(x + 80)},{_n(qy)} {_n(x + 128)},{_n(qy)}' fill='#E69F00' fill-opacity='0.35' stroke='#b07800' stroke-width='1'/>")
    parts.append(f"<polygon points='{_n(x + 170)},{_n(ry + h)} {_n(x + 196)},{_n(ry + h)} {_n(x + 196)},{_n(qy)} {_n(x + 170)},{_n(qy)}' fill='#0072B2' fill-opacity='0.18'/>")
    parts.append(_rect(x + 78, 163, 52, 14, "#ffffff", "#b07800", 1, 3))
    parts.append(_t(x + 104, 173.5, "inverted", 9, "middle", "bold", "#7a5200"))
    parts.append(_t(x + 44, 176, "match", 9, "middle", "bold", "#004a73"))
    parts.append(_t(x + 104, 262, "tier and truth QC set how far to trust it", 9, "middle", fill="#444"))
    parts.append(_t(x + 104, 275, "(not a validation of the reference itself)", 9, "middle", fill="#444"))
    return "".join(parts)


DRAW = [_draw_contigs, _draw_bins, _draw_path, _draw_ring, _draw_compare]
BADGES = {2: [1], 3: [1], 4: [2, 3]}


def render_svg(live=None):
    """The ladder figure. `live` (from live_lines(payload)) overlays this run's counts; None draws the generic figure."""
    parts = [sv.svg_open(W, H, FIGURE_TITLE, FIGURE_DESC, css_class="lad-figure"),
             f"<rect x='0' y='0' width='{W}' height='{H}' fill='#ffffff'/>",
             _t(40, 28, "From contigs to a verified plasmid: what each score judges", 18, weight="bold"),
             _t(40, 44, "Schematic, not data. Each step is judged by a different PlasBench score layer; a good score at one step says nothing about the next.",
                10.5, fill="#444")]
    for i, (sid, title, what, judged, where, fam) in enumerate(STEPS):
        x = COL_X[i]
        fill, stroke, _ = FAMILIES[fam]
        g = [f"<g id='lad-step-{sid}' class='lad-step' data-step='{sid}' data-layers='{' '.join(sorted({l for l, _ in judged}))}'>",
             f"<title>Step {sid}: {sv.esc(title)}</title>",
             _rect(x - 8, 56, COL_W + 16, 546, "none", "none", 3, 10, "", "class='lad-selring'"),
             _rect(x, 62, COL_W, 38, fill, stroke, 2, 8),
             f"<circle cx='{_n(x + 20)}' cy='81' r='12' fill='{stroke}'/>", _t(x + 20, 86, str(sid), 13, "middle", "bold", "#ffffff")]
        tl = _wrap(title, COL_W - 50, 11.5)[:2]
        for k, ln in enumerate(tl):
            g.append(_t(x + 40, (79 if len(tl) == 1 else 75) + k * 13 + (4 if len(tl) == 1 else 0), ln, 11.5, weight="bold"))
        g.append(_rect(x, 106, COL_W, 176, "#ffffff", stroke, 1.5, 8))
        g.append(DRAW[i](x))
        cap, _y = _wrapped(x + 2, 300, what, COL_W - 4, 10.5)
        g.append(cap)
        # judged-by panel
        g.append(_rect(x, 366, COL_W, 106, "#f4effa", FAMILIES["scoring"][1], 1.5, 8))
        g.append(_t(x + 10, 382, "Judged by", 10.5, weight="bold", fill=FAMILIES["scoring"][1]))
        for k_, n_ in enumerate(BADGES.get(sid, [])):
            g.append(_badge(x + COL_W - 14 - k_ * 22, 378, n_))
        cy = 397
        for layer, text in judged:
            glyph, _lab, colour = LAYER[layer]
            ln = _wrap(text, COL_W - 38, 10)
            g.append(f"<g class='lad-judge' data-layer='{layer}'>"
                     + _t(x + 10, cy, glyph, 10.5, weight="bold", fill=colour)
                     + "".join(_t(x + 24, cy + k * 12, s, 10) for k, s in enumerate(ln)) + "</g>")
            cy += 12 * len(ln) + 3
        # where to look
        g.append(_t(x + 2, 490, "Look in this report", 10, weight="bold", fill="#444"))
        cy = 503
        for s in where:
            g.append(_t(x + 2, cy, "› " + SECTION_LABEL[s], 10, fill="#0a5a41"))
            cy += 12
        if live:
            g.append(_rect(x, 556, COL_W, 38, "#f1f6f2", "#8fa597", 1, 6))
            cy = 569
            for ln in live.get(sid, [])[:2]:
                g.append(_t(x + 6, cy, ln, 9, fill="#14352a"))
                cy += 13
        g.append("</g>")
        parts.append("".join(g))
        if i < 4:
            ax = x + COL_W
            parts.append(f"<line x1='{_n(ax + 2)}' y1='81' x2='{_n(ax + 14)}' y2='81' stroke='#333' stroke-width='2'/>"
                         f"<polygon points='{_n(ax + 20)},81 {_n(ax + 12)},76 {_n(ax + 12)},86' fill='#333'/>")
    # the three distinctions
    parts.append(_t(40, 620, "Three distinctions this figure keeps explicit", 12, weight="bold"))
    for i, (nid, head, text) in enumerate(NOTES):
        x = 40 + i * 380
        g = [f"<g id='lad-note-{nid}' class='lad-note' data-note='{nid}'>",
             _rect(x, 628, 360, 114, "#fff8f6", "#7a1d16", 1.5, 8, "5 3"), _badge(x + 16, 646, nid),
             _t(x + 32, 650, head, 11.5, weight="bold", fill="#7a1d16")]
        body, _y = _wrapped(x + 10, 666, text, 340, 10)
        g.append(body)
        if live and f"d{nid}" in live:
            ln, _y2 = _wrapped(x + 10, 666 + 12.2 * len(_wrap(text, 340, 10)) + 10, live[f"d{nid}"], 340, 9.5, weight="bold", fill="#14352a")
            g.append(ln)
        g.append("</g>")
        parts.append("".join(g))
    # layer key
    lx = 40
    for k, glyph, label, colour in LAYERS:
        parts.append(_t(lx, 760, glyph, 10.5, weight="bold", fill=colour) + _t(lx + 14, 760, label, 9.5, fill="#333"))
        lx += 22 + 5.6 * len(label)
    parts.append(sv.svg_close())
    return "".join(parts)


# ------------------------------------------------------------------------------------------------ section
def _page_ids(page):
    return set(re.findall(r"\bid=['\"]([^'\"]+)['\"]", page))


def _static_panel(payload, ids):
    rows = []
    for step in payload["steps"]:
        for v in step["values"]:
            if v["v"] is None:
                shown = rc.missing(v["why"] or "not available", "not available")
            else:
                shown = f"{_fmt(v)} {v['n']}".strip() + (" (unvalidated)" if v["unvalidated"] else "")
            sec = v["sec"]
            link = rc.Raw(f"<a href='#{rc.esc(sec)}'>{rc.esc(SECTION_LABEL.get(sec, sec))}</a>") if sec in ids else ""
            rows.append([f"{step['id']}. {step['title']}", v["k"], shown, link])
    table = rc.panel(["Step", "Value in this run", "Result", "Where"], rows, sortable=False)
    dl = []
    for d in payload["distinctions"]:
        title = NOTES[d["id"] - 1][1]
        dl.append(f"<p><strong>{rc.esc(title)}.</strong> "
                  + (rc.esc(d["line"]) + " " + rc.esc(d["detail"]) if d["den"] else f"Not computable: {rc.esc(d['reason'])}.") + "</p>")
    return f"{table}{''.join(dl)}"


def assets():
    root = Path(__file__).resolve().parent.parent / "assets" / "report"
    return "".join((root / n).read_text(encoding="utf-8") for n in ("fig_ladder_style.html", "fig_ladder_core.html", "fig_ladder_ui.html"))


def json_script(sid, payload):
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    text = text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return f"<script type='application/json' id='{sid}'>{text}</script>"


LEAD = ("<strong>How to read it.</strong> The five steps run left to right: contigs, binning, ordering and orientation, the "
        "reconstructed plasmid, reference validation. Under each step the figure names the score layer that judges it (a "
        "shape marks each layer, so colour is never the only cue) and the report sections to open. Click a step, or press Enter on it, "
        "to see the metrics that judge it and their live values from this run in the side panel; click a layer in the key to "
        "highlight the steps it judges. Three distinctions are kept explicit. <em>Binning is not reconstruction</em>: the right contigs "
        "in a bin say nothing about order, orientation or joins. <em>Circular is not correct</em>: a circular-looking reconstruction can "
        "hold wrong joins, gaps or structural errors. <em>3D appearance is illustrative</em>: the ring is a styled genome map, not a "
        "measured conformation, and the 3D views in this report plot metrics, not structure. Structural events and NGOC are "
        "alignment-derived and unvalidated. The bundled demo data are synthetic and flat; its counts demonstrate the engine, "
        "not a biological result.")


def build_section(page, results_dir, data_dir, scores_path):
    payload = build_payload(results_dir, data_dir, scores_path)
    ids = _page_ids(page)
    for step in payload["steps"]:
        step["where"] = [w for w in step["where"] if w["id"] in ids]
    live = live_lines(payload) if payload["any_data"] else None
    svg = render_svg(live)
    banner = "" if payload["any_data"] else str(rc.not_run(
        "no scores, leaderboard or structural calls were found, so the live counts are not available; the schematic is generic"))
    host = (
        f"<div class='lad' id='lad-root'>{banner}"
        "<div class='lad-main'><div class='lad-stage'>"
        f"<div class='lad-fig'>{svg}</div><div class='lad-keybar' id='lad-key' aria-label='Score layers'></div>"
        "<div class='lad-tip' id='lad-tip' role='tooltip' hidden></div></div>"
        f"<aside class='lad-panel' id='lad-panel' aria-label='Ladder panel'><div class='lad-static'>{_static_panel(payload, ids)}</div></aside>"
        "</div>"
        "<p class='lad-limits'>Counts describe this run only. Structural events are alignment-derived and not validated; "
        "NGOC and collinear fraction are unvalidated. " + rc.esc(SYNTHETIC_NOTE) + "</p>"
        f"</div>{json_script('lad-data', payload)}")
    return rc.section(SID, TITLE, LEAD, host), assets()


def inject(page, results_dir, data_dir, scores_path):
    if f"id='{SID}'" in page:
        return page
    section, scripts = build_section(page, results_dir, data_dir, scores_path)
    return rc.inject_sections(rc.add_style(page), str(section) + scripts, [(SID, "Reconstruction ladder")])


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
        print(f"{args.check} is out of date; run: python python/report_fig_ladder.py --out {args.check}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
