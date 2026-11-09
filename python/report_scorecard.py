#!/usr/bin/env python3
"""
report_scorecard.py -- a weighted benchmark SCORECARD shown beside the existing composite.

It is another view of the same results. It is never the ranking: the pre-specified endpoints and the leaderboard are
unchanged, and the thresholds and weights here are examples (config/scorecard.tsv), most of them 'proposed'.

Score transform (every metric, config/scorecard.tsv gives the four thresholds and the direction)
  piecewise linear through  (excellent -> 100), (good -> 85), (moderate -> 60), (floor -> 0), clamped to [0, 100].
  Higher-is-better: value >= excellent scores 100, value <= floor scores 0.  Lower-is-better: the mirror image.
  Example (A1, percent): 99.9 -> 100, 99.0 -> 85, 95.0 -> 60, 90 -> 0, 99.45 -> 92.5 (halfway between 85 and 100).
  Band: excellent / good / moderate / poor by the thresholds themselves (an edge value takes the better band).

Overall = weighted mean of the scores of the metrics that could be scored, weights renormalised:
  overall = sum(w * score) / sum(w) over scored metrics; 'scored weight share' = sum(w scored) / sum(w all).
  Metrics that cannot be scored (A4 SNP concordance and C2 structural variant F1 need a truth variant set; others when
  their input is absent) are listed with the reason and their weight is excluded, never counted as zero.
  Overall bands: >= 90 Excellent, >= 75 Good, >= 55 Moderate, else Poor. A scored share below 0.5 is marked provisional.

Scenarios (NON-exclusive; one sample can be in several), from benchmark.scenarios.tsv:
  complex      tag multi_plasmid, large_plasmid or repeat_rich
  annotated    tag annotated
  challenging  tag low_depth, or read_quality_band == low (samples sheet)
  simple       has plasmids, none of the complex tags, and read_x >= 30 (a blank depth does not qualify)
  A per-scenario scorecard uses only member samples and reports n; n < SCORECARD_MIN_SAMPLES (5) is flagged underpowered.
  Runtime, memory and success rate are per-tool summaries, not per sample, so they are not scored inside a scenario.

Metric sources (units as in config): identity/mismatch/indel from benchmark.accuracy.tsv weighted by aligned_columns;
coverage, completeness, recovery, circular and AMR from scores.tsv (mean over isolates with a value); structural accuracy
from benchmark.ngoc.tsv (sum n_conserved / sum n_pairs), else collinear_fraction in <sample>/structural_summary.tsv; repeat
resolution joins truth repeat_rich plasmids to <sample>/<tool>.per_plasmid.tsv completeness; annotation concordance reads
<sample>/visualization/alignment_blocks.json; functional completeness from benchmark.feature_preservation.tsv;
runtime/memory/success from benchmark.performance.tsv (no track column: applied to every track of the tool).

Standard library only.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import report_common as rc  # noqa: E402
import report_svg as sv  # noqa: E402

DEFAULT_CONFIG = os.path.join(HERE, "..", "config", "scorecard.tsv")
SCORECARD_MIN_SAMPLES = int(os.environ.get("SCORECARD_MIN_SAMPLES", "5"))
STATUSES = ("proposed", "fixed", "undefined")   # undefined: no bands exist yet (blank thresholds), the metric cannot be graded
COMPLEX_TAGS = ("multi_plasmid", "large_plasmid", "repeat_rich")
SCENARIOS = ("simple", "complex", "annotated", "challenging")
OVERALL_BANDS = ((90.0, "excellent"), (75.0, "good"), (55.0, "moderate"))
SECTIONS = [("scorecard", "Scorecard"), ("scorecard-definitions", "Scorecard definitions"),
            ("scorecard-scenarios", "Scorecard by scenario")]
NOT_AVAILABLE = {"A4": "needs a truth variant set (SNP calls on the truth), which this benchmark does not carry",
                 "C2": "needs a truth structural-variant set, which this benchmark does not carry"}
FUNCTIONAL_KINDS = ("replicon", "mobility", "mob", "amr")
PERF_IDS = ("E1", "E2", "E3")


# ---------------------------------------------------------------- config

def load_config(path=None):
    """The metric specs (list of dicts, thresholds as floats) from config/scorecard.tsv; ValueError if it is not valid."""
    rows = rc.read_tsv(path or DEFAULT_CONFIG)
    if rows is None:
        raise ValueError(f"scorecard config not found: {path or DEFAULT_CONFIG}")
    return validate_config(rows)


def validate_config(rows):
    specs, seen = [], set()
    for row in rows:
        spec = dict(row)
        sid = (spec.get("id") or "").strip()
        if not sid:
            raise ValueError("scorecard config: a row has no id")
        if sid in seen:
            raise ValueError(f"scorecard config: duplicate id {sid}")
        seen.add(sid)
        spec["id"] = sid
        status = spec.get("status")
        if status not in STATUSES:
            raise ValueError(f"scorecard config: {sid} status must be one of {', '.join(STATUSES)}")
        weight = rc.number(spec.get("weight"))
        if weight is None:
            raise ValueError(f"scorecard config: {sid} has a non-numeric weight")
        spec["weight"] = weight
        for key in ("excellent", "good", "moderate", "floor"):
            value = rc.number(spec.get(key))
            if status == "undefined":
                if value is not None:
                    raise ValueError(f"scorecard config: {sid} is undefined, so its {key} threshold must be blank")
            elif value is None:
                raise ValueError(f"scorecard config: {sid} has a non-numeric {key}")
            spec[key] = value
        if spec["weight"] < 0:
            raise ValueError(f"scorecard config: {sid} has a negative weight")
        direction = (spec.get("direction") or "").strip()
        if direction not in ("higher", "lower"):
            raise ValueError(f"scorecard config: {sid} direction must be higher or lower")
        spec["direction"] = direction
        if status != "undefined":
            chain = [spec["excellent"], spec["good"], spec["moderate"], spec["floor"]]
            steps = list(zip(chain, chain[1:]))
            ordered = all(a > b for a, b in steps) if direction == "higher" else all(a < b for a, b in steps)
            if not ordered:
                raise ValueError(f"scorecard config: {sid} thresholds are not ordered excellent..floor for a {direction}-is-better metric")
        specs.append(spec)
    if not specs:
        raise ValueError("scorecard config has no metrics")
    if abs(sum(s["weight"] for s in specs) - 100.0) > 1e-6:
        raise ValueError(f"scorecard config: weights sum to {sum(s['weight'] for s in specs)}, not 100")
    return specs


# ---------------------------------------------------------------- scoring

def band_of(spec, value):
    if value is None or spec["excellent"] is None:
        return None
    higher = spec["direction"] == "higher"
    for name in ("excellent", "good", "moderate"):
        if (value >= spec[name]) if higher else (value <= spec[name]):
            return name
    return "poor"


def score_value(spec, value):
    """(score 0-100, band) for a value in the metric's unit; (None, None) for no value."""
    if value is None or spec["excellent"] is None:
        return None, None
    pts = [(spec["excellent"], 100.0), (spec["good"], 85.0), (spec["moderate"], 60.0), (spec["floor"], 0.0)]
    higher = spec["direction"] == "higher"
    if (value >= pts[0][0]) if higher else (value <= pts[0][0]):
        score = 100.0
    elif (value <= pts[-1][0]) if higher else (value >= pts[-1][0]):
        score = 0.0
    else:
        score = 0.0
        for (v0, s0), (v1, s1) in zip(pts, pts[1:]):
            inside = (v1 < value <= v0) if higher else (v0 <= value < v1)
            if inside:
                score = s0 + (s1 - s0) * (value - v0) / (v1 - v0)
                break
    return max(0.0, min(100.0, score)), band_of(spec, value)


