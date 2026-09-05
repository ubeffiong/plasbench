#!/usr/bin/env python3
"""Select an already-produced candidate for an operational sample without truth."""
import argparse, csv, json, shutil, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from recommendation_model import decision_score, load_model  # noqa: E402


def rows(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def live_model_recommendation(recommendation_rows, model, organism, gram_group, read_depth_x):
    """Predict every 'overall'-eligible tool's F1/plasmid_recall directly
    from this isolate's own features (rather than looking up a discrete
    scope), combine with that tool's historical precision/recall/bin-score/
    failure-rate via the shared decision_score(), and pick the argmax.

    structural_penalty/resource_penalty are 0.0 here, not a stand-in for a
    missing value: a genuinely new isolate has no unmapped_pred_bp/
    split_events/runtime/memory yet, since nothing has run on it -- there is
    nothing else honest to feed those terms.

    Reuses the *existing* "overall" eligibility (eligible=="true"), so a tool
    nobody validated is never live-recommended just because the model has an
    opinion about it. Returns a recommendation-row-shaped dict (same keys an
    eligible row already has), or None if no "overall" row is eligible.
    """
    candidates = [row for row in recommendation_rows if row.get("scope") == "overall" and row.get("eligible") == "true"]
    if not candidates:
        return None
    best = None
    for row in candidates:
        features = {"tool": row["tool"], "organism": organism or "not_recorded", "gram_group": gram_group or "not_recorded",
                    "amr_status": "not_recorded", "read_depth_x": read_depth_x,
                    "true_plasmid_bp": None, "true_plasmid_count": None}
        f1 = model.predict("f1", features)
        plasmid = model.predict("plasmid_recall", features)
        precision = float(row.get("mean_precision") or 0.0)
        recall = float(row.get("mean_recall") or 0.0)
        bin_score = float(row["mean_bin_f1"]) if row.get("mean_bin_f1") else None
        failure_rate = float(row.get("failure_rate") or 0.0)
        score = decision_score(f1, precision, recall, plasmid, bin_score, failure_rate, 0.0, 0.0)
        if best is None or score > best[0]:
            best = (score, dict(row))
    if best is None:
        return None
    chosen = best[1]
    chosen["reason"] = "model-fitted, per-isolate prediction from read_depth_x/organism/gram_group"
    return chosen


def choose_recommendation(recommendation_rows, organism, gram_group, model=None, read_depth_x=None):
    """Return the evidence-gated primary-tool row for the most specific
    matching scope (organism, then gram_group, then overall), or None.

    select_operational_method.py's write_recommendations() only ever marks a
    row recommendation == "primary" once it has already passed the
    coverage/sample-count eligibility gate (see its `eligible()` check before
    picking a `winner`) -- there is no separate "state" column recording that,
    so checking `recommendation` alone is both necessary and sufficient.

    When a ready model is given, live per-isolate prediction (this isolate's
    own features, not a discrete stratum lookup) takes priority -- it is
    strictly more informative than the fallback below. Falls back to the
    exact unchanged scope-lookup when the model is absent/not ready, so
    behavior is identical to before this feature existed whenever it isn't
    explicitly used.
    """
    if model is not None:
        live = live_model_recommendation(recommendation_rows, model, organism, gram_group, read_depth_x)
        if live:
            return live
    eligible = [row for row in recommendation_rows if row.get("recommendation") == "primary"]
    for scope, group in (("organism", organism), ("gram_group", gram_group), ("overall", "all")):
        if not group:
            continue
        chosen = next((row for row in eligible if row.get("scope") == scope and row.get("group") == group), None)
        if chosen:
            return chosen
    return None


def main():
    parser = argparse.ArgumentParser(description="Use validated benchmark recommendations for a truth-unknown sample.")
    parser.add_argument("--recommendations", type=Path, required=True)
    parser.add_argument("--sample-id", help="Required unless --tool-only is used.")
    parser.add_argument("--results-dir", type=Path, help="Required unless --tool-only is used.")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--organism", default="")
    parser.add_argument("--gram-group", default="")
    parser.add_argument("--analysis-track", choices=("short_read", "long_read", "hybrid"), default="short_read")
    parser.add_argument("--recommendation-model", help="Optional fitted recommendation-model JSON (fit_recommendation_model.py). "
                                                        "When ready, predicts directly from this isolate's own features "
                                                        "instead of a discrete scope lookup. Ignored (falls back to the "
                                                        "unchanged scope lookup) when omitted or not model_ready.")
    parser.add_argument("--read-depth-x", type=float, help="This isolate's own read depth, if known, for live model prediction.")
    parser.add_argument("--tool-only", action="store_true",
                        help="Print just the recommended tool name and exit 0, or exit 1 with no "
                             "output if none is eligible. Writes no report; does not need "
                             "--sample-id/--results-dir. For deciding which single tool to run "
                             "on a brand-new sample, before any prediction FASTA exists.")
    args = parser.parse_args()
    model = None
    if args.recommendation_model:
        model, model_ready, _ = load_model(args.recommendation_model)
        model = model if model_ready else None
    chosen = choose_recommendation(rows(args.recommendations), args.organism, args.gram_group, model=model, read_depth_x=args.read_depth_x)

    if args.tool_only:
        if not chosen:
            raise SystemExit(1)
        print(chosen.get("tool", ""))
        return

    if not args.sample_id or not args.results_dir:
        raise SystemExit("ERROR: --sample-id and --results-dir are required unless --tool-only is used.")
    sample_dir = args.results_dir / args.sample_id
    out = args.out or sample_dir / "selection_report.json"
    report = {"sample": args.sample_id, "generated_at": datetime.now(timezone.utc).isoformat(), "truth_available": False,
              "selection_type": "operational_method_recommendation_only", "analysis_track": args.analysis_track,
              "confidence_tier": "confirmation_required", "long_read_confirmation_required": True,
              "organism": args.organism, "gram_group": args.gram_group,
              "limitations": ["No reference truth was available for per-isolate scoring.", "This is a benchmark-derived method choice, not sequence confirmation.", "Confirm structural or high-consequence AMR findings with long-read or hybrid evidence."]}
    if chosen:
        tool = chosen.get("tool", "")
        pred = sample_dir / f"pred_{tool}.plasmid.fasta"
        model_reason = chosen.get("reason", "")
        selection_reason = (model_reason if model_reason.startswith("model-fitted")
                            else f"Eligible {chosen.get('scope')} benchmark recommendation for {chosen.get('group')}.")
        report.update({"operational_recommendation": chosen, "selected_tool": tool,
                       "selection_reason": selection_reason})
        if pred.is_file():
            selected = sample_dir / "selected_candidate"
            selected.mkdir(parents=True, exist_ok=True)
            shutil.copy2(pred, selected / "candidate.plasmid.fasta")
            report["selected_candidate_fasta"] = "selected_candidate/candidate.plasmid.fasta"
        else:
            report["selection_reason"] += " Prediction FASTA was not found; run the nominated tool first."
    else:
        report.update({"selected_tool": "", "selection_reason": "No evidence-gated recommendation matched this metadata; do not select a reconstruction automatically."})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
