#!/usr/bin/env python3
"""Regression for python/tool_capabilities.py's analysis_track support: each
tool's declared track must be queryable independently of binning_capable, and
a registry row with a missing/invalid analysis_track value must be rejected
rather than silently accepted -- this is the registry half of the fix for
scripts/05_score.sh stamping one global track onto every tool's score row.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "python" / "tool_capabilities.py"
REGISTRY = ROOT / "config" / "tool_capabilities.tsv"


def run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--registry", str(REGISTRY), *args],
        capture_output=True, text=True,
    )


def main():
    expectations = {
        "mob_recon": "short_read",
        "platon": "short_read",
        "plasmidspades": "short_read",
        "gplas2_mob": "short_read",
        "gplas2_external": "short_read",
        "flye_mob_recon": "long_read",
        "plassembler": "hybrid",
    }
    for tool, expected in expectations.items():
        result = run("--tool", tool, "--analysis-track")
        assert result.returncode == 0, f"{tool}: unexpected failure: {result.stderr}"
        assert result.stdout.strip() == expected, (
            f"{tool}: expected analysis_track={expected}, got {result.stdout.strip()!r}"
        )
    print("every existing tool's analysis_track resolves correctly -> PASS")

    # --binning-capable must still work unchanged alongside the new flag.
    result = run("--tool", "mob_recon", "--binning-capable")
    assert result.returncode == 0, f"unexpected failure: {result.stderr}"
    print("--binning-capable is unaffected by the new --analysis-track flag -> PASS")

    requires_independence = {
        "mob_recon": False, "platon": False, "plasmidspades": False,
        "gplas2_mob": False, "gplas2_external": False,
        "flye_mob_recon": True, "plassembler": True,
    }
    for tool, expected in requires_independence.items():
        result = run("--tool", tool, "--requires-independent-long-read-truth")
        if expected:
            assert result.returncode == 0 and result.stdout.strip() == "yes", (
                f"{tool}: expected requires_independent_long_read_truth=yes, "
                f"got returncode={result.returncode} stdout={result.stdout!r}"
            )
        else:
            assert result.returncode != 0, f"{tool}: should not require independent long-read truth"
    print("every existing tool's requires_independent_long_read_truth resolves correctly -> PASS")

    # A registry with a missing/invalid analysis_track value must be rejected
    # at load time, not silently degrade to an empty/None track.
    with tempfile.TemporaryDirectory() as tmp:
        bad_registry = Path(tmp) / "bad.tsv"
        bad_registry.write_text(
            "tool\tmethod_class\tbinning_capable\tprimary_input\tdescription\tanalysis_track\n"
            "broken_tool\tclassification\tno\tassembly\tmissing a valid track\tnot_a_real_track\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--registry", str(bad_registry),
             "--tool", "broken_tool", "--analysis-track"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0, "an invalid analysis_track value should be rejected"
        assert "analysis_track" in result.stderr, (
            f"expected an analysis_track-specific error, got: {result.stderr}"
        )
    print("an invalid analysis_track value is rejected at registry-load time -> PASS")

    print("ALL TOOL CAPABILITIES REGISTRY TESTS PASSED")


if __name__ == "__main__":
    main()