def overall_band(score):
    if score is None:
        return None
    for floor, name in OVERALL_BANDS:
        if score >= floor:
            return name
    return "poor"


def overall(specs, values):
    """Weighted overall of one tool. `values` maps id -> {'value': float|None, 'reason': str}.

    Returns score, band, scored_share, scored/unavailable lists and the per-metric (score, band)."""
    total = sum(s["weight"] for s in specs)
    num = den = 0.0
    per, unavailable = {}, []
    for spec in specs:
        entry = values.get(spec["id"]) or {"value": None, "reason": "not computed"}
        score, band = score_value(spec, entry.get("value"))
        per[spec["id"]] = (score, band)
        if score is None:
            unavailable.append((spec["id"], entry.get("reason") or "no data"))
            continue
        num += spec["weight"] * score
        den += spec["weight"]
    score = num / den if den else None
    share = den / total if total else 0.0
    return {"score": score, "band": overall_band(score), "scored_share": share, "scored_weight": den,
            "provisional": score is not None and share < 0.5, "unavailable": unavailable, "per_metric": per}


# ---------------------------------------------------------------- reading the results

def _track(row):
    return row.get("analysis_track") or "short_read"


def _wmean(rows, column, weight_column=None):
    pairs = []
    for r in rows:
        v = rc.number(r.get(column))
        if v is None:
            continue
        w = rc.number(r.get(weight_column)) if weight_column else 1.0
        pairs.append((v, w if w is not None else 1.0))
    total = sum(w for _, w in pairs)
    if not pairs:
        return None
    return sum(v * w for v, w in pairs) / total if total else rc.mean([v for v, _ in pairs])


