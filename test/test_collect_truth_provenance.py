#!/usr/bin/env python3
"""Offline checks of the evidence rules behind recorded truth provenance."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))
from collect_truth_provenance import derive  # noqa: E402
from truth_provenance import classify_method  # noqa: E402


def check(ok, label, condition):
    print(f"  {label} -> {bool(condition)}")
    return ok and bool(condition)


def main():
    ok = True
    row = {"sra_run": "SRR1"}
    hybrid = {"assembly_method": "Hybracter v. 0.7.3", "sequencing_tech": "Oxford Nanopore; Illumina NextSeq"}
    strategy, polish, _ = derive(row, hybrid, 1)
    ok = check(ok, "one Illumina run on the BioSample -> same_as_benchmark",
               (strategy, polish) == ("long_read_first_hybrid", "same_as_benchmark"))
    strategy, polish, reason = derive(row, hybrid, 3)
    ok = check(ok, "several Illumina runs -> polishing reads unknown", polish == "unknown" and "3 Illumina runs" in reason)
    strategy, polish, _ = derive(row, {"assembly_method": "HGAP v. 4", "sequencing_tech": "PacBio"}, 1)
    ok = check(ok, "long-read-only assembly -> polish none", (strategy, polish) == ("long_read_only", "none"))
    strategy, _, _ = derive(row, {"assembly_method": "Unicycler v. 0.4.8",
                                  "sequencing_tech": "Illumina NextSeq, ONT MinION"}, 1)
    ok = check(ok, "Unicycler hybrid -> short_read_first_hybrid", strategy == "short_read_first_hybrid")
    strategy, _, _ = classify_method("Trycyler v. V.0.5.4; Medaka v1.11.3; Polypolish v0.6.0",
                                     "Oxford Nanopore MinION; Illumina NovaSeq")
    ok = check(ok, "NCBI misspelling 'Trycyler' is still long-read-first", strategy == "long_read_first_hybrid")
    strategy, _, _ = classify_method("Unicycler v. 0.4.4; Canu v. 1.8; Pilon v. 1.23", "PacBio RSII; Illumina MiSeq")
    ok = check(ok, "Unicycler + Canu stays unknown (needs a curator)", strategy == "unknown")
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
