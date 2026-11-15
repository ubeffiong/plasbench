#!/usr/bin/env python3
"""Promoting a reviewed AMR truth draft (python/promote_amr_truth.py): gated, validated, recorded; and the AMR context columns (plan B4)."""
import csv
import datetime
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import promote_amr_truth as pat  # noqa: E402
import score_amr_placement as sap  # noqa: E402

DRAFT = ("sequence_id\tstart\tend\tgene_name\tgene_id\tcopy_id\tdatabase\tdatabase_version\tevidence_tier\n"
         "p1\t10\t90\tblaCTX-M-15\tblaCTX-M-15\tc1\tamrfinderplus\tAMRFinderPlus 4.0\tauto_derived\n")


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    def refuses(**kw):
        args = dict(draft=str(draft), truth=str(truth), out=str(out), reviewed_by="A. Reviewer", database_version="2024-05-02.1", confirmed=True)
        args.update(kw)
        try:
            pat.promote(**args)
        except ValueError as exc:
            return str(exc)
        return None

    print("promotion")
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        draft, truth, out = t / "truth_amr.draft.tsv", t / "truth.tsv", t / "truth_amr.tsv"
        draft.write_text(DRAFT)
        truth.write_text("sequence_id\tmolecule_type\tlength\np1\tPLASMID\t100\nchr\tCHROMOSOME\t500\n")
        check("it refuses without the confirmation flag", "confirm-reviewed" in (refuses(confirmed=False) or ""))
        check("it refuses without a reviewer", "reviewed-by" in (refuses(reviewed_by="  ") or ""))
        check("it refuses without the real database version", "database-version" in (refuses(database_version="") or ""))
        check("it only writes the file the scorer reads", "truth_amr.tsv" in (refuses(out=str(t / "other.tsv")) or ""))
        check("nothing was written by the refusals", not out.exists())
        count = pat.promote(str(draft), str(truth), str(out), "A. Reviewer", "2024-05-02.1", True, today=datetime.date(2026, 1, 2))
        row = next(csv.DictReader(open(out, newline=""), delimiter="\t"))
        check("a reviewed draft is promoted", count == 1 and row["evidence_tier"] == "reviewed" and row["database_version"] == "2024-05-02.1")
        check("who, when and which draft are recorded", row["reviewed_by"] == "A. Reviewer" and row["reviewed_on"] == "2026-01-02" and len(row["draft_sha256"]) == 64)
        check("it will not overwrite without --force", "already exists" in (refuses() or ""))
        check("--force replaces it", refuses(force=True) is None)
        draft.write_text(DRAFT.replace("\t10\t90\t", "\t10\t900\t"))
        out.unlink()
        check("a draft that does not validate is not promoted, and leaves nothing behind", "outside the plasmid" in (refuses() or "") and not out.exists() and not (t / "truth_amr.tsv.tmp").exists())
        done = subprocess.run([sys.executable, str(ROOT / "python" / "promote_amr_truth.py"), "--draft", str(draft), "--truth", str(truth), "--reviewed-by", "x", "--database-version", "1"],
                              capture_output=True, text=True)
        check("the command line also refuses without the confirmation", done.returncode != 0 and "confirm-reviewed" in done.stderr, done.stderr)

    print("AMR context")
    check("covered bases are a union, not a sum", sap.covered_bp([(0, 600), (400, 1000)], 0, 1000) == 1000)
    check("flank share is clipped at the plasmid ends", sap.flank_share([(0, 5000)], 100, 900, 5000, 1000) == 1.0)
    check("a record that covers only part of the flank gives that share", abs(sap.flank_share([(2900, 4000)], 3000, 3800, 5000, 1000) - 300 / 2000) < 1e-9)
    check("no flank to measure is None, not 0", sap.flank_share([], 0, 5000, 5000, 1000) is None)
    rows = [{"sample": "S", "sequence_id": "pA", "placement": "correct_plasmid", "assigned_bin": "b1", "plasmid_cprr_correct": "yes", "flank_covered": "1.0000"},
            {"sample": "S", "sequence_id": "pA", "placement": "correct_plasmid", "assigned_bin": "b1", "plasmid_cprr_correct": "yes", "flank_covered": "0.5000"},
            {"sample": "S", "sequence_id": "pB", "placement": "wrong_plasmid", "assigned_bin": "b1", "plasmid_cprr_correct": "no", "flank_covered": "0.1000"},
            {"sample": "S", "sequence_id": "pB", "placement": "correct_plasmid", "assigned_bin": "b2", "plasmid_cprr_correct": "no", "flank_covered": ""}]
    n, complete, prr, pairs, together, coloc, flank = sap.context(rows)
    check("plasmids, complete rate and AMR-PRR", (n, complete, prr) == (2, "0.5000", "0.5000"), (n, complete, prr))
    check("pairs kept together and mean flank context", (pairs, together, coloc, flank) == (2, 1, "0.5000", "0.5333"), (pairs, together, coloc, flank))
    rows2 = [{**r, "plasmid_cprr_correct_no_identity": "yes"} for r in rows]
    check("where the truth cannot judge identity the verdict without the identity criterion decides AMR-PRR (pB: complete is false, so only pA counts either way)",
          sap.context(rows2, {"S"})[2] == "0.5000" and sap.context([{**r, "plasmid_cprr_correct": "no"} for r in rows2], {"S"})[2] == "0.5000" and sap.context([{**r, "plasmid_cprr_correct": "no"} for r in rows2])[2] == "0.0000")
    check("draft truth copies are counted per group", sap.summarise([{"tool": "t", "gene_class": "x", "sample": "S", "sequence_id": "pA", "placement": "correct_plasmid", "assigned_bin": "b", "replicon_type_correct": "",
                                                                    "truth_evidence_tier": "auto_derived"}])[0]["draft_truth_copies"] == 1)
    none = sap.context([{**r, "plasmid_cprr_correct": ""} for r in rows])
    check("without a CPRR table AMR-PRR is blank, never 0", none[2] == "" and none[1] == "0.5000")
    check("fewer than two recovered copies on a plasmid is not evaluable", sap.context(rows[:1])[3:6] == (0, 0, ""))
    print()
    if not ok:
        print("AMR TRUTH PROMOTION TESTS FAILED")
        sys.exit(1)
    print("ALL AMR TRUTH PROMOTION TESTS PASSED")


if __name__ == "__main__":
    main()
