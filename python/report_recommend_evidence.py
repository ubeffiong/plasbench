#!/usr/bin/env python3
"""
report_recommend_evidence.py -- the evidence panel under the operational recommendation (plan D5).

A recommendation is a claim; this lists what stands behind it, from tables the report already holds (nothing is computed here):

  Expected performance   the tool's mean F1 over the isolates it was scored on, how many, and its decision score (recommendations table)
  Independent studies    the independent clusters behind its ranking (leaderboard n_independent_clusters)
  Reference quality      how many isolates sit on each reference tier, and how many of the six evidence fields were recorded (truth provenance)
  Dataset similarity     what the recommendation covers (isolates, organisms) and whether choosing by similar isolates beat the single best tool
                         (the three-way recommender evaluation); a recommendation for the cohort is not a prediction for a new isolate
  Uncertainty            the interval of the ranking score and whether the lead over the runner-up is significant
  Reason withheld        why there is no recommendation, when there is none, or why the headline is only provisional

When no tool is recommended the panel is still shown, with the reason; a missing table is reported as "not recorded", never as a number.
"""
import html


def _esc(value):
    return html.escape(str(value), quote=True)


def _num(value):
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def reference_quality(provenance):
    """'tier 1: n, tier 2: n, tier 3: n; evidence recorded: x of 6 on average' from the truth-provenance rows, or None when there are none."""
    if not provenance:
        return None
    tiers = {}
    for row in provenance:
        tiers[row.get("reference_tier") or "unknown"] = tiers.get(row.get("reference_tier") or "unknown", 0) + 1
    recorded = [int(str(r.get("evidence_recorded", "")).split(" of ")[0]) for r in provenance if str(r.get("evidence_recorded", "")).split(" of ")[0].isdigit()]
    text = ", ".join(f"tier {t}: {n}" for t, n in sorted(tiers.items()))
    if recorded:
        text += f"; evidence fields recorded: {sum(recorded) / len(recorded):.1f} of 6 on average"
    return text


def organisms(features):
    return sorted({r.get("organism") for r in features if r.get("organism")})


def card(row, board, provenance, features, verdict):
    tool = row.get("tool")
    lb = next((r for r in board if r.get("tool") == tool), {})
    f1, n, coverage = _num(row.get("mean_f1")), row.get("n_scored"), _num(row.get("coverage"))
    expected = (f"mean F1 {f1:.3f} over {n} scored isolate(s)" + (f" (coverage {coverage:.0%})" if coverage is not None else "")
                + (f"; decision score {row.get('decision_score')}" if row.get("decision_score") else "")) if f1 is not None else "not recorded"
    clusters = lb.get("n_independent_clusters")
    studies = f"{clusters} independent cluster(s)" if clusters not in (None, "") else "not recorded"
    if lb.get("ranking_ci_low"):
        interval = f"ranking score {lb.get('ranking_score')} (95% CI {lb['ranking_ci_low']} to {lb['ranking_ci_high']})"
    else:
        interval = "no interval: fewer than five independent units"
    if lb.get("significant_vs_runner_up"):
        interval += f"; lead over the runner-up: {lb['significant_vs_runner_up']}"
    orgs = organisms(features)
    arms = (verdict or {}).get("arms") or {}
    transfer = (f"choosing by similar isolates: {arms['feature_conditioned'].replace('_', ' ')}" if arms.get("feature_conditioned") else "choosing by similar isolates: not evaluated")
    similarity = (f"a recommendation for this cohort as a whole ({len(features) or 'unknown number of'} isolates"
                  + (f"; organisms: {', '.join(orgs)}" if orgs else "") + f"), not a prediction for a new isolate; {transfer}")
    return [("Recommended tool", _esc(tool)), ("Expected performance", _esc(expected)), ("Independent studies", _esc(studies)),
            ("Reference quality", _esc(reference_quality(provenance) or "not recorded")), ("Dataset similarity", _esc(similarity)), ("Uncertainty", _esc(interval))]


def withheld_reason(recommendations, board):
    """Why nothing is recommended or why the headline is provisional, or None."""
    primaries = [r for r in recommendations if r.get("scope") == "overall" and r.get("recommendation") == "primary"]
    status = next((r.get("primary_status") for r in board if r.get("primary_status")), "")
    reasons = []
    if not primaries:
        top = next((r for r in recommendations if r.get("scope") == "overall"), None)
        reasons.append("no tool met the coverage gate" + (f" ({top.get('reason')})" if top and top.get("reason") else ""))
    if status and status != "available":
        reasons.append(f"the primary analysis is {status.replace('_', ' ')}: no reference of tier 1 or 2 supports the headline, so the ranking is provisional")
    return "; ".join(reasons) or None


def panel_html(recommendations, board, provenance, features, verdict):
    primaries = [r for r in recommendations if r.get("scope") == "overall" and r.get("recommendation") == "primary"]
    reason = withheld_reason(recommendations, board)
    parts = ["<h3>Evidence behind the recommendation</h3>"]
    if not recommendations:
        parts.append("<p class='muted'>Not run: no recommendations table was available, so there is no evidence to list.</p>")
    for row in primaries[:1]:
        rows = card(row, board, provenance, features, verdict)
        parts.append("<div class='panel'><table class='rec-evidence'><tbody>" + "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in rows)
                     + f"<tr><th>Reason withheld or caveat</th><td>{_esc(reason) if reason else 'none: the coverage gate was met'}</td></tr></tbody></table></div>")
    if recommendations and not primaries:
        parts.append(f"<div class='panel'><p><strong>No tool is recommended.</strong> {_esc(reason or 'no reason recorded')}.</p></div>")
    return "".join(parts)
