#!/usr/bin/env python3
"""
report_fig_facets.py -- stratified small-multiples heatmaps: tools across, strata down, one panel per metric, one shared 0-1 colour bar.

  fig-facets   Columns are tools (same order in every panel). Rows are conditions nested in blocks: the BLOCK variable splits the rows into
               blocks and the ROW variable orders the rows inside each block. Both are picked from the strata the data record. One panel per
               metric (precision, recall, F1, CPRR, plasmid recall, completeness, ...), all on one 0-1 colour scale. Layout after the
               multi-panel heatmaps of metagenomic profiler benchmarks.

Two levels of unit, chosen by the reader when both exist:
  isolate   one value per isolate and tool, from scores.tsv (always present). Strata: species, sequencing depth band, reference tier,
            source study, sample origin, Gram group, plasmid content, plasmids in the truth.
  plasmid   one value per truth plasmid and tool, from <sample>/<tool>.per_plasmid.tsv and <tool>.cprr.tsv (present when the per-sample
            folders are). Strata add: plasmid size band, replicon type, MOB type, AMR carriage, circular truth.

How a cell is made (mirrored in assets/report/fig_facets_core.html; test/test_report_fig_facets.py and test/test_report_fig_visuals_js.py compare them)
  unit set       units whose stratum values equal the block and row of the cell AND that have a value for that tool and metric (n counts them)
  mean metrics   value = mean over the units; the interval shown is the RANGE (min to max), labelled as a range, because no coverage is claimed
  proportion     CPRR, recovered share: value = sum(correct) / sum(assessed) pooled over the units; the interval is a Wilson interval over the
                 pooled plasmids (not cluster-aware, labelled so)
  too few        n < MIN_N (default 3, adjustable 1 to 10): hatched, flagged "too few", still labelled with its n, never shaded as if reliable
  blank          a block and row combination with no unit, or a tool with no value there: drawn empty. It is never 0.
A unit that a tool did not run (or has no value) holds None. Every cell lists its units in the side panel with their own values.

  python python/report_fig_facets.py ...    no command line; used through inject()
  build_payload(results_dir, data_dir, scores_path) -> (payload or None, reason)
  inject(page, results_dir, data_dir, scores_path)   add the section `fig-facets` before Recommendations

Standard library only.
"""
import glob
import json
import math
import os
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import report_common as rc  # noqa: E402

SID = "fig-facets"
TITLE = "Performance across conditions: tools by stratum"
SECTIONS = [(SID, "Facet heatmaps")]
MIN_N = 3
NOT_REC = "not recorded"
Z = 1.959963984540054
SYNTHETIC_NOTE = "The bundled demo data are synthetic and tiny: the panels demonstrate the figure, not a biological result."

DEPTH_ORDER = ["<30x", "30-59x", "60-99x", "100-199x", ">=200x"]
CONTENT_ORDER = ["<10 kb", "10-100 kb", ">100 kb"]
SIZE_ORDER = ["<10kb", "10-50kb", ">50kb"]
COUNT_ORDER = ["1", "2-3", "4+"]
TIER_NAME = {"1": "Tier 1", "2": "Tier 2", "3": "Tier 3 (provisional)"}
TIER_ORDER = ["Tier 1", "Tier 2", "Tier 3 (provisional)"]
ORDERS = {"depth": DEPTH_ORDER, "content": CONTENT_ORDER, "size": SIZE_ORDER, "count": COUNT_ORDER, "tier": TIER_ORDER,
          "circular": ["circular", "not circular"], "amr": ["carries AMR gene", "no AMR gene annotated"]}
ISOLATE_STRATA = [("species", "Species"), ("depth", "Sequencing depth"), ("tier", "Reference tier"), ("study", "Source study"),
                  ("origin", "Sample origin"), ("gram", "Gram group"), ("content", "Plasmid content (total bp)"), ("count", "Plasmids in the truth")]
PLASMID_STRATA = [("species", "Species"), ("size", "Plasmid size"), ("replicon", "Replicon type"), ("mob", "MOB type"), ("amr", "AMR carriage"),
                  ("circular", "Circular truth"), ("depth", "Sequencing depth"), ("tier", "Reference tier"), ("study", "Source study")]
