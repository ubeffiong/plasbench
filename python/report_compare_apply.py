#!/usr/bin/env python3
"""
report_compare_apply.py -- turn the report's metric-by-tool tables into comparison tables (python/report_compare_table.py), keeping each original table.

Each function takes what the report already computed for the table (its rows as the text the table shows, the leaderboard rows, scores.tsv) and returns
HTML: the comparison component(s) followed by the original table in a closed "Table" fold. The text shown in a comparison cell IS the text of the table
cell (the same strings are passed to both), so the panel and the table cannot disagree. A direction comes from the metric registry
(report_compare_table.resolve) or is stated below with its reason; a metric with neither is shown unshaded and says "direction not defined".

  leaderboard(rows, texts, scores, table_html, label)   the ranking table of one track and task
  graded_recovery(rows, scores, table_html, label)      plasmid recall at 50% and 90% completeness, and complete circular recall
  scoring_additions(rows, scores, table_html, label)    F1 macro and micro, MCC, F2, F0.5, abstention
  plasmid_outcomes(rows, scores, table_html, label)     perfect / fragmented / merged / partial / missed counts and ARI
  contig_layer(rows, scores, table_html, label)         the contig layer beside the base layer
  from_table(...)                                       the generic form used by the dimension tables (accuracy, bin quality, performance, composite, features)

Standard library only.
"""
import re

import report_compare_table as ct

parse_display = ct.num_display


def fold(table_html, title="Table"):
    return f"<details class='ct-fold rpt-collapsible' data-closed='1'><summary>{ct.esc(title)}</summary>{table_html}</details>" if table_html else ""


def _slug(*parts):
    return re.sub(r"[^A-Za-z0-9]+", "-", "-".join(str(p) for p in parts if p)).strip("-").lower()


def dash(key):
    """The text report_scoring_spec.table shows for a blank: a dash."""
    return lambda r: r.get(key) if r.get(key) not in (None, "") else "-"


def _spec(group, mid, name, get, **kw):
    out = {"group": group, "id": mid, "name": name, "get": get}
    out.update(kw)
    return out


def _isolate_values(scores, column, transform=None):
    return lambda r: ct.scores_iso(scores, r.get("analysis_track") or "short_read", r.get("tool", ""), column, transform)


def _cprr_iso(scores):
    def get(r):
        out = {}
        for s in scores or []:
            if s.get("tool") != r.get("tool") or (s.get("analysis_track") or "short_read") != (r.get("analysis_track") or "short_read"):
                continue
            total, hit = ct.num(s.get("cprr_plasmids")), ct.num(s.get("cprr_correct"))
            if total and hit is not None:
                out[s.get("sample", "")] = hit / total
        return out
    return get


def _col_args(label):
    return dict(col_id=lambda r: f"{r.get('analysis_track', '')}|{r.get('task', '')}|{r.get('tool', '')}", col_label=lambda r: r.get("tool", ""), label=label)


def isolate_anchor(sample):
    """The id of an isolate's first row in the All sample-tool scores table."""
    return "sr-" + _slug(sample)


def isolate_link(sample):
    return "#" + isolate_anchor(sample)


