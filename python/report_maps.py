#!/usr/bin/env python3
"""
report_maps.py -- CGView / Proksee-style circular plasmid maps for the PlasBench report.

One map per truth plasmid per sample. Rings, outside in:
  scale (kb ticks) | truth genes, forward strand | truth genes, reverse strand | features of unknown strand (replicon, mob, IS,
  AMR blocks) | one ring per tool (filled = truth bases covered, pale with dashed outline = not covered, black ticks = structural events) |
  GC content (deviation from the replicon mean) | GC skew (G-C)/(G+C), green positive, purple negative.
The centre names the plasmid. Position 0 is at the top, positions increase clockwise. No JavaScript: the per-tool show/hide row is a
set of checkboxes that precede the <svg> and drive generated CSS (#<map> .t<i>:not(:checked) ~ svg .ring-t<i>{display:none}).
These static maps are now the no-JavaScript and print fallback. With JavaScript the section shows ONE interactive viewer (map on the left,
tabbed control panel on the right) that re-draws the same model client-side from one JSON payload per plasmid.

Public API
  inject(page, results_dir, data_dir, scores_path)   add the `plasmid-maps` section before Recommendations (data_dir may be falsy)
  load_sample(results_dir, data_dir, sample, scores, leaderboard)  -> list of models, one per truth plasmid
  render_map(model)        -> HTML (checkbox row, svg, legend, caption) or a one-line 'not drawn' note
  render_svg(model, map_id) -> (svg, meta)
  viewer_payload(model, map_id) / viewer_config()  the JSON the interactive viewer (assets/report/plasmid_viewer_*.html) draws from
  classify_gene / gc_windows / select_tools / map_id_for   the pieces the tests exercise

File layouts accepted (first hit wins; every name may live in either tree)
  results_dir/<sample>/visualization/{alignment_blocks,structural_calls}.json
  data_dir/<sample>/ or results_dir/<sample>/ : truth_proteins.tsv truth_features.tsv truth_amr.tsv truth_circular.tsv
      truth_repeat_content.tsv truth_repeat_regions.tsv (optional) reference.fna
  results_dir/<sample>/<tool>.{per_plasmid,plasmid_outcomes,amr_placement}.tsv
  results_dir/benchmark.leaderboard.tsv (tool order), scores_path (sample / tool / analysis_track)

Standard library only.
"""
import hashlib
import json
import math
import os
import re
from pathlib import Path
from urllib.parse import quote

import report_common as rc
import report_svg as sv

MAP_MAX_TOOLS = 8
MAP_MAX_BP = 600_000
COVERAGE_GOOD = 0.90
WIDTH, HEIGHT = 1100, 900
CX, CY = WIDTH / 2.0, HEIGHT / 2.0
R_OUT = 330.0          # outer edge of the first gene ring
R_MIN = 105.0          # the centre label lives inside this radius
RING_GAP = 3.0
SECTIONS = [("plasmid-maps", "Plasmid maps")]
COVER_FILL = "#3b6ea8"
EVENT_STROKE = "#111111"
TOOL_LABEL_FONT = 8
LABEL_FONT = 10

LABEL_PRIORITY = {"amr": 100, "replication": 90, "relaxase": 80, "mobile": 70, "transfer": 50, "integrase": 40}
BASELINE_PREFIX = "baseline_"

MAP_STYLE = """
.rpt-map-body{margin:0}
.rpt-map-body>input{vertical-align:middle;margin:0 3px 0 10px}
.rpt-map-body>label{font:12px Arial,sans-serif;margin-right:6px;display:inline-block;padding:2px 0}
.rpt-map-body svg{margin-top:8px}
.rpt-map-key{display:inline-block;margin-right:14px;white-space:nowrap}
.rpt-map-key i.hatch{background:#eef1f4;border:1px dashed #7d8a97}
.rpt-map-notdrawn{font:13px Arial,sans-serif;color:var(--muted);margin:6px 0}
"""

# ------------------------------------------------------------------------------------------------------------------------------
# classification

_AMR_GENE = re.compile(r"^(bla|aac|aad|aph|ant|tet|sul|dfr|qnr|cat|mcr|erm|cml|mph|fos|arr|oqx|str[AB])[A-Za-z0-9\-\(\)'']*$", re.I)
_REP_GENE = re.compile(r"^rep[A-Z0-9_\-]?[A-Za-z0-9_\-]{0,4}$")
_TRA_GENE = re.compile(r"^(tra|trb|mob|pil|vir[BD]|ptl|mpf)[A-Za-z0-9]{0,3}$", re.I)
_MOB_GENE = re.compile(r"^(IS[A-Za-z]*\d*[A-Za-z]*|Tn\d+\w*|tnp\w*|tn[A-Z]\w*)$")
_INT_GENE = re.compile(r"^int[A-Za-z0-9]{0,2}$", re.I)
_METAL_GENE = re.compile(r"^(cus|sil|pco|mer|ars|czc|cop|cad|tcr|sco|chr)[A-Z]?[A-Za-z]?$")
_MAINT_GENE = re.compile(r"^(par[A-Z]|ccd[AB]|hok|sok|relE|relB|vap[BC]|mazEF|stb[A-Z]|pem[IK]|kis|kid|ydd[AB])$")


def classify_gene(category="", gene="", product=""):
    """Map a truth annotation to one of replication, amr, mobile, transfer, metal, integrase, maintenance, other.

    The curated `category` decides first; otherwise the gene symbol and the product text do (rep* is replication, tra*/trb*/mob*/
    conjugat* is transfer, transposase/IS*/Tn* is mobile, integrase is integrase, cus/sil/pco/mer/ars/czc or copper/silver/mercury/
    arsenic is metal, bla/aac/aad/aph/tet/sul/dfr/qnr/cat/mcr/erm is amr).
    """
    cat = (category or "").strip().lower()
    name = (gene or "").strip()
    prod = (product or "").strip().lower()
    if cat in ("amr", "resistance", "antimicrobial_resistance"):
        return "amr"
    if cat in ("replicon", "rep", "replication"):
        return "replication"
    if cat in ("conjugation", "relaxase", "mob", "mpf", "transfer", "oriT", "orit"):
        return "transfer"
    if cat in ("insertion_sequence", "is", "transposase", "mobile"):
        return "mobile"
    if cat in ("integrase", "integron"):
        return "integrase"
    if cat in ("metal", "metal_resistance", "biocide"):
        return "metal"
    if cat in ("partition", "toxin_antitoxin", "maintenance"):
        return "maintenance"
    if _AMR_GENE.match(name) or "beta-lactamase" in prod or "antibiotic resistance" in prod:
        return "amr"
    if _REP_GENE.match(name) or "replication initiation" in prod or "replicase" in prod:
        return "replication"
    if _TRA_GENE.match(name) or any(w in prod for w in ("conjugat", "relaxase", "mating pair", "type iv secretion", "pilus")):
        return "transfer"
    if _MOB_GENE.match(name) or "transposase" in prod or "insertion sequence" in prod:
        return "mobile"
    if _INT_GENE.match(name) or "integrase" in prod:
        return "integrase"
    if _METAL_GENE.match(name) or any(w in prod for w in ("copper", "silver", "mercur", "arsen", "cadmium", "zinc resistance")):
        return "metal"
    if _MAINT_GENE.match(name) or any(w in prod for w in ("partition", "toxin", "antitoxin", "addiction", "stability")):
        return "maintenance"
    return "other"