ISOLATE_METRICS = [("precision", "Precision", "mean", "Share of the bases the tool called plasmid that are plasmid."),
                   ("recall", "Recall", "mean", "Share of truth plasmid bases the tool found."),
                   ("f1", "F1", "mean", "Harmonic mean of precision and recall (bases)."),
                   ("cprr", "CPRR", "prop", "Share of truth plasmids reconstructed correctly; pooled over the isolates in the cell."),
                   ("plasmid_recall", "Plasmid recall", "mean", "Share of truth plasmids recovered at the 90% completeness threshold.")]
PLASMID_METRICS = [("recovered", "Recovered (>=90%)", "prop", "Share of truth plasmids with completeness at or above 0.90."),
                   ("cprr", "CPRR correct", "prop", "Share of truth plasmids reconstructed correctly (coverage, bin share, no split, identity)."),
                   ("completeness", "Completeness", "mean", "Fraction of the truth plasmid's bases covered by the tool's output.")]
DEFAULT_METRICS = {"isolate": ["precision", "recall", "f1", "cprr"], "plasmid": ["recovered", "cprr", "completeness"]}
LEVEL_LABEL = {"isolate": "Isolates", "plasmid": "Plasmids"}
UNIT_WORD = {"isolate": "isolate", "plasmid": "plasmid"}


# ------------------------------------------------------------------------------------------------ small helpers
def wilson(c, n):
    if not n:
        return None
    p = c / n
    d = 1 + Z * Z / n
    centre = (p + Z * Z / (2 * n)) / d
    half = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / d
    return [max(0.0, centre - half), min(1.0, centre + half)]


def depth_band(x):
    if x is None:
        return NOT_REC
    return DEPTH_ORDER[0] if x < 30 else DEPTH_ORDER[1] if x < 60 else DEPTH_ORDER[2] if x < 100 else DEPTH_ORDER[3] if x < 200 else DEPTH_ORDER[4]


def content_band(bp):
    if bp is None:
        return NOT_REC
    return CONTENT_ORDER[0] if bp < 10000 else CONTENT_ORDER[1] if bp < 100000 else CONTENT_ORDER[2]


def size_band(bp):
    if bp is None:
        return NOT_REC
    return SIZE_ORDER[0] if bp < 10000 else SIZE_ORDER[1] if bp <= 50000 else SIZE_ORDER[2]


def count_band(n):
    if n is None:
        return NOT_REC
    return COUNT_ORDER[0] if n <= 1 else COUNT_ORDER[1] if n <= 3 else COUNT_ORDER[2]


def text_or_none(value):
    value = (value or "").strip()
    return None if value.lower() in ("", "not_recorded", "not recorded", "unknown", "na", "n/a") else value


def order_values(key, labels):
    """Display order of the stratum labels: the defined order for banded variables, else alphabetical; 'not recorded' always last."""
    labels = set(labels)
    fixed = [v for v in ORDERS.get(key, []) if v in labels]
    rest = sorted(v for v in labels if v not in fixed and v != NOT_REC)
    return fixed + rest + ([NOT_REC] if NOT_REC in labels else [])


def r4(x):
    return None if x is None else round(x, 4)


def _int(value):
    n = rc.number(value)
    return None if n is None else int(round(n))


# ------------------------------------------------------------------------------------------------ context: isolates, plasmids
def sample_context(results_dir, data_dir, scores):
    """{sample: {species, study, origin, gram, depth, tier, content_bp, count}}; every value None when not recorded."""
    ctx = {}

    def put(sample, **kw):
        row = ctx.setdefault(sample, {})
        for k, v in kw.items():
            if v is not None and row.get(k) is None:
                row[k] = v

    for base in (results_dir, data_dir):
        for r in (rc.read_tsv(os.path.join(base, "samples.tsv")) if base else None) or []:
            s = r.get("sample_id") or r.get("sample")
            if s:
                put(s, species=text_or_none(r.get("organism")), study=text_or_none(r.get("source_study")), origin=text_or_none(r.get("sample_origin")),
                    gram=text_or_none(r.get("gram_group")), depth=rc.number(r.get("read_depth_x")))
    for name in ("benchmark.dataset_features.tsv", "benchmark.candidate_features.tsv"):
        for r in rc.read_tsv(os.path.join(results_dir, name)) or []:
            s = r.get("sample")
            if s:
                put(s, species=text_or_none(r.get("organism")), study=text_or_none(r.get("source_study")), origin=text_or_none(r.get("sample_origin")),
                    gram=text_or_none(r.get("gram_group")), depth=rc.number(r.get("read_depth_x")), count=_int(r.get("plasmid_count")))
    for r in rc.read_tsv(os.path.join(results_dir, "benchmark.truth_provenance.tsv")) or []:
        s, tier = r.get("sample"), (r.get("reference_tier") or "").strip()
        if s and tier in TIER_NAME:
            put(s, tier=TIER_NAME[tier])
    for r in scores or []:
        s = r.get("sample")
        if s:
            put(s, content_bp=rc.number(r.get("true_plasmid_bp")), count=_int(r.get("true_plasmid_count")))
    return ctx