def leaderboard(rows, texts, scores, table_html, label=None):
    """`rows` the leaderboard rows of one track and task, `texts(row)` the strings the table shows for a row (a dict, see build_html_report)."""
    if not rows:
        return table_html
    first = rows[0]
    cid = "lb-" + _slug(first.get("analysis_track"), first.get("task"))
    shown = {id(r): texts(r) for r in rows}
    g = lambda key: (lambda r: shown[id(r)][key])  # noqa: E731
    pair = lambda a, b: (lambda r: (ct.num(r.get(a)) if ct.num(r.get(b)) else None))  # noqa: E731
    specs = [
        _spec("Run outcome", "scored", "Scored isolates", g("scored"), dir=None, definition="How many isolates were scored for this tool. A count, not a quality measure.", source="leaderboard", column="n_samples"),
        _spec("Run outcome", "completed", "Completed runs", g("completed"), dir=None, definition="Runs that finished. A count, not a quality measure.", source="leaderboard", column="n_completed"),
        _spec("Run outcome", "failed", "Failed runs", g("failed"), dir=None, definition="Runs that failed. Shown unshaded: failures are also kept in the table fold and the health section.", source="leaderboard", column="n_failed"),
        _spec("Run outcome", "skipped", "Skipped runs", g("skipped"), dir=None, definition="Runs not attempted (for example the tool does not apply to the isolate).", source="leaderboard", column="n_skipped"),
        _spec("Base-level accuracy", "precision", "Mean precision", g("precision"), source="leaderboard", column="mean_precision", n="n_samples", iso=_isolate_values(scores, "precision")),
        _spec("Base-level accuracy", "recall", "Mean base recall", g("recall"), source="leaderboard", column="mean_recall", n="n_samples", iso=_isolate_values(scores, "recall")),
        _spec("Base-level accuracy", "f1", "Mean base F1", g("f1"), source="leaderboard", column="mean_f1", n="n_samples", iso=_isolate_values(scores, "f1")),
        _spec("Plasmid recovery", "plasmid_recall", "Mean plasmid recall", g("plasmid_recall"), source="leaderboard", column="mean_plasmid_recall", n="n_samples", iso=_isolate_values(scores, "plasmid_recall")),
        _spec("Plasmid recovery", "perfect", "Perfect reference recovery", g("perfect"), registry_id="perfect_recovery", value=pair("reference_perfect_recovery_rate", "n_reference_perfect_assessed"), n="n_reference_perfect_assessed"),
        _spec("Plasmid recovery", "strict", "Strict reconstruction", g("strict"), registry_id="strict_reconstruction", value=pair("strict_reference_reconstruction_rate", "n_strict_reconstruction_assessed"), n="n_strict_reconstruction_assessed"),
        _spec("Plasmid recovery", "cprr", "CPRR", g("cprr"), registry_id="cprr", value=lambda r: ct.num(r.get("cprr")), n="cprr_plasmids", iso=_cprr_iso(scores),
              note="The cell shows the table's text (the share, its counts and the other recovery rates); the shade ranks the share."),
        _spec("Binning", "bin_f1", "Mean bin F1 (count-based)", g("bin_f1"), source="leaderboard", column="mean_bin_f1", n="n_bin_scored", iso=_isolate_values(scores, "bin_f1")),
        _spec("Binning", "nmi", "Mean NMI", g("nmi"), source="leaderboard", column="mean_nmi", n="n_bin_scored", iso=_isolate_values(scores, "nmi")),
        _spec("Binning", "vi", "Mean VI", g("vi"), source="leaderboard", column="mean_variation_of_information", n="n_bin_scored", iso=_isolate_values(scores, "variation_of_information")),
        _spec("Binning", "pr_auc", "Mean PR-AUC", g("pr_auc"), source="leaderboard", column="mean_pr_auc", n="n_pr_scored", iso=_isolate_values(scores, "pr_auc")),
        _spec("Ranking", "ranking_score", "Ranking score", g("score"), dir="higher", value=lambda r: ct.num(shown[id(r)]["score"]),
              definition="The value this track and task are ranked by (the ranking metric of the headline design). Higher is better.", source="leaderboard", column="ranking_score",
              n="n_ranking_samples", lo="ranking_ci_low", hi="ranking_ci_high"),
    ]
    out = ct.from_rows(cid, f"Leaderboard: {first.get('analysis_track', '')} {first.get('task', '')}".strip(), rows, specs,
                       col_track=lambda r: "", col_task=lambda r: (f"rank {r['rank']}" if r.get("rank") else ""), isolate_href=isolate_link,
                       lead="Tools in rank order. Rank, 95% CI and the significance against the runner-up are in the Table below; the interval of the ranking score is in the panel.",
                       **_col_args(label))
    return out + fold(table_html)


