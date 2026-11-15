#!/usr/bin/env python3
"""Tool validation tiers (plan E3): every tool states how far it has been validated, every claim has evidence, and no adapter ships untested by accident."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import tool_capabilities as tc  # noqa: E402

# the adapter script each tool's output goes through (None: the tool has none: a native mode, a baseline or a synthetic method)
ADAPTER_OF = {
    "mob_recon": "adapt_mob_recon.sh", "flye_mob_recon": "adapt_mob_recon.sh", "trycycler_mob_recon": "adapt_mob_recon.sh", "platon": "adapt_platon.sh",
    "plasmidspades": "adapt_plasmidspades.sh", "gplas2_mob": "adapt_gplas.sh", "gplas2_external": "adapt_gplas.sh", "plassembler": "adapt_plassembler.sh",
    "hybracter_long": "adapt_hybracter.sh", "hybracter_hybrid": "adapt_hybracter.sh", "genomad": "adapt_genomad.sh", "plasme": "adapt_plasme.sh",
    "rfplasmid": "adapt_rfplasmid.sh", "plasmidhunter": "adapt_plasmidhunter.sh", "plasmer": "adapt_plasmer.sh", "plascope": "adapt_plascope.sh",
    "plasgraph2": "adapt_plasgraph2.sh", "plsmd": "adapt_plsmd.sh", "plasbin_flow": "adapt_plasbin_flow.sh",
}
# Tools allowed to sit at the `untested` tier. Adding a tool here is a decision, made in a reviewed change, to ship an adapter without a test; remove the
# entry when the adapter gets one.
ACKNOWLEDGED_UNTESTED = {"plassembler"}


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    caps = tc.read_capabilities(ROOT / "config" / "tool_capabilities.tsv")
    check("every tool states a validation tier from the vocabulary", all(c.get("validation_status") in tc.VALIDATION_TIERS for c in caps.values()),
          [t for t, c in caps.items() if c.get("validation_status") not in tc.VALIDATION_TIERS])
    try:
        tc.read_capabilities(ROOT / "test" / "fixtures" / "does_not_exist.tsv")
    except OSError:
        pass
    bad = [t for t, c in caps.items() if c.get("validation_status") == "adapter_tested" and not (ROOT / (c.get("validation_evidence") or "-")).is_file()]
    check("an adapter_tested claim names an evidence file that exists", not bad, bad)
    unmentioned = [t for t, c in caps.items() if c.get("validation_status") == "adapter_tested" and ADAPTER_OF.get(t)
                   and ADAPTER_OF[t] not in (ROOT / c["validation_evidence"]).read_text(encoding="utf-8", errors="replace")]
    check("the evidence file actually mentions the tool's adapter", not unmentioned, unmentioned)
    records = ROOT / "test" / "real_tools" / "records"
    claimed = [t for t, c in caps.items() if c.get("validation_status") == "real_binary_checked"]
    def passed(tool):
        """A record file with a ROW for this tool whose status is exactly 'pass' (not a substring match: 'bypass' or a problem text containing 'pass' is not a pass)."""
        import csv
        for path in (records.glob("*.tsv") if records.is_dir() else []):
            with open(path, newline="", encoding="utf-8") as handle:
                if any(r.get("tool") == tool and r.get("status") == "pass" for r in csv.DictReader(handle, delimiter="\t")):
                    return True
        return False
    missing = [t for t in claimed if not passed(t)]
    check("real_binary_checked needs a reviewed workflow record that passed for that tool (none is claimed until one exists)", not missing, missing)
    untested = {t for t, c in caps.items() if c.get("validation_status") == "untested"}
    check("every untested tool is acknowledged (a new adapter cannot ship untested by accident)", untested <= ACKNOWLEDGED_UNTESTED, sorted(untested - ACKNOWLEDGED_UNTESTED))
    check("an acknowledged-untested tool that has since been tested is removed from the list", ACKNOWLEDGED_UNTESTED <= untested, sorted(ACKNOWLEDGED_UNTESTED - untested))
    adapters = {p.name for p in (ROOT / "adapters").glob("adapt_*.sh")}
    check("every adapter script belongs to a registered tool (a new adapter is registered and tiered)", adapters <= set(ADAPTER_OF.values()), sorted(adapters - set(ADAPTER_OF.values())))
    check("every mapped tool is in the registry", set(ADAPTER_OF) <= set(caps), sorted(set(ADAPTER_OF) - set(caps)))
    check("not_applicable is only for PlasBench's own baselines and the synthetic demo methods",
          {t for t, c in caps.items() if c.get("validation_status") == "not_applicable"} == {"mob_like", "platon_like", "spades_like", "gplas_like", "weak_like",
                                                                                          "baseline_coverage", "baseline_reference", "baseline_replicon"})
    doc = (ROOT / "adapters" / "REGISTRY.md").read_text(encoding="utf-8")
    check("the registry documents the tiers and the interface", all(t in doc for t in tc.VALIDATION_TIERS) and "Validation tiers" in doc and "bin_id" in doc)
    check("a bad tier is rejected by the reader", _rejects())
    print()
    if not ok:
        print("TOOL VALIDATION TIER TESTS FAILED")
        sys.exit(1)
    print("ALL TOOL VALIDATION TIER TESTS PASSED")


def _rejects():
    import tempfile
    with tempfile.TemporaryDirectory() as t:
        path = Path(t) / "caps.tsv"
        path.write_text("tool\tmethod_class\tbinning_capable\tprimary_input\tdescription\tanalysis_track\trequires_independent_long_read_truth\tvalidation_status\n"
                        "x\tbinning\tyes\tassembly\td\tshort_read\tno\tbogus\n")
        try:
            tc.read_capabilities(path)
        except ValueError as exc:
            return "validation_status" in str(exc)
    return False


if __name__ == "__main__":
    main()