def tool_order(results_dir, scores):
    """Ordered [[track, tool], ...]: tracks in order of appearance, tools by leaderboard rank, baselines last, then name. The same in every panel."""
    ranks = {}
    for r in rc.read_tsv(os.path.join(results_dir, "benchmark.leaderboard.tsv")) or []:
        n = rc.number(r.get("rank"))
        key = (r.get("analysis_track") or "short_read", r.get("tool", ""))
        if n is not None and key not in ranks:
            ranks[key] = n
    seen, tracks = [], []
    for r in scores:
        key = (r.get("analysis_track") or "not recorded", r.get("tool"))
        if key not in seen:
            seen.append(key)
        if key[0] not in tracks:
            tracks.append(key[0])
    return sorted(seen, key=lambda k: (tracks.index(k[0]), str(k[1]).startswith("baseline_"), ranks.get(k, 1e9), str(k[1])))


def load_plasmids(results_dir, data_dir, ctx, tools=None):
    """Truth plasmids and what is known of them, from the per-sample folders.

    {rows: [{sample, id, length, circular, ...}], outcome: {(track, tool): {(sample, id): {comp, correct}}}, feats: {(sample, id): {...}},
     annotated: {sample: {amr, features, proteins}}}   or None when no per-sample folder holds a truth table.
    """
    bases = [b for b in (data_dir, results_dir) if b and os.path.isdir(b)]
    rows, outcome, feats, annotated = [], {}, {}, {}
    classes = None
    seen = set()
    for base in bases:
        for truth_path in sorted(glob.glob(os.path.join(base, "*", "truth.tsv"))):
            sdir = os.path.dirname(truth_path)
            sample = os.path.basename(sdir)
            if sample in seen:
                continue
            truth = rc.read_tsv(truth_path) or []
            plas = [r for r in truth if (r.get("molecule_type") or "PLASMID").upper() == "PLASMID" and r.get("sequence_id")]
            if not plas:
                continue
            seen.add(sample)
            circ = rc.read_tsv(os.path.join(sdir, "truth_circular.tsv"))
            circ_ids = None if circ is None else {r.get("sequence_id") for r in circ}
            amr_path, feat_path, prot_path = (os.path.join(sdir, f) for f in ("truth_amr.tsv", "truth_features.tsv", "truth_proteins.tsv"))
            amr, ft, prot = rc.read_tsv(amr_path), rc.read_tsv(feat_path), rc.read_tsv(prot_path)
            annotated[sample] = {"amr": amr is not None, "features": ft is not None, "proteins": prot is not None}
            if amr and classes is None:
                classes = amr_classes()
            meta = ctx.get(sample, {})
            for r in plas:
                pid = r["sequence_id"]
                length = _int(r.get("length"))
                f = feats.setdefault((sample, pid), {"replicon": set(), "mob": set(), "amr_genes": set(), "amr_classes": set(), "other": {}})
                for a in amr or []:
                    if a.get("sequence_id") == pid and a.get("gene_name"):
                        f["amr_genes"].add(a["gene_name"])
                        f["amr_classes"].add(gene_class_of(a["gene_name"], classes))
                for a in ft or []:
                    if a.get("sequence_id") != pid or not a.get("label"):
                        continue
                    kind = a.get("feature_type") or "feature"
                    if kind == "replicon":
                        f["replicon"].add(a["label"])
                    elif kind == "mob":
                        f["mob"].add(a["label"])
                    else:
                        f["other"].setdefault(kind, set()).add(a["label"])
                for a in prot or []:
                    cat = (a.get("category") or "").strip()
                    name = (a.get("gene") or a.get("product") or "").strip()
                    if a.get("sequence_id") == pid and name and cat and cat not in ("replicon", "amr", "mob", "other", "unknown", "hypothetical"):
                        f["other"].setdefault("protein:" + cat, set()).add(name)
                rows.append({"sample": sample, "id": pid, "length": length, "circular": None if circ_ids is None else pid in circ_ids,
                             "species": meta.get("species"), "study": meta.get("study"), "tier": meta.get("tier"), "depth": meta.get("depth"),
                             "has_features": ft is not None, "has_amr": amr is not None})
            for path in sorted(glob.glob(os.path.join(sdir, "*.per_plasmid.tsv"))):
                tool = os.path.basename(path)[: -len(".per_plasmid.tsv")]
                per = rc.read_tsv(path) or []
                cprr = rc.read_tsv(os.path.join(sdir, f"{tool}.cprr.tsv"))
                correct = None if cprr is None else {r.get("true_plasmid"): (r.get("correct") or "").strip().lower() for r in cprr}
                track = (per[0].get("analysis_track") if per else None) or "short_read"
                slot = outcome.setdefault((track, tool), {})
                for r in per:
                    pid = r.get("sequence_id")
                    if pid:
                        slot[(sample, pid)] = {"comp": rc.number(r.get("completeness")),
                                               "correct": None if correct is None or pid not in correct else correct[pid] == "yes"}
    if not rows:
        return None
    return {"rows": rows, "outcome": outcome, "feats": feats, "annotated": annotated}