def _simple(rows, scores, table_html, label, cid_base, title, specs, lead=""):
    """One component per track and task (tools of different tracks are never ranked together), then the original table once."""
    if not rows:
        return table_html
    blocks, order = {}, []
    for r in rows:
        key = (r.get("analysis_track") or "", r.get("task") or "")
        if key not in blocks:
            blocks[key] = []
            order.append(key)
        blocks[key].append(r)
    out = []
    for key in order:
        suffix = " ".join(x for x in key if x)
        out.append(ct.from_rows(_slug(cid_base, *key), f"{title}{': ' + suffix if suffix else ''}", blocks[key], specs, col_task=lambda r: "", isolate_href=isolate_link,
                                lead=lead if key == order[0] else "", **_col_args(label)))
    return "".join(out) + fold(table_html)


def graded_recovery(rows, scores, table_html, label=None):
    def text(r, key, tier=None):
        v = ct.num(r.get(key))
        return f"{v:.3f}" if v is not None else ("not assessed" if tier else "not annotated")
    specs = [
        _spec("Graded recovery", "ge50", "Recall, plasmids at least 50% recovered", lambda r: text(r, "mean_plasmid_recall_ge50"), source="leaderboard", column="mean_plasmid_recall_ge50", registry_id="recall_ge50", iso=_isolate_values(scores, "plasmid_recall_ge50")),
        _spec("Graded recovery", "ge90", "Recall, plasmids at least 90% recovered", lambda r: text(r, "mean_plasmid_recall_ge90"), source="leaderboard", column="mean_plasmid_recall_ge90", registry_id="recall_ge90", iso=_isolate_values(scores, "plasmid_recall_ge90")),
        _spec("Graded recovery", "circ", "Complete and circular recall", lambda r: text(r, "mean_complete_circular_plasmid_recall") if (ct.num(r.get("n_complete_circular_assessed")) or 0) > 0 else "not assessed",
              registry_id="circular_recall", n="n_complete_circular_assessed", iso=_isolate_values(scores, "complete_circular_plasmid_recall"),
              note="Shown only for tools with circular-truth evidence; 'not assessed' is not zero."),
    ]
    return _simple(rows, scores, table_html, label, "graded", "Graded plasmid recovery", specs)


def scoring_additions(rows, scores, table_html, label=None):
    specs = [
        _spec("Base-level F1", "f1_macro", "F1 (macro)", dash("mean_f1"), source="leaderboard", column=dash("mean_f1"), iso=_isolate_values(scores, "f1")),
        _spec("Base-level F1", "f1_micro", "F1 (micro)", dash("micro_f1"), registry_id="base_f1", definition="Base-level F1 pooled over all bases rather than averaged over isolates."),
        _spec("Base-level F1", "mcc", "MCC", dash("mean_mcc"), source="leaderboard", column=dash("mean_mcc"), iso=_isolate_values(scores, "mcc")),
        _spec("Base-level F1", "f2", "F2 (recall-weighted)", dash("mean_f2"), source="leaderboard", column=dash("mean_f2"), iso=_isolate_values(scores, "f2")),
        _spec("Base-level F1", "f05", "F0.5 (precision-weighted)", dash("mean_f0_5"), registry_id="f_beta", iso=_isolate_values(scores, "f0_5")),
        _spec("Abstention", "abstain", "Abstention rate", dash("mean_abstention_rate"), dir=None, definition="The share of isolates on which the tool returned nothing. Whether that is good depends on whether the isolate had plasmids, so it is not shaded.",
              iso=_isolate_values(scores, "abstention_rate")),
    ]
    return _simple(rows, scores, table_html, label, "additions", "MCC, F2, F0.5 and abstention", specs)


