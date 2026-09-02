#!/usr/bin/env python3
"""Select an already-produced candidate for an operational sample without truth."""
import argparse, csv, json, shutil
from datetime import datetime, timezone
from pathlib import Path


def rows(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def main():
    parser = argparse.ArgumentParser(description="Use validated benchmark recommendations for a truth-unknown sample.")
    parser.add_argument("--recommendations", type=Path, required=True)
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--organism", default="")
    parser.add_argument("--gram-group", default="")
    parser.add_argument("--analysis-track", choices=("short_read", "long_read", "hybrid"), default="short_read")
    args = parser.parse_args()
    eligible = [row for row in rows(args.recommendations) if row.get("recommendation") == "primary" and row.get("state") == "eligible_operational_method"]
    track_rows = [row for row in eligible if row.get("analysis_track", args.analysis_track) == args.analysis_track]
    eligible = track_rows or eligible
    chosen = None
    for scope, group in (("organism", args.organism), ("gram_group", args.gram_group), ("overall", "all")):
        chosen = next((row for row in eligible if row.get("scope") == scope and row.get("group") == group), None)
        if chosen:
            break
    sample_dir = args.results_dir / args.sample_id
    out = args.out or sample_dir / "selection_report.json"
    report = {"sample": args.sample_id, "generated_at": datetime.now(timezone.utc).isoformat(), "truth_available": False,
              "selection_type": "operational_method_recommendation_only", "analysis_track": args.analysis_track,
              "confidence_tier": "confirmation_required", "long_read_confirmation_required": True,
              "organism": args.organism, "gram_group": args.gram_group,
              "limitations": ["No reference truth was available for per-isolate scoring.", "This is a benchmark-derived method choice, not sequence confirmation.", "Confirm structural or high-consequence AMR findings with long-read or hybrid evidence."]}
    if chosen:
        tool = chosen.get("primary_tool", "")
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