class Inputs:
    """Every table the scorecard reads, loaded once (None when a file is absent)."""

    def __init__(self, results_dir, scores_path):
        self.dir = results_dir
        self.scores = rc.read_tsv(scores_path)
        table = lambda name: rc.read_tsv(os.path.join(results_dir, "benchmark." + name + ".tsv"))  # noqa: E731
        self.accuracy = table("accuracy")
        self.features = table("feature_preservation")
        self.ngoc = table("ngoc")
        self.performance = table("performance")
        self.repeats = table("repeat_content")
        self.scenarios = table("scenarios")
        self._cache = {}

    def sample_file(self, sample, name):
        key = (sample, name)
        if key not in self._cache:
            path = os.path.join(self.dir, sample, name)
            self._cache[key] = rc.read_tsv(path) if name.endswith(".tsv") else rc.read_json(path)
        return self._cache[key]

    def repeat_rich(self, sample):
        """Truth repeat-rich plasmid ids of a sample, or None when no repeat table exists."""
        rows = self.repeats
        if rows is not None:
            rows = [r for r in rows if r.get("sample") == sample]
        if not rows:
            rows = self.sample_file(sample, "truth_repeat_content.tsv")
        if rows is None:
            return None
        return {r["sequence_id"] for r in rows if r.get("molecule_type") == "PLASMID" and r.get("repeat_rich") == "yes"}


def _result(value, reason="", n=0):
    return {"value": value, "reason": "" if value is not None else reason, "n": n}


