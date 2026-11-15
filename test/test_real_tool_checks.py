#!/usr/bin/env python3
"""The real-binary check (test/real_tools/check_real_tool.py) and its workflow, tested without any real binary (plan E1).

The checks run offline against stand-in tool OUTPUT, passed through the REAL adapters, so a change in the adapters' contract, in contig naming or in the
database handling is caught here, and the scheduled workflow only has to prove that the real binaries still write what the stand-ins imitate.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "test" / "real_tools"))
import check_real_tool as crt  # noqa: E402

BASH = os.environ.get("PLASBENCH_BASH") or shutil.which("bash")


def bash_works():
    try:
        return subprocess.run([BASH, "-c", "true"], capture_output=True, timeout=30).returncode == 0
    except (OSError, TypeError, subprocess.TimeoutExpired):
        return False


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    print("the checks")
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        asm = t / "asm.fasta"
        asm.write_text(">NODE_1_length_5000_cov_20.5\n" + "ACGT" * 1250 + "\n>NODE_2_length_100_cov_3.0\n" + "ACGT" * 25 + "\n")
        ids = [n for n, _l in crt.fasta_records(asm)]
        check("record ids are the first word of the header", ids == ["NODE_1_length_5000_cov_20.5", "NODE_2_length_100_cov_3.0"], ids)
        pred, bins = t / "pred.plasmid.fasta", t / "pred.bins.tsv"
        pred.write_text(">NODE_1_length_5000_cov_20.5 plasmid_x\n" + "ACGT" * 1250 + "\n")
        bins.write_text("bin_id\tsequence_id\nplasmid_x\tNODE_1_length_5000_cov_20.5\n")
        check("a sound output has no problems", crt.validate_output("mob_recon", pred, bins, ids) == [])
        pred.write_text(">contig_1\n" + "ACGT" * 10 + "\n")
        bins.write_text("bin_id\tsequence_id\nplasmid_x\tcontig_1\n")
        bad = crt.validate_output("mob_recon", pred, bins, ids)
        check("a tool that renames contigs is caught, in both the FASTA and the bins", sum("not contigs of the input" in p for p in bad) == 2, bad)
        check("a re-assembler's own contig names are not a problem", crt.validate_output("plasmidspades", pred, bins, ids) == [])
        bins.write_text("bin\tseq\nx\tNODE_1_length_5000_cov_20.5\n")
        check("a wrong bins header is caught", any("header" in p for p in crt.validate_output("platon", pred, bins, ids)))
        bins.write_text("bin_id\tsequence_id\nb1\ta\nb2\ta\n")
        check("a sequence in two bins is caught", any("more than one bin" in p for p in crt.validate_output("platon", pred, bins, ["a"])))
        check("a missing bins table is caught", any("no bins table" in p for p in crt.validate_output("platon", pred, t / "none.tsv", ids)))
        check("a missing predicted FASTA is caught", crt.validate_output("platon", t / "none.fasta", bins, ids) == ["the adapter wrote no none.fasta"])
        share = crt.plasmid_share(pred, asm)
        check("the plasmid share is bases called over input bases", abs(share - 40 / 5100) < 1e-9, share)

    print("the database")
    check("a tool that needs no database has no database problem", crt.database_problem("mob_recon", {}) is None)
    check("an unset database variable is named before the tool runs", "PLATON_DB is not set" in (crt.database_problem("platon", {}) or ""))
    check("a database path that is not a directory is named", "is not a directory" in (crt.database_problem("platon", {"PLATON_DB": "/no/such/dir"}) or ""))
    with tempfile.TemporaryDirectory() as t:
        check("a configured database directory is accepted", crt.database_problem("platon", {"PLATON_DB": t}) is None)

    print("the verdict")
    check("clean run passes", crt.judge([], 0, 0, 0.5, 0.0)[0] == "pass")
    check("a share of 0 against a floor of 0 passes (recorded, not enforced)", crt.judge([], 0, 0, 0.0, 0.0)[0] == "pass")
    check("a share under an enforced floor fails", crt.judge([], 0, 0, 0.1, 0.5)[0] == "fail")
    check("a tool exit fails", crt.judge([], 1, -1, None, 0.0)[0] == "fail")
    check("the shipped floors are all present and numeric", all(crt.expected_floor(t) >= 0 for t in ("mob_recon", "platon", "plasmidspades")))

    print("the real adapters on stand-in output")
    if not bash_works():
        print("  SKIP: no working bash for the adapters (set PLASBENCH_BASH)")
    else:
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            asm = t / "asm.fasta"
            asm.write_text(">NODE_1_length_5000_cov_20.5\n" + "ACGT" * 1250 + "\n>NODE_2_length_300_cov_9.0\n" + "ACGT" * 75 + "\n")
            ids = [n for n, _l in crt.fasta_records(asm)]
            for tool, adapter, make in (
                    ("mob_recon", "adapt_mob_recon.sh", lambda d: (d / "plasmid_AA123.fasta").write_text(">NODE_1_length_5000_cov_20.5 rep_cluster_1\n" + "ACGT" * 1250 + "\n")),
                    ("platon", "adapt_platon.sh", lambda d: (d / "fixture.plasmid.fasta").write_text(">NODE_1_length_5000_cov_20.5\n" + "ACGT" * 1250 + "\n")),
                    ("plasmidspades", "adapt_plasmidspades.sh", lambda d: (d / "contigs.fasta").write_text(">NODE_1_length_4400_cov_300.2\n" + "ACGT" * 1100 + "\n"))):
                out = t / tool
                out.mkdir()
                make(out)
                pred = t / f"pred_{tool}.plasmid.fasta"
                done = subprocess.run([BASH, str(ROOT / "adapters" / adapter), str(out), str(asm), str(pred)], capture_output=True, text=True)
                bins = Path(str(pred).replace(".plasmid.fasta", ".bins.tsv"))
                check(f"{tool}: the adapter runs and its output passes every check", done.returncode == 0 and crt.validate_output(tool, pred, bins, ids) == [], done.stderr[-300:])
            empty = t / "empty"
            empty.mkdir()
            pred = t / "pred_mob_recon.plasmid.fasta"
            done = subprocess.run([BASH, str(ROOT / "adapters" / "adapt_mob_recon.sh"), str(empty), str(asm), str(pred)], capture_output=True, text=True)
            check("an output directory with no plasmids is a valid empty prediction, not a failure", done.returncode == 0 and pred.read_text() == "" and "predicted no plasmids" in done.stderr)

    print("the workflow")
    text = (ROOT / ".github" / "workflows" / "real-tools.yml").read_text(encoding="utf-8")
    check("it runs on a schedule and on request, never on a pull request", "schedule:" in text and "workflow_dispatch:" in text and "pull_request" not in text and "push:" not in text)
    check("it covers the three tools", all(tool in text for tool in ("mob_recon", "platon", "plasmidspades")))
    check("it has no write permission and every third-party action is pinned to a major version", "contents: read" in text and all(re.search(r"uses: [^@\s]+@v\d+", line) for line in text.splitlines() if "uses:" in line))
    check("a tool failure does not cancel the others", "fail-fast: false" in text)
    check("the checker it runs exists", (ROOT / "test" / "real_tools" / "check_real_tool.py").is_file() and "test/real_tools/check_real_tool.py" in text)
    print()
    if not ok:
        print("REAL TOOL CHECK TESTS FAILED")
        sys.exit(1)
    print("ALL REAL TOOL CHECK TESTS PASSED")


if __name__ == "__main__":
    main()
