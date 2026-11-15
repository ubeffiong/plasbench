#!/usr/bin/env python3
"""The generic user-tool output adapter (python/user_tool_adapter.py), every format checked by hand.

Assembly: c1 (10 bp), c2 (10 bp), c3 (10 bp). Each case writes a tool output, maps it with a manifest's [output]
section and checks the files stage 5 scores: pred_<tool>.plasmid.fasta, .bins.tsv, .candidates.fasta, .scores.tsv.
"""

import csv
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))

import user_tool_adapter as uta  # noqa: E402
import user_tools as ut  # noqa: E402

FAILED = []
ASSEMBLY = ">c1 desc\nACGTACGTAC\n>c2\nGGGGCCCCAA\n>c3\nTTTTAAAAGG\n"


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def headers(path):
    return [l[1:].strip() for l in Path(path).read_text(encoding="utf-8").splitlines() if l.startswith(">")]


def tsv(path):
    with open(path, encoding="utf-8") as handle:
        return [tuple(r) for r in csv.reader(handle, delimiter="\t")][1:]


def case(base, name, task, output_section, output_name, output_text, files=None):
    """Write a manifest + tool output, run the adapter; return (exit-or-error, paths)."""
    folder = base / "tools" / name
    folder.mkdir(parents=True)
    for fname, text in (files or {}).items():
        (folder / fname).write_text(text, encoding="utf-8")
    (folder / "plasbench-tool.ini").write_text(
        f"[tool]\nname = {name}\ntask = {task}\nanalysis_track = short_read\n[run]\nmode = import\ndir = {base}\n"
        f"pattern = {{sample}}\n[output]\n{output_section}\n", encoding="utf-8")
    tool = ut.UserTool(folder / "plasbench-tool.ini")
    out = base / name / "out"
    if isinstance(output_text, dict):
        out.mkdir(parents=True)
        for fname, text in output_text.items():
            (out / fname).write_text(text, encoding="utf-8")
        target = out
    else:
        out.mkdir(parents=True)
        target = out / output_name
        target.write_text(output_text, encoding="utf-8")
    contigs = base / "contigs.fasta"
    contigs.write_text(ASSEMBLY, encoding="utf-8")
    pred = base / name / f"pred_{name}.plasmid.fasta"
    try:
        prov = uta.convert(tool, str(target), str(contigs), str(pred))
        error = None
    except uta.OutputError as exc:
        prov, error = None, str(exc)
    stem = str(pred)[: -len(".plasmid.fasta")]
    return error, prov, pred, Path(stem + ".bins.tsv"), Path(stem + ".candidates.fasta"), Path(stem + ".scores.tsv")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)

        print("contig_bins")
        err, prov, pred, bins, cand, scores = case(
            base, "t_bins", "reconstruction", "format = contig_bins\nheader = yes\ncontig_column = seq\nbin_column = plasmid",
            "bins.tsv", "plasmid\tseq\nP1\tc1|x\nP1\tc2|x\nP2\tc1|x\n# a comment\n",
        )
        check("ids mapped with contig_id_strip_regex are required (raw ids fail)", err and "not in this assembly" in err, err)
        err, prov, pred, bins, cand, scores = case(
            base, "t_bins2", "reconstruction",
            "format = contig_bins\nheader = yes\ncontig_column = seq\nbin_column = plasmid\ncontig_id_strip_regex = \\|x$",
            "bins.tsv", "plasmid\tseq\nP1\tc1|x\nP1\tc2|x\nP2\tc1|x\n# a comment\n",
        )
        check("contig_bins: named columns, stripped ids, comment skipped", err is None and headers(pred) == ["c1", "c2"], err)
        check("contig_bins: bins written, a contig in two bins keeps the first", tsv(bins) == [("P1", "c1"), ("P1", "c2")], tsv(bins))
        check("contig_bins: the second bin is recorded in the provenance", prov["contigs_in_multiple_bins"] == {"c1": ["P1", "P2"]}, prov)
        check("contig_bins: no scores without a score column", not cand.exists() and not scores.exists())

        err, prov, pred, bins, *_ = case(
            base, "t_hash", "reconstruction", "format = contig_bins\ncontig_column = 2\nbin_column = 1",
            "b.tsv", "#bin\tcontig\nB\tc3\n")
        check("contig_bins: a '#'-prefixed header and 1-based columns", err is None and tsv(bins) == [("B", "c3")], err)

        print("contig_labels")
        err, prov, pred, bins, cand, scores = case(
            base, "t_lab", "classification",
            "format = contig_labels\ndelimiter = comma\ncontig_column = id\nlabel_column = call\nplasmid_values = plasmid, 1\n"
            "score_column = p\ncontig_id_from = first_token",
            "x.csv", "id,call,p\nc1 extra,plasmid,0.9\nc2,chromosome,0.2\nc3,1,0.55\n")
        check("labels: the hard call follows plasmid_values", err is None and headers(pred) == ["c1", "c3"], err)
        check("labels: a classifier writes no bins", not bins.exists())
        check("labels: candidates are every scored contig", headers(cand) == ["c1", "c2", "c3"])
        check("labels: scores.tsv carries each probability", tsv(scores) == [("c1", "0.9"), ("c2", "0.2"), ("c3", "0.55")], tsv(scores))
        err, prov, pred, *_ = case(
            base, "t_thr", "classification", "format = contig_labels\nheader = no\ncontig_column = 1\nscore_column = 2\nthreshold = 0.6",
            "x.tsv", "c1\t0.9\nc2\t0.6\nc3\t0.1\n")
        check("labels: without a label column, score >= threshold is plasmid", err is None and headers(pred) == ["c1", "c2"], err)
        err, *_ = case(base, "t_range", "classification", "format = contig_labels\nheader = no\ncontig_column = 1\nscore_column = 2",
                       "x.tsv", "c1\t90\n")
        check("labels: a score outside [0, 1] is rejected with the fix", err and "outside [0, 1]" in err, err)
        err, *_ = case(base, "t_col", "classification", "format = contig_labels\ncontig_column = contig\nlabel_column = nope",
                       "x.tsv", "contig\tlabel\nc1\tplasmid\n")
        check("labels: a column name not in the header is named with the columns", err and "'nope'" in err and "contig, label" in err, err)
        err, prov, pred, bins, *_ = case(
            base, "t_labrec", "reconstruction", "format = contig_labels\ncontig_column = 1\nlabel_column = 2",
            "x.tsv", "contig\tlabel\nc2\tplasmid\n")
        check("labels for a reconstruction task: each plasmid contig its own bin", tsv(bins) == [("c2", "c2")], tsv(bins) if bins.exists() else err)

        print("plasmid_fasta and fasta_dir")
        err, prov, pred, bins, *_ = case(base, "t_fa", "reconstruction", "format = plasmid_fasta", "p.fasta",
                                         ">p1 circular\nAAAA\n>p1\nCCCC\n>empty\n")
        check("plasmid_fasta: records kept, a repeated id made unique, empty records dropped",
              err is None and headers(pred) == ["p1", "p1_2"] and prov["renamed"] == 1, (err, prov))
        check("plasmid_fasta: each record is its own bin", tsv(bins) == [("p1", "p1"), ("p1_2", "p1_2")])
        err, prov, pred, bins, *_ = case(base, "t_dir", "reconstruction", "format = fasta_dir", "",
                                         {"plasmid_A.fasta": ">ctg1\nAAAA\n>ctg2\nCC\n", "plasmid_B.fa": ">ctg1\nGG\n",
                                          "notes.txt": "ignored"})
        check("fasta_dir: one bin per file, record ids prefixed by the file",
              err is None and tsv(bins) == [("plasmid_A", "plasmid_A__ctg1"), ("plasmid_A", "plasmid_A__ctg2"),
                                            ("plasmid_B", "plasmid_B__ctg1")], (err, tsv(bins) if bins.exists() else None))

        print("adapter")
        script = ("import sys\nout = sys.argv[3]\nopen(out, 'w').write('>c2\\nGGGGCCCCAA\\n')\n"
                  "open(out[:-len('.plasmid.fasta')] + '.bins.tsv', 'w').write('bin_id\\tsequence_id\\nX\\tc2\\n')\n")
        err, prov, pred, bins, *_ = case(base, "t_adapt", "reconstruction", "format = adapter\nadapter = conv.py", "o.json", "{}",
                                         files={"conv.py": script})
        check("adapter: the tool's own script writes the native files", err is None and headers(pred) == ["c2"] and tsv(bins) == [("X", "c2")], err)
        err, *_ = case(base, "t_adapt_bad", "reconstruction", "format = adapter\nadapter = conv.py", "o.json", "{}",
                       files={"conv.py": "import sys\nsys.exit(4)\n"})
        check("adapter: a failing adapter is an unusable output", err and "exited 4" in err, err)

        print("empty and missing output")
        err, prov, pred, bins, *_ = case(base, "t_empty", "reconstruction", "format = contig_bins", "b.tsv", "contig\tbin\n")
        check("an empty table is a completed, empty prediction", err is None and headers(pred) == [] and tsv(bins) == [], err)
        tool = ut.UserTool(base / "tools" / "t_empty" / "plasbench-tool.ini")
        try:
            uta.convert(tool, str(base / "nowhere.tsv"), str(base / "contigs.fasta"), str(base / "pred_x.plasmid.fasta"))
            missing = None
        except uta.OutputError as exc:
            missing = str(exc)
        check("an output the tool never wrote is named", missing and "did not write" in missing, missing)

    if FAILED:
        print("USER TOOL ADAPTER TESTS FAILED")
        return 1
    print("ALL USER TOOL ADAPTER TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