def _tool_metrics(inp, track, tool, samples):
    """{id: result} for one (track, tool); `samples` is a set or None (all)."""
    keep = (lambda r: samples is None or r.get("sample") in samples)  # noqa: E731
    mine = lambda r: r.get("tool") == tool and _track(r) == track and keep(r)  # noqa: E731
    out = {}
    srows = [r for r in (inp.scores or []) if mine(r)]
    for sid, column in (("B1", "recall"), ("B2", "plasmid_recall_ge90"), ("B3", "plasmid_recall"),
                        ("C3", "complete_circular_plasmid_recall"), ("D1", "amr_gene_recall")):
        vals = [rc.number(r.get(column)) for r in srows]
        vals = [v for v in vals if v is not None]
        out[sid] = _result(rc.mean(vals), f"no isolate has a {column} value (undefined, not zero)", len(vals))
    acc = [r for r in (inp.accuracy or []) if mine(r)]
    why = "benchmark.accuracy.tsv is absent" if inp.accuracy is None else "no aligned columns for this tool"
    ident = _wmean(acc, "identity", "aligned_columns")
    mism = _wmean(acc, "mismatch_rate", "aligned_columns")
    ins, dele = _wmean(acc, "insertion_rate", "aligned_columns"), _wmean(acc, "deletion_rate", "aligned_columns")
    out["A1"] = _result(None if ident is None else ident * 100, why, len(acc))
    out["A2"] = _result(None if mism is None else mism * 100, why, len(acc))
    out["A3"] = _result(None if ins is None or dele is None else (1 - (ins + dele)) * 100, why, len(acc))
    for sid in ("A4", "C2"):
        out[sid] = _result(None, NOT_AVAILABLE[sid])
    out["C1"] = _structural(inp, track, tool, samples, mine)
    out["C4"] = _repeat_resolution(inp, track, tool, srows)
    out["D2"] = _annotation(inp, tool, srows)
    feats = [r for r in (inp.features or []) if mine(r) and (r.get("feature_kind") or "") in FUNCTIONAL_KINDS]
    d3 = _wmean(feats, "mean_covered_fraction", "n_expected")
    out["D3"] = _result(d3, "benchmark.feature_preservation.tsv is absent" if inp.features is None
                        else "no replicon, mobility or AMR element on the truth plasmids", len(feats))
    perf = [r for r in (inp.performance or []) if r.get("tool") == tool]
    for sid, column in (("E1", "median_runtime_seconds"), ("E2", "median_peak_memory_gb"), ("E3", "success_rate")):
        if samples is not None:
            out[sid] = _result(None, "a per-tool summary, not available per scenario")
        else:
            out[sid] = _result(rc.number(perf[0].get(column)) if perf else None,
                               "benchmark.performance.tsv is absent" if inp.performance is None else f"no {column}", 1)
    return out


def _structural(inp, track, tool, samples, mine):
    rows = [r for r in (inp.ngoc or []) if mine(r)]
    pairs = sum(rc.number(r.get("n_pairs")) or 0 for r in rows)
    if pairs:
        return _result(sum(rc.number(r.get("n_conserved")) or 0 for r in rows) / pairs, "", len(rows))
    collected = []
    for sample in sorted({r.get("sample") for r in (inp.scores or []) if mine(r)}):
        for r in inp.sample_file(sample, "structural_summary.tsv") or []:
            if r.get("tool") == tool:
                collected.append(r)
    value = _wmean(collected, "collinear_fraction", "aligned_bp")
    return _result(value, "no NGOC pairs and no structural_summary.tsv collinear fraction for this tool", len(collected))


def _repeat_resolution(inp, track, tool, srows):
    completeness, tracked = [], False
    for sample in sorted({r.get("sample") for r in srows}):
        rich = inp.repeat_rich(sample)
        if not rich:
            continue
        tracked = True
        for r in inp.sample_file(sample, f"{tool}.per_plasmid.tsv") or []:
            if r.get("sequence_id") in rich and _track(r) == track and rc.number(r.get("completeness")) is not None:
                completeness.append(rc.number(r["completeness"]))
    return _result(rc.mean(completeness), "no repeat-rich truth plasmid scored for this tool" if not tracked
                   else "repeat-rich plasmids have no per-plasmid result for this tool", len(completeness))


def _annotation(inp, tool, srows):
    hit = total = 0
    for sample in sorted({r.get("sample") for r in srows}):
        data = inp.sample_file(sample, os.path.join("visualization", "alignment_blocks.json"))
        projected = (((data or {}).get("tools") or {}).get(tool) or {}).get("protein_features") or []
        truth = (data or {}).get("protein_features") or []
        if not projected or not truth:
            continue
        for p in truth:
            length = max(1, p["end"] - p["start"])
            total += 1
            for f in projected:
                overlap = min(p["end"], f["end"]) - max(p["start"], f["start"])
                if f.get("sequence_id") == p.get("sequence_id") and overlap >= 0.5 * length \
                        and (f.get("projection_fraction") or 0) >= 0.9:
                    hit += 1
                    break
    return _result(hit / total if total else None,
                   "no predicted-protein annotation projected for this tool (coordinate-based, needs annotated predictions)", total)


def metric_values(results_dir, scores_path, samples=None, inputs=None):
    """{(track, tool): {metric id: {'value', 'reason', 'n'}}}; `samples` restricts the per-sample tables to those isolates."""
    inp = inputs or Inputs(results_dir, scores_path)
    pairs = sorted({(_track(r), r["tool"]) for r in (inp.scores or []) if r.get("tool")})
    return {(track, tool): _tool_metrics(inp, track, tool, None if samples is None else set(samples))
            for track, tool in pairs}


