#!/usr/bin/env python3
"""One validated set of readers (audit AU-021): FASTA duplicate-id / empty-header policy, PAF with a counted
dropped-row warning, a table reader that names a missing column, and one zero-length-block identity (0.0).

Part 1 pins the readers. Part 2 runs the migrated scorers on a fixture holding a duplicate id, an empty
header and damaged PAF rows: the duplicate and the empty header are refused (never resolved differently by
module), and damaged PAF rows change no score (output byte-identical to the clean PAF) while being counted
in a warning."""
import gzip
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import plasbench_common as pc  # noqa: E402
import score_plasmids  # noqa: E402
import contig_classification  # noqa: E402
import make_truth  # noqa: E402
import build_enterprise_view  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


def raises(fn, text):
    try:
        fn()
    except ValueError as exc:
        return text in str(exc)
    return False


def run(args):
    return subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True)


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    good = tmp / "good.fa"
    good.write_text(">a first\nACGT\nAC\n\n>b\nACG\n>c\n")
    dup = tmp / "dup.fa"
    dup.write_text(">a\nACGT\n>b\nAC\n>a desc\nACGTAC\n")
    empty = tmp / "empty.fa"
    empty.write_text(">a\nACGT\n>\nTTTT\n>b\nAC\n")
    orphan = tmp / "orphan.fa"
    orphan.write_text("ACGT\n>a\nAC\n")
    gz = tmp / "good.fa.gz"
    with gzip.open(gz, "wt") as handle:
        handle.write(">a first\nACGT\nAC\n>b\nACG\n>c\n")

    # --- 1. FASTA -------------------------------------------------------------------------
    check("valid FASTA: ordered (id, length), zero-length record kept, blank lines ignored",
          pc.read_fasta_records(good) == [("a", 6), ("b", 3), ("c", 0)], pc.read_fasta_records(good))
    check("gzip FASTA reads identically", pc.read_fasta_records(gz) == pc.read_fasta_records(good))
    check("duplicate id is an error by default", raises(lambda: pc.read_fasta_records(dup), "duplicate FASTA record id: a"))
    check("duplicate id policy 'last' keeps the later length at the first position",
          pc.read_fasta_records(dup, duplicates="last") == [("a", 6), ("b", 2)], pc.read_fasta_records(dup, duplicates="last"))
    check("empty header is an error by default", raises(lambda: pc.read_fasta_records(empty), "without a record id"))
    check("empty header policy 'skip' drops that record and its sequence",
          pc.read_fasta_records(empty, empty_header="skip") == [("a", 4), ("b", 2)], pc.read_fasta_records(empty, empty_header="skip"))
    check("sequence before the first header is an error", raises(lambda: pc.read_fasta_records(orphan), "before a header"))
    check("an unknown policy is refused", raises(lambda: pc.read_fasta_records(good, duplicates="first"), "must be"))

    # The scorers and truth builders now agree on the same files (they used to keep-last, raise or crash by module).
    for label, reader in (("score_plasmids", score_plasmids.read_fasta_lengths),
                          ("contig_classification", contig_classification.read_fasta_lengths),
                          ("make_truth", make_truth.read_fasta_lengths)):
        check(f"{label}: duplicate id refused", raises(lambda: reader(dup), "duplicate FASTA record id"))
        check(f"{label}: empty header refused with a message (no IndexError)", raises(lambda: reader(empty), "without a record id"))
    check("score_plasmids and contig_classification return the same map on valid input",
          score_plasmids.read_fasta_lengths(good) == contig_classification.read_fasta_lengths(good) == {"a": 6, "b": 3, "c": 0})
    check("make_truth returns the same lengths as an ordered list", make_truth.read_fasta_lengths(good) == [("a", 6), ("b", 3), ("c", 0)])

    # --- 2. PAF ---------------------------------------------------------------------------
    truth = tmp / "truth.tsv"
    truth.write_text("sequence_id\tmolecule_type\tlength\npA\tPLASMID\t1000\nchr\tCHROMOSOME\t5000\n")
    contigs = tmp / "contigs.fa"
    contigs.write_text(">c1\n" + "A" * 1000 + "\n>c2\n" + "A" * 2000 + "\n")
    clean_rows = ["c1\t1000\t0\t1000\t+\tpA\t1000\t0\t1000\t990\t1000\t60\ttp:A:P",
                  "c2\t2000\t0\t2000\t+\tchr\t5000\t100\t2100\t1980\t2000\t60\ttp:A:P",
                  "c2\t2000\t0\t10\t+\tpA\t1000\t0\t10\t0\t0\t60\ttp:A:P"]          # zero-length block
    bad_rows = ["c1\t1000\t0\t1000\t+\tpA\t1000",                                      # too few columns
                "c1\tNOTINT\t0\t1000\t+\tpA\t1000\t0\t1000\t990\t1000\t60"]            # non-integer
    clean_paf, dirty_paf = tmp / "clean.paf", tmp / "dirty.paf"
    clean_paf.write_text("\n".join(clean_rows) + "\n")
    dirty_paf.write_text("\n".join([bad_rows[0]] + clean_rows + [bad_rows[1]]) + "\n\n")

    stats = {}
    rows = list(pc.iter_paf(dirty_paf, stats=stats))
    check("lenient iter_paf yields only the valid rows and counts the dropped ones", len(rows) == 3 and stats["dropped"] == 2, (len(rows), stats))
    check("a PAF row carries parsed integers and its optional tags", rows[0]["qlen"] == 1000 and rows[0]["tags"] == ["tp:A:P"], rows[0])
    check("strict iter_paf raises on a short row, naming the line", raises(lambda: list(pc.iter_paf(dirty_paf, strict=True)), "line 1 has 7 columns"))
    check("zero-length-block identity is one value, 0.0", pc.paf_identity(0, 0) == 0.0 and pc.paf_identity(3, 4) == 0.75)
    check("build_enterprise_view uses that same identity (was 1.0 there, 0.0 elsewhere)", build_enterprise_view.paf_identity is pc.paf_identity)

    # --- 3. migrated callers: damaged PAF rows are counted, scores do not move ----------------
    outputs = {}
    for name, paf in (("clean", clean_paf), ("dirty", dirty_paf)):
        done = run([ROOT / "python" / "contig_classification.py", "label", "--contigs", contigs, "--paf", paf, "--truth", truth,
                    "--labels-out", tmp / f"labels_{name}.tsv", "--min-length", 500])
        check(f"contig_classification label ({name} PAF) exits 0", done.returncode == 0, done.stderr)
        outputs[name] = (tmp / f"labels_{name}.tsv").read_bytes()
        if name == "dirty":
            check("the dropped PAF rows are reported once, with their count", "2 malformed labelling PAF row(s) dropped" in done.stderr, done.stderr)
        else:
            check("a clean PAF produces no dropped-row warning", "malformed" not in done.stderr, done.stderr)
    check("contig labels are byte-identical with and without the damaged rows", outputs["clean"] == outputs["dirty"])
    labels = outputs["clean"].decode()
    check("contig labels are what the clean PAF implies (c1 PLASMID, c2 CHROMOSOME)",
          "c1\t1000\tPLASMID" in labels and "c2\t2000\tCHROMOSOME" in labels, labels)

    bins = tmp / "bins.tsv"
    bins.write_text("sequence_id\tbin_id\nc1\tb1\nc2\tb2\n")
    results = {}
    for name, paf in (("clean", clean_paf), ("dirty", dirty_paf)):
        done = run([ROOT / "python" / "score_bins.py", "--truth", truth, "--paf", paf, "--bins", bins,
                    "--out", tmp / f"bins_{name}.tsv", "--summary", tmp / f"summary_{name}.tsv"])
        check(f"score_bins ({name} PAF) exits 0", done.returncode == 0, done.stderr[-400:])
        if done.returncode == 0:
            results[name] = ((tmp / f"bins_{name}.tsv").read_bytes(), (tmp / f"summary_{name}.tsv").read_bytes())
        if name == "dirty":
            check("score_bins reports the dropped PAF rows with their count", "2 malformed bin PAF row(s) dropped" in done.stderr, done.stderr[-400:])
    check("bin scores are byte-identical with and without the damaged rows", len(results) == 2 and results["clean"] == results["dirty"])

    done = run([ROOT / "python" / "contig_classification.py", "label", "--contigs", dup, "--paf", clean_paf, "--truth", truth,
                "--labels-out", tmp / "x.tsv"])
    check("a duplicate contig id stops the labeller with a message instead of silently keeping the last",
          done.returncode != 0 and "duplicate FASTA record id" in done.stderr, done.stderr[-300:])

    # --- 4. table reader -----------------------------------------------------------------------
    table = tmp / "t.tsv"
    table.write_text("a\tb\n1\t2\n")
    check("read_table returns rows when the required columns exist", pc.read_table(table, required=("a", "b")) == [{"a": "1", "b": "2"}])
    check("read_table names a missing column", raises(lambda: pc.read_table(table, required=("a", "z")), "missing required column(s): z"))
    check("read_table allow_missing returns [] for an absent file", pc.read_table(tmp / "nope.tsv", allow_missing=True) == [])
    check("read_tsv and read_table agree on a valid table", pc.read_tsv(table) == pc.read_table(table))

print("ALL SHARED READER TESTS PASSED" if ok else "SHARED READER TESTS FAILED")
sys.exit(0 if ok else 1)