def amr_classes():
    path = Path(HERE).parent / "config" / "amr_gene_classes.tsv"
    return [(r["gene_prefix"], r["gene_class"]) for r in (rc.read_tsv(str(path)) or []) if r.get("gene_prefix")]


def gene_class_of(name, classes):
    lowered = (name or "").lower()
    for prefix, cls in sorted(classes or [], key=lambda item: -len(item[0])):
        if lowered.startswith(prefix.lower()):
            return cls
    return "other"


def plasmid_outcome(comp, correct):
    """recovered / partial / missed / None. Recovered = counted correct by CPRR (else completeness >= 0.90 when no CPRR file); partial = some
    truth bases covered but not counted correct; missed = none covered; None = the tool has no value for this plasmid."""
    if correct is True:
        return "recovered"
    if correct is None and comp is not None and comp >= 0.9:
        return "recovered"
    if comp is None and correct is None:
        return None
    return "partial" if (comp or 0) > 0 else "missed"


# ------------------------------------------------------------------------------------------------ levels
def _level(unit_kind, strata_defs, units, metrics, tool_vals):
    """units: [(id, label, {stratum: label|None})]; tool_vals: {tool index: {metric key: [value per unit]}}. Strata with no recorded value are dropped."""
    strata, kept = [], []
    for key, label in strata_defs:
        labels = [(u[2].get(key) or NOT_REC) for u in units]
        if all(v == NOT_REC for v in labels):
            continue
        strata.append({"k": key, "l": label, "vals": order_values(key, labels)})
        kept.append(key)
    out_units = []
    for uid, lab, sv in units:
        idx = []
        for st in strata:
            idx.append(st["vals"].index(sv.get(st["k"]) or NOT_REC))
        out_units.append([uid, lab, idx])
    mets, vals = [], {}
    for key, label, kind, desc in metrics:
        have = [t for t, m in tool_vals.items() if any(v is not None for v in m.get(key, []))]
        if not have:
            continue
        mi = len(mets)
        mets.append({"k": key, "l": label, "kind": kind, "d": desc})
        for t in have:
            vals.setdefault(str(t), {})[str(mi)] = tool_vals[t][key]
    if not mets or not strata:
        return None
    return {"unit": unit_kind, "strata": strata, "units": out_units, "metrics": mets, "vals": vals}


def isolate_level(scores, ctx, tools):
    tidx = {(t[0], t[1]): i for i, t in enumerate(tools)}
    samples = []
    for r in scores:
        if r.get("sample") not in samples:
            samples.append(r["sample"])
    sidx = {s: i for i, s in enumerate(samples)}
    units = []
    for s in samples:
        m = ctx.get(s, {})
        units.append((s, s, {"species": m.get("species"), "depth": None if m.get("depth") is None else depth_band(m["depth"]),
                             "tier": m.get("tier"), "study": m.get("study"), "origin": m.get("origin"), "gram": m.get("gram"),
                             "content": None if m.get("content_bp") is None else content_band(m["content_bp"]),
                             "count": None if m.get("count") is None else count_band(m["count"])}))
    tv, done = {}, set()
    for r in scores:
        key = (r.get("analysis_track") or "not recorded", r.get("tool"))
        if key not in tidx:
            continue
        t, u = tidx[key], sidx[r["sample"]]
        if (t, u) in done:
            continue
        done.add((t, u))
        slot = tv.setdefault(t, {k: [None] * len(samples) for k, *_ in ISOLATE_METRICS})
        for k in ("precision", "recall", "f1", "plasmid_recall"):
            slot[k][u] = r4(rc.number(r.get(k)))
        total, correct = rc.number(r.get("cprr_plasmids")), rc.number(r.get("cprr_correct"))
        if total and correct is not None and total > 0:
            slot["cprr"][u] = [int(round(correct)), int(round(total))]
    return _level("isolate", ISOLATE_STRATA, units, ISOLATE_METRICS, tv)