# ---------------------------------------------------------------- scenarios

def scenario_membership(rows, quality=None, min_depth=30.0):
    """{scenario: set of samples}, non-exclusive. `rows` are benchmark.scenarios.tsv rows; `quality` maps sample -> read_quality_band."""
    quality = quality or {}
    members = {name: set() for name in SCENARIOS}
    for r in rows or []:
        sample = r.get("sample")
        tags = {t.strip() for t in (r.get("tags") or "").split(",") if t.strip()}
        complex_ = bool(tags & set(COMPLEX_TAGS))
        depth = rc.number(r.get("read_depth_x"))
        if complex_:
            members["complex"].add(sample)
        if "annotated" in tags:
            members["annotated"].add(sample)
        if "low_depth" in tags or (quality.get(sample) or "").lower() == "low":
            members["challenging"].add(sample)
        if (rc.number(r.get("n_plasmids")) or 0) > 0 and not complex_ and depth is not None and depth >= min_depth:
            members["simple"].add(sample)
    return members


def underpowered(n, minimum=None):
    return n < (SCORECARD_MIN_SAMPLES if minimum is None else minimum)


def _quality_bands(samples_path):
    return {r.get("sample_id") or r.get("sample"): r.get("read_quality_band") for r in (rc.read_tsv(samples_path) or [])}


# ---------------------------------------------------------------- rendering

def _fmt_value(spec, value):
    if value is None:
        return None
    digits = 0 if spec["unit"] in ("seconds",) else (2 if spec["unit"] in ("percent", "GB") else 3)
    return f"{value:.{digits}f}"


def _cell(spec, entry):
    value = entry.get("value") if entry else None
    score, band = score_value(spec, value)
    if score is None:
        return rc.missing((entry or {}).get("reason") or "no data", "n/a")
    return rc.Raw(f"{rc.esc(_fmt_value(spec, value))} {rc.band_chip(band)} <span class='rpt-band-detail'>{score:.0f}</span>")


def _overall_cell(res):
    if res["score"] is None:
        return rc.missing("no metric could be scored")
    tail = " (provisional)" if res["provisional"] else ""
    return rc.Raw(f"<strong>{res['score']:.1f}</strong> {rc.band_chip(res['band'])}{rc.esc(tail)}")


def _ranked(specs, per_tool):
    results = {key: overall(specs, vals) for key, vals in per_tool.items()}
    order = sorted(results, key=lambda k: (results[k]["score"] is None, -(results[k]["score"] or 0), k[1]))
    return order, results


def profile_strip(specs, tool, res, values):
    """Inline SVG: one bar per metric (height = score), grouped A-E, with a <title> per bar."""
    bar, gap, group_gap, left, top, height = 13, 3, 10, 6, 14, 70
    width = left * 2
    x, xs, prev = left, [], None
    for spec in specs:
        if prev is not None and spec["group"] != prev:
            x += group_gap
        xs.append(x)
        x += bar + gap
        prev = spec["group"]
    width = x + left
    parts = [sv.svg_open(width, top + height + 22, f"Scorecard profile of {tool}",
                         "Bar height is the 0-100 score of each metric, grouped A to E; an empty dashed bar was not scored.")]
    parts.append(sv.line(left, top + height, width - left, top + height, "#888"))
    for spec, bx in zip(specs, xs):
        score, band = res["per_metric"][spec["id"]]
        entry = values.get(spec["id"]) or {}
        if score is None:
            title = f"{spec['id']} {spec['name']}: not available ({entry.get('reason') or 'no data'})"
            parts.append(f"<rect x='{sv.num(bx)}' y='{top}' width='{bar}' height='{height}' fill='none' stroke='#999' "
                         f"stroke-dasharray='2 2'><title>{sv.esc(title)}</title></rect>")
        else:
            h = max(1.0, height * score / 100.0)
            title = f"{spec['id']} {spec['name']}: {_fmt_value(spec, entry.get('value'))} {spec['unit']}, score {score:.0f}, {rc.BAND_LABELS[band]}"
            parts.append(f"<rect x='{sv.num(bx)}' y='{sv.num(top + height - h)}' width='{bar}' height='{sv.num(h)}' "
                         f"fill='{sv.OKABE_ITO['blue']}'><title>{sv.esc(title)}</title></rect>")
        parts.append(sv.text(bx + bar / 2, top + height + 10, spec["id"], 6.5, "middle"))
    for group in sorted({s["group"] for s in specs}):
        gx = [bx for s, bx in zip(specs, xs) if s["group"] == group]
        parts.append(sv.text((gx[0] + gx[-1] + bar) / 2, top - 4, group, 9, "middle", "bold"))
    parts.append(sv.svg_close())
    return "".join(parts)


