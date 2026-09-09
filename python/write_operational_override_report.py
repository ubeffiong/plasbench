#!/usr/bin/env python3
"""Write a selection report for an explicit --tool override.

Used only by scripts/08_operational_reconstruct.sh when the caller names a
tool directly instead of asking the benchmark recommendation for one, so the
report cannot claim this was an evidence-gated choice.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from select_unknown_sample import read_plasmid_similarity  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--tool", required=True)
    parser.add_argument("--analysis-track", choices=("short_read", "long_read", "hybrid"), default="short_read")
    parser.add_argument("--organism", default="")
    parser.add_argument("--gram-group", default="")
    parser.add_argument("--candidate-fasta", help="This isolate's copied candidate.plasmid.fasta, used only to "
                                                   "match --plasmid-similarity rows to this isolate's own records.")
    parser.add_argument("--plasmid-similarity", help="Optional plasmid_similarity.tsv (classify_operational_plasmid.py); "
                                                     "merged into the report under 'plasmid_novelty' when both this "
                                                     "and --candidate-fasta are given.")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    report = {
        "sample": args.sample_id, "generated_at": datetime.now(timezone.utc).isoformat(),
        "truth_available": False, "selection_type": "explicit_tool_override",
        "analysis_track": args.analysis_track, "confidence_tier": "confirmation_required",
        "long_read_confirmation_required": True, "organism": args.organism, "gram_group": args.gram_group,
        "selected_tool": args.tool, "selected_candidate_fasta": "selected_candidate/candidate.plasmid.fasta",
        "selection_reason": "Explicit --tool override, not a benchmark recommendation lookup.",
        "limitations": ["No reference truth was available for per-isolate scoring.",
                        "This tool was explicitly requested, not chosen from benchmark evidence.",
                        "Confirm structural or high-consequence AMR findings with long-read or hybrid evidence."],
    }
    if args.candidate_fasta:
        novelty = read_plasmid_similarity(args.plasmid_similarity, args.candidate_fasta)
        if novelty:
            report["plasmid_novelty"] = novelty
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