def plasmid_level(pl, ctx, tools):
    tidx = {(t[0], t[1]): i for i, t in enumerate(tools)}
    rows = pl["rows"]
    units = []
    for r in rows:
        f = pl["feats"].get((r["sample"], r["id"])) or {}
        rep = (" + ".join(sorted(f.get("replicon", ()))) or "no replicon annotated") if r["has_features"] else None
        mob = (" + ".join(sorted(f.get("mob", ()))) or "no MOB annotated") if r["has_features"] else None
        amr = None if not r["has_amr"] else ("carries AMR gene" if f.get("amr_genes") else "no AMR gene annotated")
        units.append((f"{r['sample']}/{r['id']}", f"{r['id']} ({r['sample']})",
                      {"species": r["species"], "size": None if r["length"] is None else size_band(r["length"]), "replicon": rep, "mob": mob, "amr": amr,
                       "circular": None if r["circular"] is None else ("circular" if r["circular"] else "not circular"),
                       "depth": None if r["depth"] is None else depth_band(r["depth"]), "tier": r["tier"], "study": r["study"]}))
    tv = {}
    for key, per in pl["outcome"].items():
        if key not in tidx:
            continue
        slot = {k: [None] * len(rows) for k, *_ in PLASMID_METRICS}
        for i, r in enumerate(rows):
            o = per.get((r["sample"], r["id"]))
            if not o:
                continue
            if o["comp"] is not None:
                slot["completeness"][i] = r4(o["comp"])
                slot["recovered"][i] = [1 if o["comp"] >= 0.9 else 0, 1]
            if o["correct"] is not None:
                slot["cprr"][i] = [1 if o["correct"] else 0, 1]
        tv[tidx[key]] = slot
    return _level("plasmid", PLASMID_STRATA, units, PLASMID_METRICS, tv)


def build_payload(results_dir, data_dir, scores_path):
    """The figure data, or (None, reason). Compact: per level one array of values per tool and metric, in the order of the units."""
    scores = rc.read_tsv(scores_path)
    if scores is None:
        return None, "scores.tsv was not found."
    if not scores:
        return None, "scores.tsv has no rows."
    ctx = sample_context(results_dir, data_dir, scores)
    tools = tool_order(results_dir, scores)
    levels = {}
    iso = isolate_level(scores, ctx, tools)
    if iso:
        levels["isolate"] = iso
    pl = load_plasmids(results_dir, data_dir, ctx, tools)
    if pl:
        lv = plasmid_level(pl, ctx, tools)
        if lv:
            levels["plasmid"] = lv
    if not levels:
        return None, ("no stratum is recorded for any isolate (species, depth, reference tier, study and origin are all missing) or no metric has a value; "
                      "the sample sheet (samples.tsv) and benchmark.truth_provenance.tsv hold them")
    return {"v": 1, "minN": MIN_N, "tools": [list(t) for t in tools], "tracks": sorted({t[0] for t in tools}, key=[t[0] for t in tools].index),
            "levels": levels, "defaults": DEFAULT_METRICS}, None


# ------------------------------------------------------------------------------------------------ the model (mirrored in fig_facets_core.html)
def default_selection(level, track_tools=None):
    """Block and row strata: the first two strata with at least two values (else the first two), metrics: the defaults that exist."""
    multi = [s["k"] for s in level["strata"] if len([v for v in s["vals"] if v != NOT_REC]) >= 2]
    keys = [s["k"] for s in level["strata"]]
    pick = multi + [k for k in keys if k not in multi]
    block = pick[0]
    row = pick[1] if len(pick) > 1 else None
    have = [m["k"] for m in level["metrics"]]
    want = [k for k in DEFAULT_METRICS[level["unit"]] if k in have] or have[:3]
    return {"block": block, "row": row, "metrics": want}


