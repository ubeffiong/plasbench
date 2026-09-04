#!/usr/bin/env python3
"""Select an already-produced candidate for an operational sample without truth."""
import argparse, csv, json, shutil
from datetime import datetime, timezone
from pathlib import Path


def rows(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def choose_recommendation(recommendation_rows, organism, gram_group):
    """Return the evidence-gated primary-tool row for the most specific
    matching scope (organism, then gram_group, then overall), or None.

    select_operational_method.py's write_recommendations() only ever marks a
    row recommendation == "primary" once it has already passed the
    coverage/sample-count eligibility gate (see its `eligible()` check before
    picking a `winner`) -- there is no separate "state" column recording that,
    so checking `recommendation` alone is both necessary and sufficient.
    """
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
    parser.add_argument("--tool-only", action="store_true",
                        help="Print just the recommended tool name and exit 0, or exit 1 with no "
                             "output if none is eligible. Writes no report; does not need "
                             "--sample-id/--results-dir. For deciding which single tool to run "
                             "on a brand-new sample, before any prediction FASTA exists.")
    args = parser.parse_args()
    chosen = choose_recommendation(rows(args.recommendations), args.organism, args.gram_group)

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
        report.update({"operational_recommendation": chosen, "selected_tool": tool,
                       "selection_reason": f"Eligible {chosen.get('scope')} benchmark recommendation for {chosen.get('group')}."})
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
