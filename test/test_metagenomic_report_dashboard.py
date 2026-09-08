#!/usr/bin/env python3
"""Regression contract for the detailed, self-contained meta dashboard."""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))
from metagenomics import build_report  # noqa: E402


def main():
    with tempfile.TemporaryDirectory() as temporary:
        out = Path(temporary)
        (out / "metagenomics.summary.tsv").write_text(
            "community_id\ttool\tbin_f1\ncommunity_a\ttool_a\t0.8\n", encoding="utf-8")
        (out / "metagenomics.classification_metrics.tsv").write_text(
            "community_id\ttool\tmacro_f1\ncommunity_a\ttool_b\t0.7\n", encoding="utf-8")
        (out / "metagenomics.bin_metrics.tsv").write_text(
            "community_id\ttool\tpredicted_bin_id\ttrue_plasmid_contigs\tchromosome_contigs\tvirus_contigs\tunknown_contigs\ncommunity_a\ttool_a\tb1\t2\t1\t0\t0\n", encoding="utf-8")
        (out / "metagenomics.mobilome_evidence.tsv").write_text(
            "community_id\tfeature\ncommunity_a\tAMR\n", encoding="utf-8")
        report = build_report(out, [{"community_id": "community_a", "information_regime": "graph_aware", "truth_status": "verified", "assembly_profile": "metaSPAdes</script><script>bad()</script>", "host_assignment_evidence": "hic"}]).read_text(encoding="utf-8")
        for required in ("Method performance", "Community × tool matrix", "Bin and classification drilldown",
                         "Mobilome evidence timeline", "Artifact explorer", "Reading this report",
                         "plasbench-metagenomics-filtered.csv", "not a host assignment"):
            assert required in report, required
        assert "metaSPAdes" in report and "tool_a" in report and "tool_b" in report
        assert "</script><script>bad()" not in report and "\\u003c/script\\u003e" in report
        assert "{payload}" not in report
    print("METAGENOMIC DETAILED DASHBOARD CONTRACT PASSED")


if __name__ == "__main__":
    main()