def stratum(level, key):
    return next((s for s in level["strata"] if s["k"] == key), None)


def grid(level, block_key, row_key):
    """Blocks of rows: [{label, rows: [{label, units: [unit index]}]}]. Blocks are the block stratum's values that occur; rows are the row stratum's
    values that occur ANYWHERE, repeated in every block so a missing combination is a visible blank."""
    bs = stratum(level, block_key)
    rs = stratum(level, row_key) if row_key and row_key != block_key else None
    bi = level["strata"].index(bs)
    ri = level["strata"].index(rs) if rs else None
    used_rows = sorted({u[2][ri] for u in level["units"]}) if rs else [0]
    out = []
    for b, blabel in enumerate(bs["vals"]):
        members = [i for i, u in enumerate(level["units"]) if u[2][bi] == b]
        if not members:
            continue
        rows = []
        for r in used_rows:
            units = [i for i in members if rs is None or level["units"][i][2][ri] == r]
            rows.append({"label": rs["vals"][r] if rs else "all", "units": units})
        out.append({"label": blabel, "rows": rows})
    return out


def cell_stats(level, tool, metric, units, min_n=MIN_N):
    """n, value, interval, few, and the units with their values for one cell. `tool` and `metric` are indices; value None when n == 0."""
    kind = level["metrics"][metric]["kind"]
    arr = level["vals"].get(str(tool), {}).get(str(metric))
    items = []
    if arr is not None:
        items = [(i, arr[i]) for i in units if arr[i] is not None]
    n = len(items)
    out = {"n": n, "v": None, "lo": None, "hi": None, "few": 0 < n < min_n, "kind": kind, "units": [i for i, _ in items]}
    if not n:
        return out
    if kind == "prop":
        c, tot = sum(v[0] for _, v in items), sum(v[1] for _, v in items)
        out["c"], out["total"] = c, tot
        if tot:
            out["v"] = c / tot
            out["lo"], out["hi"] = wilson(c, tot)
    else:
        vs = [v for _, v in items]
        out["v"] = sum(vs) / len(vs)
        out["lo"], out["hi"] = min(vs), max(vs)
    return out


def unit_value(level, tool, metric, unit):
    arr = level["vals"].get(str(tool), {}).get(str(metric))
    v = None if arr is None else arr[unit]
    if v is None:
        return None
    return v[0] / v[1] if isinstance(v, list) and v[1] else (None if isinstance(v, list) else v)


# ------------------------------------------------------------------------------------------------ colour and static drawing
STOPS = [(0.0, (68, 1, 84)), (0.25, (59, 82, 139)), (0.5, (33, 144, 140)), (0.75, (93, 200, 99)), (1.0, (253, 231, 37))]


def colour(v):
    """Shared 0-1 scale (viridis anchors, read in grayscale and by most colour-blind readers); returns '#rrggbb'."""
    v = min(1.0, max(0.0, v))
    for (a, ca), (b, cb) in zip(STOPS, STOPS[1:]):
        if v <= b:
            f = (v - a) / (b - a)
            return "#%02x%02x%02x" % tuple(int(round(x + (y - x) * f)) for x, y in zip(ca, cb))
    return "#%02x%02x%02x" % STOPS[-1][1]


def ink_on(hex_colour):
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return "#ffffff" if 0.299 * r + 0.587 * g + 0.114 * b < 140 else "#111111"


CW, CH, BG, PG, LW, TOPH, BOTH = 30, 16, 6, 16, 150, 34, 90   # cell width and height, block gap, panel gap, label width, header, tool-label height


def esc(x):
    return rc.esc(x)


def fnum(v):
    return "no value" if v is None else f"{v:.2f}"