def _is_relaxase(item):
    text = f"{item.get('name', '')} {item.get('product', '')} {item.get('ftype', '')}".lower()
    return any(w in text for w in ("relaxase", "mob"))


# ------------------------------------------------------------------------------------------------------------------------------
# sequence statistics

def gc_windows(sequence, window=None):
    """GC content and GC skew per window along one replicon.

    window = max(200, length // 300) bp, so a replicon has at most ceil(length / window) windows (the last one may be short).
    Returns {'window', 'length', 'mean_gc', 'gc': [...], 'skew': [...]} where gc is the G+C fraction of each window and skew is
    (G-C)/(G+C) (0 for a window without G or C).
    """
    seq = (sequence or "").upper()
    length = len(seq)
    if length == 0:
        return {"window": 0, "length": 0, "mean_gc": 0.0, "gc": [], "skew": []}
    window = window or max(200, length // 300)
    gcs, skews = [], []
    for start in range(0, length, window):
        piece = seq[start:start + window]
        g, c = piece.count("G"), piece.count("C")
        gcs.append((g + c) / len(piece))
        skews.append((g - c) / (g + c) if g + c else 0.0)
    gc_total = (seq.count("G") + seq.count("C")) / length
    return {"window": window, "length": length, "mean_gc": gc_total, "gc": gcs, "skew": skews}


# ------------------------------------------------------------------------------------------------------------------------------
# data loading

def _first(paths):
    for path in paths:
        if path and os.path.isfile(path):
            return path
    return None


def _truth_path(results_dir, data_dir, sample, name):
    return _first([os.path.join(data_dir, sample, name) if data_dir else None, os.path.join(results_dir, sample, name)])


def _int(value, default=None):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def read_fasta_subset(path, wanted):
    """{id: sequence} for the wanted ids only (a full-genome FASTA is streamed, other records are not kept)."""
    out, name, parts = {}, None, []
    if not path or not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.strip()
            if line.startswith(">"):
                if name in wanted:
                    out[name] = "".join(parts)
                name, parts = (line[1:].split() or [""])[0], []
            elif name in wanted:
                parts.append(line)
    if name in wanted:
        out[name] = "".join(parts)
    return out


def tool_order_from(leaderboard):
    """{(track, tool): rank} from benchmark.leaderboard.tsv rows (the first row of a pair wins)."""
    ranks = {}
    for row in leaderboard or []:
        rank = rc.number(row.get("rank"))
        key = (row.get("analysis_track") or "short_read", row.get("tool", ""))
        if rank is not None and key not in ranks:
            ranks[key] = rank
    return ranks


def _overlap_fraction(a0, a1, b0, b1):
    low, high = max(a0, b0), min(a1, b1)
    shorter = max(1, min(a1 - a0, b1 - b0))
    return max(0, high - low) / shorter


def _outcome_detail(row):
    """The plasmid_outcomes.tsv row of one truth plasmid, reduced to what the viewer shows (None when the tool has no such row)."""
    if not row:
        return None
    detail = {"bin": row.get("best_bin") or "", "recall": rc.number(row.get("best_bin_recall")), "precision": rc.number(row.get("best_bin_precision")),
              "bins": _int(row.get("bins_holding_share")), "merged_with": row.get("merged_with") or "",
              "contamination": rc.number(row.get("contamination_fraction"))}
    return detail


def load_sample(results_dir, data_dir, sample, scores=None, leaderboard=None):
    """Models (one per truth plasmid) for a sample, or [] when the sample has no alignment_blocks.json."""
    viz = os.path.join(results_dir, sample, "visualization")
    blocks = rc.read_json(os.path.join(viz, "alignment_blocks.json"))
    if not blocks:
        return []
    calls = rc.read_json(os.path.join(viz, "structural_calls.json")) or {}
    tp = lambda name: _truth_path(results_dir, data_dir, sample, name)  # noqa: E731
    proteins = rc.read_tsv(tp("truth_proteins.tsv")) or []
    features = rc.read_tsv(tp("truth_features.tsv")) or []
    amr = rc.read_tsv(tp("truth_amr.tsv")) or []
    circular_rows = rc.read_tsv(tp("truth_circular.tsv"))
    repeats = rc.read_tsv(tp("truth_repeat_content.tsv")) or []
    regions = rc.read_tsv(tp("truth_repeat_regions.tsv")) or []
    if circular_rows is not None:
        circular_ids = {r.get("sequence_id") for r in circular_rows}
    elif "circular_truth_plasmids" in blocks:
        circular_ids = set(blocks["circular_truth_plasmids"])
    else:
        circular_ids = None
    ranks = tool_order_from(leaderboard)
    tracks = {}
    for row in scores or []:
        if row.get("sample") == sample:
            tracks[row.get("tool")] = row.get("analysis_track") or "short_read"
    plasmids = {pid: info for pid, info in (blocks.get("truth_plasmids") or {}).items()
                if str(info.get("molecule_type", "PLASMID")).upper() == "PLASMID"}
    sequences = read_fasta_subset(tp("reference.fna"), set(plasmids))
    models = []
    tool_data = {}
    for tool, payload in (blocks.get("tools") or {}).items():
        d = lambda name: os.path.join(results_dir, sample, f"{tool}.{name}.tsv")  # noqa: E731
        tool_data[tool] = {
            "recovery": payload.get("plasmid_recovery") or {},
            "per_plasmid": {r.get("sequence_id"): r for r in (rc.read_tsv(d("per_plasmid")) or [])},
            "outcomes": {r.get("true_plasmid"): r for r in (rc.read_tsv(d("plasmid_outcomes")) or [])},
            "amr": rc.read_tsv(d("amr_placement")),
            "events": ((calls.get("tools") or {}).get(tool) or {}).get("events") or [],
            "blocks": payload.get("blocks") or [],
            "collinear": rc.number((((calls.get("tools") or {}).get(tool) or {}).get("summary") or {}).get("collinear_fraction")),
            "order_conflicts": _int((payload.get("structural_diagnostics") or {}).get("order_conflicts")),
            "blocks_omitted": _int(payload.get("blocks_omitted"), 0) or 0,
        }
    for pid, info in plasmids.items():
        length = _int(info.get("length"), 0)
        model = {"sample": sample, "plasmid": pid, "length": length,
                 "circular": None if circular_ids is None else pid in circular_ids,
                 "repeat_rich": None, "repeat_regions": [], "genes": [], "tools": [],
                 "sequence": sequences.get(pid)}
        for row in repeats:
            if row.get("sequence_id") == pid and row.get("repeat_rich") in ("yes", "no"):
                model["repeat_rich"] = row["repeat_rich"] == "yes"
        for row in regions:
            if row.get("sequence_id") == pid and _int(row.get("start")) is not None and _int(row.get("end")) is not None:
                model["repeat_regions"].append((_int(row["start"]), _int(row["end"])))
        for row in proteins:
            if row.get("sequence_id") != pid or _int(row.get("start")) is None or _int(row.get("end")) is None:
                continue
            name = row.get("gene") or row.get("feature_id") or ""
            model["genes"].append({"start": _int(row["start"]), "end": _int(row["end"]), "strand": (row.get("strand") or "").strip(),
                                   "name": name, "product": row.get("product") or "", "kind": "gene",
                                   "cls": classify_gene(row.get("category"), name, row.get("product")), "ftype": row.get("category") or ""})
        for row in features:
            if row.get("sequence_id") != pid or _int(row.get("start")) is None or _int(row.get("end")) is None:
                continue
            ftype = row.get("feature_type") or ""
            model["genes"].append({"start": _int(row["start"]), "end": _int(row["end"]), "strand": "", "name": row.get("label") or ftype,
                                   "product": ftype, "kind": "feature",
                                   "cls": classify_gene(ftype, row.get("label"), ""), "ftype": ftype})
        for row in amr:
            if row.get("sequence_id") != pid or _int(row.get("start")) is None or _int(row.get("end")) is None:
                continue
            s, e = _int(row["start"]), _int(row["end"])
            if any(g["kind"] == "gene" and g["cls"] == "amr" and _overlap_fraction(s, e, g["start"], g["end"]) >= 0.5
                   for g in model["genes"]):
                continue
            model["genes"].append({"start": s, "end": e, "strand": "", "name": row.get("gene_name") or "AMR gene",
                                   "product": "antimicrobial resistance gene", "kind": "feature", "cls": "amr", "ftype": "amr"})
        for tool, data in tool_data.items():
            rec = (data["recovery"] or {}).get(pid) or {}
            per = data["per_plasmid"].get(pid) or {}
            comp = rc.number(per.get("completeness"))
            if comp is None:
                comp = rc.number(rec.get("completeness"))
            amr_rows = [r for r in (data["amr"] or []) if r.get("sequence_id") == pid]
            events = []
            for ev in data["events"]:
                for side, pos_key in (("left_target", "left_target_end"), ("right_target", "right_target_start")):
                    pos = _int(ev.get(pos_key))
                    if ev.get(side) == pid and pos is not None:
                        events.append({"pos": pos, "type": ev.get("event_type", "event"), "record": ev.get("record_id", ""),
                                       "detail": ev.get("detail", "")})
            model["tools"].append({
                "name": tool, "track": tracks.get(tool, "short_read"),
                "rank": ranks.get((tracks.get(tool, "short_read"), tool)),
                "intervals": [(int(a), int(b)) for a, b in (rec.get("covered_intervals") or [])],
                "completeness": comp,
                "outcome": (data["outcomes"].get(pid) or {}).get("outcome") or None,
                "amr_total": len(amr_rows) if data["amr"] is not None else None,
                "amr_recovered": [r.get("gene_name", "") for r in amr_rows if r.get("placement") == "correct_plasmid"],
                "events": events, "has_alignment": True,
                "amr_rows": [{"gene": r.get("gene_name", ""), "cls": r.get("gene_class", ""), "start": _int(r.get("start")), "end": _int(r.get("end")),
                              "placement": r.get("placement", ""), "replicon_ok": r.get("replicon_type_correct", ""),
                              "record": r.get("covering_record", ""), "bin": r.get("assigned_bin", "")} for r in amr_rows],
                "outcome_detail": _outcome_detail(data["outcomes"].get(pid)),
                "blocks": _plasmid_blocks(data["blocks"], pid), "collinear_fraction": data["collinear"],
                "order_conflicts": data["order_conflicts"], "blocks_omitted": data["blocks_omitted"],
            })
        models.append(model)
    return models


def _plasmid_blocks(blocks, pid):
    """The retained alignment blocks of one tool that land on truth plasmid `pid`, as plain dicts (identity = matches / block length)."""
    out = []
    for b in blocks or []:
        if b.get("target") != pid:
            continue
        ts, te, qs, qe = _int(b.get("target_start")), _int(b.get("target_end")), _int(b.get("query_start")), _int(b.get("query_end"))
        if None in (ts, te, qs, qe) or te <= ts:
            continue
        length = rc.number(b.get("block_length")) or 0
        matches = rc.number(b.get("matches"))
        out.append({"record": str(b.get("record_id", "")), "qlen": _int(b.get("query_length"), qe), "qs": qs, "qe": qe,
                    "strand": "-" if b.get("strand") == "-" else "+", "ts": ts, "te": te,
                    "identity": (matches / length) if (matches is not None and length > 0) else None, "mapq": _int(b.get("mapq"))})
    return out


# ------------------------------------------------------------------------------------------------------------------------------
# helpers

def _slug(text):
    return re.sub(r"[^A-Za-z0-9]+", "-", str(text)).strip("-") or "x"


def map_id_for(sample, plasmid):
    """Deterministic and unique across the page: the same plasmid id in two samples gets two ids."""
    digest = hashlib.sha1(f"{sample}\x00{plasmid}".encode("utf-8")).hexdigest()[:6]
    return f"map-{_slug(sample)}-{_slug(plasmid)}-{digest}"


def _tool_key(t):
    return (t.get("rank") if t.get("rank") is not None else 1e9, -(t.get("completeness") or 0.0), t.get("track", ""), t["name"])


def select_tools(tools, cap=MAP_MAX_TOOLS):
    """(drawn, not_drawn): best-ranked tools first, every baseline_* tool if room; the rest with the reason they were left out."""
    key = _tool_key
    baselines = sorted((t for t in tools if t["name"].startswith(BASELINE_PREFIX)), key=key)
    others = sorted((t for t in tools if not t["name"].startswith(BASELINE_PREFIX)), key=key)
    keep_others = max(min(len(others), cap // 2), cap - len(baselines))
    keep_others = min(keep_others, len(others), cap)
    drawn_others = others[:keep_others]
    drawn_base = baselines[:max(0, cap - len(drawn_others))]
    drawn = drawn_others + drawn_base
    names = {t["name"] for t in drawn}
    rest = [(t["name"], f"left out by the {cap}-tool cap on a map ({'baseline' if t['name'].startswith(BASELINE_PREFIX) else 'ranked lower'})")
            for t in sorted(tools, key=key) if t["name"] not in names]
    return drawn, rest


def _pct(value):
    return None if value is None else f"{value * 100:.0f}%"


def badge_text(tool):
    parts = [_pct(tool.get("completeness")) or "completeness n/a", tool.get("outcome") or "outcome n/a"]
    total = tool.get("amr_total")
    if total is None:
        parts.append("AMR n/a")
    elif total == 0:
        parts.append("no AMR on plasmid")
    else:
        parts.append(f"AMR {len(tool.get('amr_recovered') or [])}/{total}")
    return " | ".join(parts)


def _clean(value):
    return rc.esc(value)


def _mid_angle(start, end, length):
    pieces = sv.split_wrapped(start, end, length)
    if not pieces:
        return None
    s, e = max(pieces, key=lambda p: p[1] - p[0])
    return sv.bp_to_deg((s + e) / 2.0, length)


def _shaft(r_in, r_out, a0, a1):
    mid, half = (r_in + r_out) / 2.0, (r_out - r_in) / 2.0
    return sv.sector_path(CX, CY, mid - half * 0.62, mid + half * 0.62, a0, a1)


def _ring_bounds(spec, scale):
    """[(name, r_in, r_out)] from the outside: spec is [(name, height)]."""
    out, r = {}, R_OUT
    for name, height in spec:
        h = height * scale
        out[name] = (r - h, r)
        r -= h + RING_GAP * scale
    return out


def _gene_title(g):
    strand = {"+": "forward strand", "-": "reverse strand"}.get(g["strand"], "strand not given")
    label = g["name"] or g["product"] or "feature"
    prod = f" ({g['product']})" if g.get("product") and g["product"] != label else ""
    return f"{label}{prod}: {sv.CLASS_LABELS.get(g['cls'], g['cls'])}, {strand}, {g['start']}-{g['end']} bp"


def _ring_name(text, r_mid, size=TOOL_LABEL_FONT):
    x, y = CX - 4, CY - r_mid + size * 0.35
    return (sv.text(x, y, text, size, "end", "normal", "#fff", "stroke='#fff' stroke-width='2.6' stroke-linejoin='round'")
            + sv.text(x, y, text, size, "end", "normal", "#222"))


# ------------------------------------------------------------------------------------------------------------------------------
# svg

def render_svg(model, map_id):
    """(svg, meta). meta: classes (present), dropped_labels, labelled, tools_drawn, tools_not_drawn, gc, notes."""
    length = int(model["length"])
    genes = model.get("genes") or []
    drawn, not_drawn = select_tools(model.get("tools") or [])
    fwd = [g for g in genes if g["strand"] == "+"]
    rev = [g for g in genes if g["strand"] == "-"]
    blocks = [g for g in genes if g["strand"] not in ("+", "-")]
    seq = model.get("sequence")
    gc = gc_windows(seq) if seq else None
    notes = []
    spec = [("fwd", 18), ("rev", 18)]
    if blocks:
        spec.append(("feat", 12))
    spec += [(f"t{i}", 13) for i in range(len(drawn))]
    if gc:
        spec += [("gc", 22), ("skew", 22)]
    else:
        notes.append("GC content and GC skew are not drawn: no reference sequence for this plasmid.")
    needed = sum(h for _, h in spec) + RING_GAP * (len(spec) - 1)
    scale = min(1.0, (R_OUT - R_MIN) / needed)
    rings = _ring_bounds(spec, scale)
    title = f"Circular map of {model['plasmid']} ({length:,} bp) in {model['sample']}"
    desc = (f"{len(genes)} truth annotations and {len(drawn)} tool rings; position 0 at the top, clockwise. "
            "Outer ring forward strand, next ring reverse strand.")
    out = [sv.svg_open(WIDTH, HEIGHT, title, desc, css_class="rpt-plasmid-map")]
    out.append(f"<rect x='0' y='0' width='{WIDTH}' height='{HEIGHT}' fill='#ffffff'/>")

    # scale
    step, ticks = sv.nice_ticks(length)
    tick_boxes = []
    r_tick_in, r_tick_out = R_OUT + 10, R_OUT + 16
    out.append(f"<g class='scale'><circle cx='{sv.num(CX)}' cy='{sv.num(CY)}' r='{sv.num(R_OUT + 10)}' fill='none' stroke='#999' stroke-width='0.8'/>")
    for pos in ticks:
        ang = sv.bp_to_deg(pos, length)
        x1, y1 = sv.polar(CX, CY, r_tick_in, ang)
        x2, y2 = sv.polar(CX, CY, r_tick_out, ang)
        out.append(sv.line(x1, y1, x2, y2, "#555", 1))
        lx, ly = sv.polar(CX, CY, r_tick_out + 5, ang)
        anchor = "middle" if (ang < 12 or ang > 348 or 168 < ang < 192) else ("start" if lx >= CX else "end")
        ly += 3 if not (ang < 12 or ang > 348) else -2
        ly += 7 if 168 < ang < 192 else 0
        label = sv.kb_label(pos)
        out.append(sv.text(lx, ly, label, 9, anchor, "normal", "#444"))
        tick_boxes.append(sv.text_box(label, 9, lx, ly, anchor))
    out.append("</g>")

    # truth genes
    present = []

    def mark(cls):
        if cls not in present:
            present.append(cls)

    def draw_gene(g, ring):
        r_in, r_out = rings[ring]
        colour = sv.CLASS_COLOURS[g["cls"]]
        mark(g["cls"])
        pieces = sv.split_wrapped(g["start"], g["end"], length)
        shapes = []
        for k, (s, e) in enumerate(pieces):
            a0, a1 = sv.bp_to_deg(s, length), e / length * 360.0
            if a1 - a0 < 0.5:
                a1 = a0 + 0.5
            if ring == "feat":
                d = sv.sector_path(CX, CY, r_in, r_out, a0, a1)
            else:
                forward = g["strand"] == "+"
                wrapped = len(pieces) == 2
                has_head = (not wrapped) or (forward and k == len(pieces) - 1) or ((not forward) and k == 0)
                d = sv.arrow_path(CX, CY, r_in, r_out, a0, a1, forward) if has_head else _shaft(r_in, r_out, a0, a1)
            shapes.append(sv.path(d, colour, "#222", 0.5, _gene_title(g), f"class='gene' data-class='{g['cls']}' data-name='{rc.esc(g['name'])}'"))
        return "".join(shapes)

    for name, label_text, members in (("fwd", "+ strand", fwd), ("rev", "- strand", rev), ("feat", "features", blocks)):
        if name not in rings:
            continue
        r_in, r_out = rings[name]
        out.append(f"<g class='ring-genes ring-{name}'><title>{rc.esc(label_text)} annotations of the truth</title>"
                   f"<circle cx='{sv.num(CX)}' cy='{sv.num(CY)}' r='{sv.num((r_in + r_out) / 2)}' fill='none' stroke='#e2e2e2' stroke-width='{sv.num(r_out - r_in)}'/>")
        out.append("".join(draw_gene(g, name) for g in members))
        out.append(_ring_name(label_text, (r_in + r_out) / 2) + "</g>")

    # repeat regions (only when the data gives coordinates)
    if model.get("repeat_regions"):
        r_in, r_out = rings["fwd"][1] + 2, R_OUT + 8
        parts = []
        for s, e in model["repeat_regions"]:
            for ps, pe in sv.split_wrapped(s, e, length):
                parts.append(sv.sector_path(CX, CY, r_in, r_out, sv.bp_to_deg(ps, length), pe / length * 360.0))
        out.append(sv.path("".join(parts), "#bbbbbb", "none", 0, f"Repeat-rich regions of {model['plasmid']}", "opacity='0.45' class='repeat-regions'"))

    # tool rings
    for i, tool in enumerate(drawn):
        r_in, r_out = rings[f"t{i}"]
        cov = []
        for s, e in tool.get("intervals") or []:
            s, e = max(0, int(s)), min(length, int(e))
            if e <= s:
                continue
            a0, a1 = sv.bp_to_deg(s, length), e / length * 360.0
            cov.append(sv.path(sv.sector_path(CX, CY, r_in, r_out, a0, a1), COVER_FILL, "#12355b", 0.6,
                               f"{tool['name']}: truth bases {s}-{e} covered ({e - s:,} bp)",
                               f"class='cov' data-start='{s}' data-end='{e}' data-a0='{sv.num(a0, 3)}' data-a1='{sv.num(a1, 3)}'"))
        comp = _pct(tool.get("completeness")) or "n/a"
        out.append(f"<g class='ring-t{i}' data-tool='{rc.esc(tool['name'])}'><title>{rc.esc(tool['name'])}: completeness {comp}, "
                   f"{rc.esc(tool.get('outcome') or 'outcome n/a')}</title>"
                   + sv.path(sv.ring_path(CX, CY, r_in, r_out), "#eef1f4", "#7d8a97", 0.7,
                             tool["name"] + ": not covered (pale, dashed outline)", "class='uncov' stroke-dasharray='3 2'") + "".join(cov))
        for ev in tool.get("events") or []:
            ang = sv.bp_to_deg(ev["pos"], length)
            x1, y1 = sv.polar(CX, CY, r_in - 1.5, ang)
            x2, y2 = sv.polar(CX, CY, r_out + 1.5, ang)
            out.append(sv.line(x1, y1, x2, y2, EVENT_STROKE, 2.2,
                               f"class='event' data-pos='{ev['pos']}'")[:-2] + f"><title>{rc.esc(tool['name'])}: {rc.esc(ev['type'])} at {ev['pos']:,} bp "
                       f"(record {rc.esc(ev['record'])})</title></line>")
        out.append(_ring_name(tool["name"][:18], (r_in + r_out) / 2) + "</g>")

    # GC content and skew
    if gc:
        glen = gc["length"]
        window = gc["window"]
        dev = [v - gc["mean_gc"] for v in gc["gc"]]
        r_in, r_out = rings["gc"]
        base, half = (r_in + r_out) / 2.0, (r_out - r_in) / 2.0
        top = max(max((abs(v) for v in dev), default=0.0), 0.01)
        plus, minus = [], []
        for k, v in enumerate(dev):
            a0, a1 = k * window / glen * 360.0, min(glen, (k + 1) * window) / glen * 360.0
            h = half * min(1.0, abs(v) / top)
            if h < 0.05:
                continue
            (plus if v > 0 else minus).append(sv.sector_path(CX, CY, base, base + h, a0, a1) if v > 0 else sv.sector_path(CX, CY, base - h, base, a0, a1))
        out.append(f"<g class='ring-gc'><circle cx='{sv.num(CX)}' cy='{sv.num(CY)}' r='{sv.num(base)}' fill='none' stroke='#bbb' stroke-width='0.5'/>"
                   + sv.path("".join(plus + minus), "#000000", "none", 0,
                             f"GC content: deviation from the replicon mean of {gc['mean_gc'] * 100:.1f}% in {len(dev)} windows of {window} bp",
                             "class='gc-bars'") + _ring_name("GC", base) + "</g>")
        r_in, r_out = rings["skew"]
        base, half = (r_in + r_out) / 2.0, (r_out - r_in) / 2.0
        top = max(max((abs(v) for v in gc["skew"]), default=0.0), 0.01)
        pos_d, neg_d = [], []
        for k, v in enumerate(gc["skew"]):
            a0, a1 = k * window / glen * 360.0, min(glen, (k + 1) * window) / glen * 360.0
            h = half * min(1.0, abs(v) / top)
            if h < 0.05:
                continue
            (pos_d if v > 0 else neg_d).append(sv.sector_path(CX, CY, base, base + h, a0, a1) if v > 0
                                               else sv.sector_path(CX, CY, base - h, base, a0, a1))
        out.append(f"<g class='ring-skew'><circle cx='{sv.num(CX)}' cy='{sv.num(CY)}' r='{sv.num(base)}' fill='none' stroke='#bbb' stroke-width='0.5'/>"
                   + sv.path("".join(pos_d), "#009E73", "none", 0, "GC skew (G-C)/(G+C) positive: G-rich windows", "class='skew-pos'")
                   + sv.path("".join(neg_d), "#8e4ba0", "none", 0, "GC skew (G-C)/(G+C) negative: C-rich windows", "class='skew-neg'")
                   + _ring_name("skew", base) + "</g>")

    # labels
    items, taken = [], []
    cands = sorted(genes, key=lambda g: (0 if g["kind"] == "feature" else 1, g["start"]))
    for g in cands:
        relax = _is_relaxase(g) and g["cls"] == "transfer"
        always = g["cls"] in ("amr", "replication", "mobile") or relax
        if not (always or g["cls"] in ("transfer", "integrase")):
            continue
        if not g["name"]:
            continue
        if any(t["cls"] == g["cls"] and _overlap_fraction(g["start"], g["end"], t["start"], t["end"]) >= 0.5 for t in taken):
            continue
        taken.append(g)
        ang = _mid_angle(g["start"], g["end"], length)
        if ang is None:
            continue
        ring = "feat" if g["strand"] not in ("+", "-") else ("fwd" if g["strand"] == "+" else "rev")
        prio = LABEL_PRIORITY["relaxase"] if relax else LABEL_PRIORITY.get(g["cls"], 10)
        items.append({"angle": ang, "text": g["name"], "priority": prio, "cls": g["cls"], "r_out": rings[ring][1], "gene": g})
    r_base = R_OUT + 34
    placed, dropped = sv.place_labels(items, CX, CY, r_base, LABEL_FONT, WIDTH, HEIGHT, levels=5, level_step=LABEL_FONT * 1.45,
                                      avoid=tick_boxes)
    out.append("<g class='gene-labels'>")
    for p in placed:
        (fx, fy), (lx, ly) = p["leader"]
        sx, sy = sv.polar(CX, CY, p["r_out"] + 1, p["angle"])
        out.append(f"<polyline points='{sv.num(sx)},{sv.num(sy)} {sv.num(fx)},{sv.num(fy)} {sv.num(lx)},{sv.num(ly)}' fill='none' "
                   f"stroke='#777' stroke-width='0.6'/>")
        out.append(sv.text(p["x"], p["y"], p["text"], LABEL_FONT, p["anchor"], "bold" if p["cls"] == "amr" else "normal",
                           sv.CLASS_COLOURS[p["cls"]] if p["cls"] != "other" else "#333",
                           f"class='gene-label' data-name='{rc.esc(p['text'])}'"))
    out.append("</g>")

    # centre
    n_ok = sum(1 for t in model.get("tools") or [] if (t.get("completeness") or 0) >= COVERAGE_GOOD)
    n_all = len(model.get("tools") or [])
    circ = {True: "yes", False: "no", None: "unknown"}[model.get("circular")]
    rep = {True: "yes", False: "no", None: "unknown"}[model.get("repeat_rich")]
    pid = str(model["plasmid"])
    pid_size = 20 if len(pid) <= 14 else max(10, int(260 / (len(pid) * 0.6)))
    out.append(f"<g class='centre'><title>{rc.esc(pid)}: {length:,} bp, circular {circ}, repeat-rich {rep}, "
               f"{n_ok} of {n_all} tools at or above {int(COVERAGE_GOOD * 100)}% completeness</title>")
    out.append(sv.text(CX, CY - 28, pid, pid_size, "middle", "bold", "#111"))
    out.append(sv.text(CX, CY - 6, f"{length:,} bp", 14, "middle", "normal", "#222"))
    out.append(sv.text(CX, CY + 14, f"circular: {circ}", 12, "middle", "normal", "#222"))
    out.append(sv.text(CX, CY + 30, f"repeat-rich: {rep}", 12, "middle", "normal", "#222"))
    out.append(sv.text(CX, CY + 46, f"{n_ok} of {n_all} tools >= {int(COVERAGE_GOOD * 100)}%", 12, "middle", "normal", "#222"))
    out.append("</g>")
    out.append(sv.svg_close())
    meta = {"classes": [c for c in sv.CLASS_COLOURS if c in present], "dropped_labels": [d["text"] for d in dropped],
            "labelled": [p["text"] for p in placed], "placed": placed, "tools_drawn": [t["name"] for t in drawn],
            "tools_not_drawn": not_drawn, "gc": gc, "notes": notes, "n_ok": n_ok, "n_all": n_all, "rings": rings,
            "n_gene_shapes": sum(1 for g in genes for _ in sv.split_wrapped(g["start"], g["end"], length))}
    return "".join(out), meta


# ------------------------------------------------------------------------------------------------------------------------------
# html around one map

def _legend(meta):
    keys = []
    for cls in meta["classes"]:
        keys.append(f"<span class='rpt-map-key' data-class='{cls}'><i style='background:{sv.CLASS_COLOURS[cls]}'></i>{rc.esc(sv.CLASS_LABELS[cls])}</span>")
    keys.append(f"<span class='rpt-map-key'><i style='background:{COVER_FILL}'></i>Tool ring: truth bases covered (solid)</span>")
    keys.append("<span class='rpt-map-key'><i class='hatch'></i>Tool ring: not covered (pale, dashed outline)</span>")
    keys.append("<span class='rpt-map-key'><i style='background:#111;width:3px'></i>Structural event on this plasmid</span>")
    if meta["gc"]:
        keys.append("<span class='rpt-map-key'><i style='background:#000'></i>GC deviation</span>")
        keys.append("<span class='rpt-map-key'><i style='background:#009E73'></i>GC skew +</span>"
                    "<span class='rpt-map-key'><i style='background:#8e4ba0'></i>GC skew -</span>")
    return "<div class='rpt-legend'>" + "".join(keys) + "</div>"


def render_map(model, map_id=None):
    """HTML for one plasmid: toggle row, svg, legend and caption; or a one-line 'not drawn' note."""
    length = model.get("length") or 0
    ident = map_id or map_id_for(model["sample"], model["plasmid"])
    who = f"{model['sample']} / {model['plasmid']}"
    if length <= 0:
        return f"<p class='rpt-map-notdrawn' id='{ident}'>Not drawn: {rc.esc(who)} has no length in the truth table.</p>"
    if length > MAP_MAX_BP:
        return (f"<p class='rpt-map-notdrawn' id='{ident}'>Not drawn: {rc.esc(who)} is {length:,} bp, over the "
                f"{MAP_MAX_BP:,} bp limit for a plasmid map.</p>")
    svg, meta = render_svg(model, ident)
    drawn = meta["tools_drawn"]
    tool_by_name = {t["name"]: t for t in model.get("tools") or []}
    row = []
    for i, name in enumerate(drawn):
        cid = f"{ident}-c{i}"
        row.append(f"<input type='checkbox' class='t{i}' id='{cid}' checked><label for='{cid}'><strong>{rc.esc(name)}</strong> "
                   f"<span class='muted'>{rc.esc(badge_text(tool_by_name[name]))}</span></label>")
    caption = []
    if meta["dropped_labels"]:
        caption.append("Labels that did not fit and are not drawn: " + ", ".join(sorted(set(meta["dropped_labels"]))) + ".")
    if meta["tools_not_drawn"]:
        caption.append("Tools not drawn: " + "; ".join(f"{n} ({why})" for n, why in meta["tools_not_drawn"]) + ".")
    caption += meta["notes"]
    if model.get("repeat_rich") and not model.get("repeat_regions"):
        caption.append("This plasmid is repeat-rich; the data give no coordinates for the repeats, so they are not shaded.")
    if not model.get("genes"):
        caption.append("No truth annotation is available for this plasmid.")
    css = "".join(f"#{ident} .t{i}:not(:checked) ~ svg .ring-t{i}{{display:none}}" for i in range(len(drawn)))
    return (f"<figure class='rpt-figure'><style>{css}</style><div class='rpt-map-body' id='{ident}'>{''.join(row)}{svg}</div>"
            f"{_legend(meta)}<figcaption>{rc.esc(' '.join(caption))}</figcaption></figure>")


# ------------------------------------------------------------------------------------------------------------------------------
# interactive viewer: payload, configuration and assets

VIEWER_BUDGET_BYTES = 1_500_000      # all plasmid payloads together; the whole report budget is build_html_report.INLINE_VISUALIZATION_BUDGET
VIEWER_ASSETS = ("plasmid_viewer_style.html", "plasmid_viewer_core.html", "plasmid_viewer_align.html", "plasmid_viewer_ui.html")
# Colour-blind-safe alternative (Okabe-Ito and Tol), switched on with the report's palette toggle or in the viewer's Appearance tab.
CVD_COLOURS = {"replication": "#332288", "amr": "#D55E00", "mobile": "#88CCEE", "transfer": "#0072B2", "metal": "#DDCC77",
               "integrase": "#CC79A7", "maintenance": "#117733", "other": "#999999", "cover": "#0072B2", "skewPos": "#0072B2", "skewNeg": "#D55E00"}


def viewer_asset(name):
    """A viewer fragment from assets/report/ (style, pure core, DOM glue)."""
    path = Path(__file__).resolve().parent.parent / "assets" / "report" / name
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def json_for_script(obj):
    """Compact JSON that is safe inside <script type='application/json'> (no '</script', no '<!--', no raw line separators)."""
    text = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    return (text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def viewer_config():
    """Constants the browser needs so its geometry matches this module: canvas, ring radii, fonts, classes, palettes, label priority."""
    default = dict(sv.CLASS_COLOURS)
    default.update({"cover": COVER_FILL, "skewPos": "#009E73", "skewNeg": "#8e4ba0"})
    return {"core": {"W": WIDTH, "H": HEIGHT, "R_OUT": R_OUT, "R_MIN": R_MIN, "GAP": RING_GAP, "TOOL_LABEL_FONT": TOOL_LABEL_FONT,
                     "LABEL_FONT": LABEL_FONT, "COVERAGE_GOOD": COVERAGE_GOOD, "COVER_FILL": COVER_FILL, "EVENT_STROKE": EVENT_STROKE,
                     "MAX_TOOLS": MAP_MAX_TOOLS, "classes": list(sv.CLASS_COLOURS), "labels": dict(sv.CLASS_LABELS),
                     "palettes": {"default": default, "cvd": dict(CVD_COLOURS)}, "priority": dict(LABEL_PRIORITY)},
            "maxBp": MAP_MAX_BP}


def _display_name(tool):
    """The reader-facing tool name used elsewhere in the report (MOB-like for mob_like); the id stays the key."""
    try:
        from plasbench_common import display_tool_name
        return display_tool_name(tool)
    except ImportError:
        return tool


def _r(value, digits):
    return None if value is None else round(value, digits)


VIEWER_MAX_BLOCKS = 300     # alignment blocks kept per tool and plasmid in the viewer payload (the longest ones; the rest are counted, not drawn)


def _payload_blocks(blocks):
    """[[record, query length, query start, query end, strand, ref start, ref end, identity (4 dp) or null, mapq or null]] longest first, in reference order."""
    keep = sorted(blocks, key=lambda b: (-(b["te"] - b["ts"]), b["ts"]))[:VIEWER_MAX_BLOCKS]
    keep.sort(key=lambda b: (b["ts"], b["te"], b["record"]))
    return [[b["record"], b["qlen"], b["qs"], b["qe"], b["strand"], b["ts"], b["te"], _r(b.get("identity"), 4), b.get("mapq")] for b in keep]


def viewer_payload(model, map_id=None):
    """The model of one plasmid as compact JSON-ready data (short keys; the viewer's PV.normalize expands them).

    id, sample, plasmid, length, circ (bool, absent when unknown), rr (repeat-rich), rg [[start,end]] repeat regions,
    genes [{s,e,t strand,n name,p product,c class,k kind,f ftype}], tools [{n,dn display name (when it differs),tr track,rk rank,cm completeness,oc outcome,iv [[a,b]],
    at AMR total,ar AMR recovered names,ev [{p,t,r,d}],bl alignment blocks [[record,qlen,qs,qe,strand,ref start,ref end,identity,mapq]],
    bo blocks not sent,cf collinear fraction (tool-wide, structural_calls.json),oc order conflicts,am [{g,c,s,e,pl,rc,r,b}],od outcome detail {b,r,p,n,m,c},d 1 = drawn by default}],
    gc {w window,m mean,g [GC per window],k [skew per window]}. Every tool is included (the static map caps at MAP_MAX_TOOLS; the
    viewer starts with the same tools switched on and lets the reader switch the others on).
    """
    ident = map_id or map_id_for(model["sample"], model["plasmid"])
    drawn, rest = select_tools(model.get("tools") or [])
    drawn_names = {t["name"] for t in drawn}
    out = {"id": ident, "sample": model["sample"], "plasmid": model["plasmid"], "length": int(model["length"])}
    if model.get("circular") is not None:
        out["circ"] = bool(model["circular"])
    if model.get("repeat_rich") is not None:
        out["rr"] = bool(model["repeat_rich"])
    if model.get("repeat_regions"):
        out["rg"] = [[int(a), int(b)] for a, b in model["repeat_regions"]]
    genes = []
    for g in model.get("genes") or []:
        item = {"s": int(g["start"]), "e": int(g["end"]), "c": g["cls"]}
        for key, field in (("t", "strand"), ("n", "name"), ("p", "product"), ("f", "ftype")):
            if g.get(field):
                item[key] = g[field]
        if g.get("kind") == "feature":
            item["k"] = "feature"
        genes.append(item)
    out["genes"] = genes
    tools = []
    for t in sorted(model.get("tools") or [], key=_tool_key):
        item = {"n": t["name"], "tr": t.get("track", ""), "iv": [[int(a), int(b)] for a, b in t.get("intervals") or []]}
        if _display_name(t["name"]) != t["name"]:
            item["dn"] = _display_name(t["name"])
        if t.get("rank") is not None:
            item["rk"] = t["rank"]
        if t.get("completeness") is not None:
            item["cm"] = _r(t["completeness"], 4)
        if t.get("outcome"):
            item["oc"] = t["outcome"]
        if t.get("amr_total") is not None:
            item["at"] = t["amr_total"]
        if t.get("amr_recovered"):
            item["ar"] = list(t["amr_recovered"])
        if t.get("events"):
            item["ev"] = [{"p": int(e["pos"]), "t": e.get("type", "event"), "r": e.get("record", ""), "d": str(e.get("detail", ""))[:240]} for e in t["events"]]
        if t.get("amr_rows"):
            item["am"] = [{k: v for k, v in (("g", a.get("gene")), ("c", a.get("cls")), ("s", a.get("start")), ("e", a.get("end")), ("pl", a.get("placement")),
                                             ("rc", a.get("replicon_ok")), ("r", a.get("record")), ("b", a.get("bin"))) if v not in (None, "")}
                          for a in t["amr_rows"]]
        od = t.get("outcome_detail")
        if od:
            item["od"] = {k: v for k, v in (("b", od.get("bin")), ("r", _r(od.get("recall"), 4)), ("p", _r(od.get("precision"), 4)), ("n", od.get("bins")),
                                           ("m", od.get("merged_with")), ("c", _r(od.get("contamination"), 4))) if v not in (None, "")}
        if t.get("blocks"):
            item["bl"] = _payload_blocks(t["blocks"])
            if len(t["blocks"]) > VIEWER_MAX_BLOCKS:
                item["bo"] = len(t["blocks"]) - VIEWER_MAX_BLOCKS
        if t.get("collinear_fraction") is not None:
            item["cf"] = _r(t["collinear_fraction"], 5)
        if t.get("order_conflicts") is not None:
            item["oc"] = t["order_conflicts"]
        if t["name"] in drawn_names:
            item["d"] = 1
        tools.append(item)
    out["tools"] = tools
    if rest:
        out["nd"] = [name for name, _ in rest]
    gc = gc_windows(model["sequence"]) if model.get("sequence") else None
    if gc:
        out["gc"] = {"w": gc["window"], "m": round(gc["mean_gc"], 5), "g": [round(v, 4) for v in gc["gc"]], "k": [round(v, 3) for v in gc["skew"]]}
    else:
        out["notes"] = ["GC content and GC skew are not drawn: no reference sequence for this plasmid."]
    return out


def viewer_script_blocks(payloads):
    """<script type='application/json'> blocks: one config and one payload per plasmid (id pv-data-<map id>)."""
    parts = [f"<script type='application/json' id='pv-config'>{json_for_script(viewer_config())}</script>"]
    for payload in payloads:
        parts.append(f"<script type='application/json' class='pv-data' id='pv-data-{rc.esc(payload['id'])}'>{json_for_script(payload)}</script>")
    return "".join(parts)


def viewer_open_link(sample, plasmid):
    return f"#plasmid-maps?msample={quote(str(sample), safe='')}&mplasmid={quote(str(plasmid), safe='')}"


# ------------------------------------------------------------------------------------------------------------------------------
# section

def _samples_in(results_dir):
    if not results_dir or not os.path.isdir(results_dir):
        return []
    return sorted(d for d in os.listdir(results_dir)
                  if os.path.isfile(os.path.join(results_dir, d, "visualization", "alignment_blocks.json")))


LEAD = ("One interactive circular map per truth plasmid. Choose a sample and plasmid, or click a thumbnail. Hover or focus any gene, tool ring, "
        "structural event or GC window for its details; click it (or press Enter) to open the Detail tab with the tools that cover it, AMR placement, "
        "neighbours and overlapping events. Scroll to zoom to the cursor, drag to rotate, search a gene to fly to it. The side panel holds the layers, "
        "filters, and the tool, feature and event tables of the plasmid on show, and exports SVG, PNG and TSV. "
        "The outer rings are the truth annotation by strand; each tool then gets a ring that is filled where it recovered the truth and pale with a dashed "
        "outline where it did not, with black ticks at structural events. Without JavaScript the static maps at the end of this section are shown instead.")


def build_section(results_dir, data_dir, scores_path):
    samples = _samples_in(results_dir)
    if not samples:
        return rc.section("plasmid-maps", "Plasmid maps", LEAD,
                          rc.not_run("no <sample>/visualization/alignment_blocks.json was found under the results directory."))
    scores = rc.read_tsv(scores_path) or []
    leaderboard = rc.read_tsv(os.path.join(results_dir, "benchmark.leaderboard.tsv")) or []
    gallery, blocks_html, payloads, spent = [], [], [], 0
    for index, sample in enumerate(samples):
        models = load_sample(results_dir, data_dir, sample, scores, leaderboard)
        parts = []
        for model in models:
            ident = map_id_for(model["sample"], model["plasmid"])
            drawable = 0 < model["length"] <= MAP_MAX_BP
            payload = None
            if drawable:
                candidate = viewer_payload(model, ident)
                size = len(json_for_script(candidate))
                if spent + size <= VIEWER_BUDGET_BYTES:
                    payload, spent = candidate, spent + size
                    payloads.append(payload)
            flag = " data-pv='1'" if payload else ""
            parts.append(f"<div class='pv-static'{flag}>{render_map(model, ident)}</div>")
            n_ok = sum(1 for t in model["tools"] if (t.get("completeness") or 0) >= COVERAGE_GOOD)
            link = viewer_open_link(model["sample"], model["plasmid"]) if payload else f"#{ident}"
            gallery.append([sample, model["plasmid"], f"{model['length']:,}" if model["length"] else rc.missing("no length"),
                            f"{n_ok} of {len(model['tools'])}",
                            rc.Raw(f"<a href='{rc.esc(link)}'>map</a>") if drawable else rc.missing("not drawn")])
        if not models:
            parts.append(rc.note("This sample has no truth plasmid in its alignment data.").__str__())
        blocks_html.append(f"<details{' open' if index == 0 else ''}><summary><strong>{rc.esc(sample)}</strong> "
                           f"({len(models)} truth plasmid{'s' if len(models) != 1 else ''})</summary>{''.join(parts)}</details>")
    table = str(rc.panel(["Sample", "Plasmid", "Length (bp)", "Tools at 90% or more", "Map"], gallery, "No truth plasmids."))
    index_html = f"<details class='pv-index'><summary><strong>Plasmid index table</strong> ({len(gallery)} truth plasmids)</summary>{table}</details>"
    style = f"<style>{MAP_STYLE}</style>" + viewer_asset(VIEWER_ASSETS[0])
    fallback = "<div class='pv-fallback'>" + "".join(blocks_html) + "</div>"
    if not payloads:
        return rc.section("plasmid-maps", "Plasmid maps", LEAD, style + index_html + fallback)
    viewer = f"<div class='pv-root' id='pv-root' hidden data-plasmids='{len(payloads)}'></div>" + viewer_script_blocks(payloads)
    body = style + viewer + index_html + fallback + viewer_asset(VIEWER_ASSETS[1]) + viewer_asset(VIEWER_ASSETS[2]) + viewer_asset(VIEWER_ASSETS[3])
    return rc.section("plasmid-maps", "Plasmid maps", LEAD, body)


def inject(page, results_dir, data_dir, scores_path):
    """Add the `plasmid-maps` section before Recommendations, with its nav link (data_dir may be None or empty)."""
    section = str(build_section(results_dir, data_dir, scores_path))
    return rc.inject_sections(rc.add_style(page), section, SECTIONS)