def plasmid_outcomes(rows, scores, table_html, label=None):
    count = dash
    specs = [
        _spec("Outcome counts (summed over isolates)", "perfect", "Perfect", count("total_outcome_perfect"), dir="higher", definition="Truth plasmids whose best bin is precise and complete enough (perfect). More is better.", source="scores", column="outcome_perfect", iso=_isolate_values(scores, "outcome_perfect")),
        _spec("Outcome counts (summed over isolates)", "fragmented", "Fragmented", count("total_outcome_fragmented"), dir="lower", definition="Truth plasmids split over several bins. Fewer is better.", source="scores", column="outcome_fragmented", iso=_isolate_values(scores, "outcome_fragmented")),
        _spec("Outcome counts (summed over isolates)", "merged", "Merged", count("total_outcome_merged"), dir="lower", definition="Truth plasmids whose bin also holds another plasmid. Fewer is better.", source="scores", column="outcome_merged", iso=_isolate_values(scores, "outcome_merged")),
        _spec("Outcome counts (summed over isolates)", "fm", "Fragmented and merged", count("total_outcome_fragmented_and_merged"), dir="lower", source="scores", column="outcome_fragmented_and_merged", iso=_isolate_values(scores, "outcome_fragmented_and_merged")),
        _spec("Outcome counts (summed over isolates)", "partial", "Partial", count("total_outcome_partial"), dir=None, source="scores", column="outcome_partial", iso=_isolate_values(scores, "outcome_partial"),
              definition="Truth plasmids in none of the other states. A count with no stated direction."),
        _spec("Outcome counts (summed over isolates)", "missed", "Missed", count("total_outcome_missed"), dir="lower", definition="Truth plasmids no bin recovered. Fewer is better.", source="scores", column="outcome_missed", iso=_isolate_values(scores, "outcome_missed")),
        _spec("Agreement", "ari", "ARI", count("mean_bin_ari"), dir="higher", definition="Adjusted Rand index of the bins against the truth (1 is identical). Higher is better.", source="scores", column="bin_ari", iso=_isolate_values(scores, "bin_ari")),
    ]
    return _simple(rows, scores, table_html, label, "outcomes", "Per-plasmid outcomes", specs,
                   lead="Counts depend on how many plasmids each isolate holds, so compare tools within this table only.")


def contig_layer(rows, scores, table_html, label=None, exclusion=None):
    specs = [
        _spec("Base layer", "base_f1", "Base F1 (reference layer)", dash("mean_f1"), source="leaderboard", column=dash("mean_f1"), iso=_isolate_values(scores, "f1")),
        _spec("Contig layer", "contig_f1", "Contig F1 (length)", dash("mean_contig_f1_bp"), dir="higher", definition="F1 of the contig calls, weighted by contig length. Not comparable with base-level F1.", source="scores", column="contig_f1_bp", iso=_isolate_values(scores, "contig_f1_bp")),
        _spec("Contig layer", "contig_mcc", "Contig MCC (length)", dash("mean_contig_mcc_bp"), dir="higher", source="scores", column="contig_mcc_bp", iso=_isolate_values(scores, "contig_mcc_bp"), definition="Matthews correlation of the contig calls, weighted by length."),
        _spec("Contig layer", "contig_bin_f1", "Contig binning F1 (length)", dash("mean_contig_bin_f1_bp"), dir="higher", source="scores", column="contig_bin_f1_bp", iso=_isolate_values(scores, "contig_bin_f1_bp"), definition="Binning F1 of the contigs, weighted by length."),
    ]
    if exclusion:
        specs.append(_spec("Contigs left out", "excluded", "Contigs excluded from contig F1", lambda r: exclusion(r), dir=None, value=lambda r: None, text=True,
                           definition="The share of contigs left out of the contig F1 (ambiguous, unplaced, chimeric or too short). Text only; kept in the table."))
    return _simple(rows, scores, table_html, label, "contig", "Contig layer beside the base layer", specs,
                   lead="Contig F1 and base F1 are different layers and are not comparable: read each against the other tools, not against each other.")