def svg_static(level, tools, sel, min_n=MIN_N, track=None):
    """The complete static figure for one selection: every chosen metric as a panel, one colour bar. Returns (svg, panels) or (None, reason)."""
    cols = [i for i, t in enumerate(tools) if (track is None or t[0] == track) and str(i) in level["vals"]]
    if not cols:
        return None, "no tool has values at this level in this track"
    g = grid(level, sel["block"], sel["row"])
    if not g:
        return None, "no unit is recorded for the chosen strata"
    metrics = [i for i, m in enumerate(level["metrics"]) if m["k"] in sel["metrics"]] or [0]
    nrows = sum(len(b["rows"]) for b in g)
    height = TOPH + nrows * CH + (len(g) - 1) * BG + BOTH
    pw = len(cols) * CW
    width = LW + len(metrics) * (pw + PG) + 70
    o = [f"<svg class='fc-svg' viewBox='0 0 {width} {height}' role='img' aria-labelledby='fc-st-t fc-st-d' xmlns='http://www.w3.org/2000/svg' font-family='Arial,Helvetica,sans-serif'>",
         f"<title id='fc-st-t'>Tools by stratum: {esc(' and '.join(m['l'] for m in (level['metrics'][i] for i in metrics)))}</title>",
         f"<desc id='fc-st-d'>One panel per metric, columns are tools, rows are {esc(sel['row'] or 'all units')} within blocks of {esc(sel['block'])}. "
         f"Colour is the value from 0 to 1; a hatched cell has fewer than {min_n} units; an empty cell has no data.</desc>",
         "<defs><pattern id='fc-hatch' width='5' height='5' patternUnits='userSpaceOnUse' patternTransform='rotate(45)'>"
         "<rect width='5' height='5' fill='#d8d8d8'/><line x1='0' y1='0' x2='0' y2='5' stroke='#555' stroke-width='1.6'/></pattern>"
         "<linearGradient id='fc-bar' x1='0' y1='1' x2='0' y2='0'>"
         + "".join(f"<stop offset='{a}' stop-color='{colour(a)}'/>" for a in (0, 0.25, 0.5, 0.75, 1)) + "</linearGradient></defs>"]
    for k, mi in enumerate(metrics):
        x0 = LW + k * (pw + PG)
        o.append(f"<text x='{x0 + pw / 2}' y='16' font-size='12' font-weight='bold' text-anchor='middle' fill='currentColor'>{esc(level['metrics'][mi]['l'])}</text>")
        y = TOPH
        for b in g:
            for r in b["rows"]:
                for c, tool in enumerate(cols):
                    st = cell_stats(level, tool, mi, r["units"], min_n)
                    x = x0 + c * CW
                    if st["n"] == 0:
                        o.append(f"<rect x='{x}' y='{y}' width='{CW}' height='{CH}' fill='none' stroke='#9aa3a8' stroke-width='.4' stroke-dasharray='2 2'/>")
                        continue
                    fill = "url(#fc-hatch)" if st["few"] else colour(st["v"])
                    ink = "#111111" if st["few"] else ink_on(colour(st["v"]))
                    o.append(f"<g><title>{esc(b['label'])} / {esc(r['label'])} / {esc(tools[tool][1])}: {fnum(st['v'])}, n = {st['n']}"
                             f"{' (too few)' if st['few'] else ''}</title><rect x='{x}' y='{y}' width='{CW}' height='{CH}' fill='{fill}' stroke='#fff' stroke-width='.6'/>"
                             f"<text x='{x + CW / 2}' y='{y + CH - 4.5}' font-size='8.5' text-anchor='middle' fill='{ink}'>{st['n']}</text></g>")
                if k == 0:
                    o.append(f"<text x='{LW - 6}' y='{y + CH - 4}' font-size='9' text-anchor='end' fill='currentColor'>{esc(r['label'])}</text>")
                y += CH
            if k == 0:
                span = len(b["rows"]) * CH
                o.append(f"<text x='8' y='{y - span / 2 + 3}' font-size='10.5' font-weight='bold' fill='currentColor'>{esc(b['label'])}</text>")
            y += BG
        for c, tool in enumerate(cols):
            tx, ty = x0 + c * CW + CW / 2, y - BG + 12
            o.append(f"<text transform='translate({tx},{ty}) rotate(45)' font-size='9.5' fill='currentColor'>{esc(tools[tool][1])}</text>")
    bx = LW + len(metrics) * (pw + PG) + 6
    o.append(f"<rect x='{bx}' y='{TOPH}' width='12' height='120' fill='url(#fc-bar)' stroke='#666' stroke-width='.5'/>")
    for v in (0, 0.5, 1):
        o.append(f"<text x='{bx + 16}' y='{TOPH + 120 - v * 120 + 3}' font-size='9' fill='currentColor'>{v:g}</text>")
    o.append(f"<rect x='{bx}' y='{TOPH + 134}' width='12' height='12' fill='url(#fc-hatch)' stroke='#666' stroke-width='.5'/>"
             f"<text x='{bx + 16}' y='{TOPH + 144}' font-size='9' fill='currentColor'>n &lt; {min_n}</text>")
    o.append("</svg>")
    return "".join(o), len(metrics)