def _intro(page):
    links = "See <a href='#rank-robustness'>ranking robustness</a>"
    if "id='composite'" in page:
        links += " and the <a href='#composite'>five-dimension composite</a>"
    return ("<strong>Another view, never the ranking.</strong> A weighted scorecard of 17 metrics, each turned into a 0-100 score "
            "by example thresholds that are mostly proposed, not standards. The leaderboard and the pre-specified endpoints are "
            f"unchanged. {links}.")


def _tool_table(specs, per_tool, order, results):
    headers = ["Rank", "Tool", "Overall", "Scored weight share"] + [f"{s['id']} {s['name']}" for s in specs]
    rows = []
    for i, key in enumerate(order, 1):
        res = results[key]
        rows.append([i if res["score"] is not None else "-", key[1], _overall_cell(res), f"{res['scored_share']:.2f}"]
                    + [_cell(s, per_tool[key].get(s["id"])) for s in specs])
    return rc.panel(headers, rows, "No tool was scored.", extra_class="rpt-scorecard")


def scorecard_section(page, specs, per_tool):
    if not per_tool:
        return rc.section("scorecard", "Benchmark scorecard", _intro(page),
                          rc.not_run("scores.tsv has no scored tool, so no scorecard can be computed."), group="Scoring")
    body = ""
    for track in sorted({k[0] for k in per_tool}):
        sub = {k: v for k, v in per_tool.items() if k[0] == track}
        order, results = _ranked(specs, sub)
        body += f"<h3>Analysis track: {rc.esc(track)}</h3>" + _tool_table(specs, sub, order, results)
        missing_all = sorted({(i, r) for k in order for i, r in results[k]["unavailable"]})
        shared = [(i, r) for i, r in missing_all if all(i in dict(results[k]["unavailable"]) for k in order)]
        if shared:
            body += rc.note("Not scored for any tool, and excluded from the overall: "
                            + "; ".join(f"{i} ({r})" for i, r in shared) + ".", "caution")
        if any(results[k]["provisional"] for k in order):
            body += rc.note("Provisional: the scored weight share is below 0.5 for at least one tool, so its overall rests on "
                            "fewer than half of the weights.")
        body += "<div class='rpt-grid'>" + "".join(
            f"<figure class='rpt-figure'>{profile_strip(specs, k[1], results[k], per_tool[k])}"
            f"<figcaption>{rc.esc(k[1])}: overall {'-' if results[k]['score'] is None else format(results[k]['score'], '.1f')}, "
            f"scored share {results[k]['scored_share']:.2f}</figcaption></figure>" for k in order) + "</div>"
    body += rc.note("Overall = weighted mean of the scored metrics with weights renormalised (a metric that cannot be scored is "
                    "left out, never counted as zero); the scored weight share says how much of the 100 weights it rests on. "
                    "Structural accuracy is alignment-derived and unvalidated; annotation concordance is coordinate-based, not "
                    "orthology; runtime is hardware-dependent.", "")
    return rc.section("scorecard", "Benchmark scorecard", _intro(page), body, group="Scoring")