# ------------------------------------------------------------------------------------------------ the generic form
def from_table(cid, title, rows, tool_col, specs, track_col=None, block_cols=(), table_html="", label=None, lead="", scores=None, ncols=None):
    """One component per block of `rows` (a block is one track and any extra `block_cols`, never pooled across tracks), then one Table fold.

    rows        the table body as lists of the text shown (one row per tool)
    tool_col    index of the tool in a row; track_col the index of the track; block_cols further indexes that start a new block (a feature kind)
    specs       [(group, header_index, id, name, kwargs)] with kwargs as in report_compare_table.from_rows (source, column, registry_id, dir, definition, unit, note, n)
                n and iso here are functions of (track, tool) -> value
    """
    if not rows:
        return table_html
    blocks, order = {}, []
    for r in rows:
        key = tuple([r[track_col] if track_col is not None else ""] + [r[i] for i in block_cols])
        if key not in blocks:
            blocks[key] = []
            order.append(key)
        blocks[key].append(r)
    out = []
    for key in order:
        brow = blocks[key]
        ident = lambda r: (r[track_col] if track_col is not None else "", r[tool_col])  # noqa: E731
        sp = []
        for group, idx, mid, name, kw in specs:
            kw = dict(kw)
            iso = kw.pop("iso", None)
            n = kw.pop("n", None)
            sp.append(dict(_spec(group, mid, name, (lambda r, i=idx: r[i])), **kw, **({"iso": (lambda r, f=iso: f(*ident(r)))} if iso else {}),
                           **({"n": (lambda r, f=n: f(*ident(r)))} if n else {})))
        suffix = " ".join(x for x in key if x)
        out.append(ct.from_rows(_slug(cid, *key), f"{title}{': ' + suffix if suffix else ''}", brow, sp, col_id=lambda r: "|".join(str(x) for x in ident(r)),
                                col_label=lambda r: r[tool_col], col_track=lambda r: "", label=label, lead=lead if key == order[0] else "", isolate_href=isolate_link))
    return "".join(out) + fold(table_html)


def features(rows, table_html, label=None):
    """Feature preservation: one component per track, a group of rows per feature kind (rows are [track, tool, kind, expected, full, truncated, missed, rate, covered])."""
    if not rows:
        return table_html
    out, tracks = [], []
    for r in rows:
        if r[0] not in tracks:
            tracks.append(r[0])
    for track in tracks:
        block = [r for r in rows if r[0] == track]
        tools, kinds = [], []
        for r in block:
            if r[1] not in tools:
                tools.append(r[1])
            if r[2] not in kinds:
                kinds.append(r[2])
        cols = [ct.column(t, t, "", "") for t in tools]
        groups, cells = [], {}
        for kind in kinds:
            ms = [ct.metric(f"{kind}.expected", "Expected features", "Truth features of this kind expected in the recovered sequence. A count: it depends on the references, so it is not shaded.", None),
                  ct.metric(f"{kind}.rate", "Full-length rate", "Share of expected features covered at least 95%. Higher is better.", "higher", source="feature_preservation", column="full_length_rate"),
                  ct.metric(f"{kind}.covered", "Mean covered fraction", "", "auto", source="feature_preservation", column="mean_covered_fraction")]
            groups.append({"title": f"Feature kind: {kind}", "metrics": ms})
            for r in block:
                if r[2] != kind:
                    continue
                for m, idx in zip(ms, (3, 7, 8)):
                    cells[(m["id"], r[1])] = ct.cell(r[idx])
        out.append(ct.build(_slug("features", track), f"Feature preservation: {track}", groups, cols, cells, label=label, isolate_href=None,
                            lead="Expected, full length, truncated and missed counts for every kind are in the Table below." if track == tracks[0] else ""))
    return "".join(out) + fold(table_html)