def table_html(level, tools, sel, min_n=MIN_N, track=None):
    """Every cell of the figure as a table (the 'Table' fold): block, row, tool, metric, n, value, interval, flag."""
    cols = [i for i, t in enumerate(tools) if (track is None or t[0] == track) and str(i) in level["vals"]]
    metrics = [i for i, m in enumerate(level["metrics"]) if m["k"] in sel["metrics"]] or [0]
    body = []
    for b in grid(level, sel["block"], sel["row"]):
        for r in b["rows"]:
            for mi in metrics:
                for tool in cols:
                    st = cell_stats(level, tool, mi, r["units"], min_n)
                    body.append([b["label"], r["label"], tools[tool][1], level["metrics"][mi]["l"], st["n"],
                                 rc.missing("no unit has a value here") if st["v"] is None else f"{st['v']:.3f}",
                                 "" if st["lo"] is None else f"{st['lo']:.3f} to {st['hi']:.3f} ({'range' if st['kind'] == 'mean' else 'Wilson'})",
                                 "too few" if st["few"] else ""])
    heads = ["Block", "Row", "Tool", "Metric", "n units", "Value", "Interval", "Flag"]
    return rc.panel(heads, body, empty="No cells.")


# ------------------------------------------------------------------------------------------------ section
def asset(name):
    return (Path(HERE).parent / "assets" / "report" / name).read_text(encoding="utf-8")


def json_script(sid, payload):
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    return f"<script type='application/json' id='{sid}'>" + text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026") + "</script>"


LEAD = ("Each panel is one metric; columns are tools, rows are conditions (strata) nested in blocks. Pick the strata, the metrics and the track, then click a cell to see "
        "which isolates or plasmids are in it. A cell with fewer than three units is hatched and labelled with its n: do not read it as a result. Empty means no data, never zero.")


def build_section(results_dir, data_dir, scores_path):
    data, reason = build_payload(results_dir, data_dir, scores_path)
    if data is None:
        return rc.section(SID, TITLE, LEAD, rc.not_run(f"Not available in this run: {reason}"), group="Figures")
    level = data["levels"].get("isolate") or next(iter(data["levels"].values()))
    sel = default_selection(level)
    track = data["tracks"][0]
    svg, info = svg_static(level, data["tools"], sel, MIN_N, track)
    if svg is None:
        static = rc.not_run(f"Not available in this run: {info}.")
    else:
        mlabel = ", ".join(m["l"] for m in level["metrics"] if m["k"] in sel["metrics"])
        static = (f"<figure class='rpt-figure fc-fig'>{svg}<figcaption>{esc(LEVEL_LABEL[level['unit']])} per tool, track {esc(track)}. Blocks: "
                  f"{esc(stratum(level, sel['block'])['l'])}; rows: {esc(stratum(level, sel['row'])['l']) if sel['row'] else 'none'}; panels: {esc(mlabel)}. "
                  f"The number in a cell is its n; hatched = fewer than {MIN_N}; dashed empty = no data. {esc(SYNTHETIC_NOTE) if _synthetic(results_dir) else ''}</figcaption></figure>")
    fold = ("<details class='rpt-collapsible fc-table' data-closed><summary>Table: every cell of this figure</summary>"
            f"{table_html(level, data['tools'], sel, MIN_N, track)}</details>") if svg is not None else ""
    body = (json_script("fc-data", data) + asset("fig_facets_style.html") + asset("fig_facets_core.html") + asset("fig_facets_ui.html") +
            f"<div class='fc-root' id='fc-root' data-fc-n='{len(data['levels'])}'><div class='fc-static'>{static}</div></div>{fold}")
    return rc.section(SID, TITLE, LEAD, body, group="Figures")


def _synthetic(results_dir):
    rows = rc.read_tsv(os.path.join(results_dir, "samples.tsv")) or []
    return bool(rows) and all((r.get("sample_origin") or "").strip().lower() == "synthetic" for r in rows)


def inject(page, results_dir, data_dir, scores_path):
    return rc.inject_sections(rc.add_style(page), str(build_section(results_dir, data_dir, scores_path)), SECTIONS)