def definitions_section(specs, error=None):
    lead = ("Example scoring definitions: the weights and bands behind the scorecard, read from <code>config/scorecard.tsv</code>. "
            "Status <em>fixed</em> is a stated definition; <em>proposed</em> is a default open to change; <em>undefined</em> means no bands exist yet, so the metric is shown as not available and cannot be graded. Score = piecewise linear "
            "through excellent 100, good 85, moderate 60, floor 0, clamped to 0-100.")
    if error:
        return rc.section("scorecard-definitions", "Scorecard definitions", lead, rc.not_run(error), group="Scoring")
    rows = [[s["id"], s["name"], s["weight"] and f"{s['weight']:g}", f"{s['direction']} is better", s["unit"]]
            + [f"{s[k]:g}" if s[k] is not None else rc.missing("no bands defined: needs a truth variant set and a panel decision", "undefined")
               for k in ("excellent", "good", "moderate", "floor")]
            + [s["status"], s.get("rationale", "")] for s in specs]
    body = rc.panel(["ID", "Metric", "Weight", "Direction", "Unit", "Excellent", "Good", "Moderate", "Floor (0)", "Status", "Rationale"],
                    rows, extra_class="rpt-scorecard")
    return rc.section("scorecard-definitions", "Scorecard definitions", lead, body, group="Scoring")


def scenarios_section(specs, inp, quality):
    lead = ("The scorecard restricted to isolates of one scenario. Scenarios overlap, so an isolate can appear in several. "
            f"Fewer than {SCORECARD_MIN_SAMPLES} isolates is flagged underpowered: read it as an illustration, not a result. "
            "Runtime, memory and success rate are per-tool summaries and are not scored here.")
    if inp.scenarios is None:
        return rc.section("scorecard-scenarios", "Scorecard by scenario", lead,
                          rc.not_run("benchmark.scenarios.tsv was not produced, so isolates cannot be assigned to scenarios."), group="Scoring")
    members = scenario_membership(inp.scenarios, quality)
    body = ""
    for name in SCENARIOS:
        samples = members[name]
        n = len(samples)
        flag = " <span class='rpt-band rpt-band-moderate'>underpowered</span>" if underpowered(n) else ""
        body += f"<h3>{rc.esc(name.capitalize())}: {n} isolate{'s' if n != 1 else ''}{flag}</h3>"
        if not samples:
            body += rc.note(f"No isolate is tagged {name} in this cohort.")
            continue
        per_tool = metric_values(inp.dir, None, samples, inputs=inp)
        order, results = _ranked(specs, per_tool)
        rows = [[k[0], k[1], _overall_cell(results[k]), f"{results[k]['scored_share']:.2f}", n] for k in order]
        body += rc.panel(["Track", "Tool", "Overall", "Scored weight share", "Isolates (n)"], rows, "No tool was scored here.")
    return rc.section("scorecard-scenarios", "Scorecard by scenario", lead, body, group="Scoring")


def inject(page, results_dir, scores_path, config_path=None, samples_path=None):
    """Add the scorecard sections before Recommendations (and nav links); every failure is a visible 'Not run'."""
    try:
        specs, error = load_config(config_path), None
    except ValueError as exc:
        specs, error = [], str(exc)
    inp = Inputs(results_dir, scores_path)
    if error:
        reason = f"the scorecard configuration is invalid: {error}"
        sections = [rc.section("scorecard", "Benchmark scorecard", _intro(page), rc.not_run(reason), group="Scoring"),
                    definitions_section([], reason),
                    rc.section("scorecard-scenarios", "Scorecard by scenario", "", rc.not_run(reason), group="Scoring")]
    else:
        per_tool = metric_values(results_dir, scores_path, inputs=inp) if inp.scores else {}
        if not inp.scores:
            reason = "scores.tsv is absent or empty, so no tool was scored."
            scen = rc.section("scorecard-scenarios", "Scorecard by scenario", "", rc.not_run(reason), group="Scoring")
        else:
            samples_path = samples_path or os.path.join(results_dir, "samples.tsv")
            scen = scenarios_section(specs, inp, _quality_bands(samples_path))
        sections = [scorecard_section(page, specs, per_tool), definitions_section(specs), scen]
    page = rc.add_style(page)
    return rc.inject_sections(page, "".join(sections), SECTIONS)
