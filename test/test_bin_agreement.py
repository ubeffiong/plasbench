#!/usr/bin/env python3
"""Bin agreement (python/bin_agreement.py): best-match eval, dissimilarity, matrix.

Toy example (hand computed). Contigs a=100 b=200 c=300 d=400 (PLASMID), e=500
(CHROMOSOME). Truth T1={a,b} (300 bp), T2={c,d} (700 bp).
Predicted P1={a,b,c} (600 bp), P2={d,e} (900 bp).
  overlaps (count/bp): P1-T1 2/300, P1-T2 1/300, P2-T2 1/400
  count: precision (2+1)/(3+2)=0.6, recall (2+1)/4=0.75, F1 0.666667
  bp:    precision 700/1500=0.466667, recall 700/1000=0.7, F1 0.56
Dissimilarity, alpha=1: extra e=500, missing 0; cells (P1,T1)=300 (P1,T2)=300
(P2,T2)=400; split P1 = 300+300-300 = 300; join T2 = 300+400-400 = 300;
total 1100, norm = (600+900)+1000 = 2500 -> 0.44.
Non one-to-one: P1={a}, P2={b} vs T={a,b}: both best match T; count precision 1,
recall 1/2.
Pure split (alpha=1): P={a,b,c,d} vs T1,T2: split 300+700-700 = 300, norm 2000 -> 0.15.
Pure join is the mirror image (join 300).
Edge cases: empty/empty 0, one empty 1, identical 0, disjoint 1.
"""
import csv
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
import bin_agreement as ba  # noqa: E402

FAILS = []


def check(name, cond):
    if not cond:
        FAILS.append(name)
        print("FAIL", name)


def near(x, y, tol=1e-6):
    return x is not None and abs(x - y) < tol


def write_labels(path, rows, with_plasmids=True):
    cols = ["contig", "length", "label", "plasmid_fraction", "chromosome_fraction", "best_plasmid", "reason"]
    if with_plasmids:
        cols.append("plasmids")
    with open(path, "w", newline="") as fh:
        fh.write("\t".join(cols) + "\n")
        for cid, ln, lab, pl in rows:
            vals = [cid, ln, lab, "1", "0", pl.split(",")[0], "x"]
            if with_plasmids:
                vals.append(pl)
            fh.write("\t".join(str(v) for v in vals) + "\n")


def write_bins(path, bins):
    with open(path, "w", newline="") as fh:
        fh.write("bin_id\tsequence_id\n")
        for b, cs in bins.items():
            for c in cs:
                fh.write("%s\t%s\n" % (b, c))


def read_tsv(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        lab = tmp / "labels.tsv"
        write_labels(lab, [("a", 100, "PLASMID", "T1"), ("b", 200, "PLASMID", "T1"),
                           ("c", 300, "PLASMID", "T2"), ("d", 400, "PLASMID", "T2"),
                           ("e", 500, "CHROMOSOME", ""), ("x", 50, "AMBIGUOUS", "T1"),
                           ("y", 60, "CHIMERIC", "T2"), ("s", 10, "SHORT", "")])
        labels = ba.read_labels(lab)
        lengths = ba.lengths_of(labels)
        tb = ba.truth_bins(labels)
        check("truth bins", tb == {"T1": {"a", "b"}, "T2": {"c", "d"}})

        # README toy example, excluded contigs present in prediction are ignored+counted
        bins = {"P1": ["a", "b", "c", "x"], "P2": ["d", "e", "y"]}
        r = ba.eval_bestmatch(bins, labels)
        check("toy status", r["status"] == "ok")
        check("toy count", near(r["precision_count"], 0.6) and near(r["recall_count"], 0.75)
              and near(r["f1_count"], 2 * 0.6 * 0.75 / 1.35))
        check("toy bp", near(r["precision_bp"], 700 / 1500) and near(r["recall_bp"], 0.7)
              and near(r["f1_bp"], 0.56))
        check("excluded counted", r["excluded"] == 2)

        # non one-to-one
        lab2 = {c: {"length": l, "label": "PLASMID", "plasmids": ["T"]} for c, l in (("a", 100), ("b", 200))}
        r = ba.eval_bestmatch({"P1": ["a"], "P2": ["b"]}, lab2)
        check("non-1to1 count", near(r["precision_count"], 1.0) and near(r["recall_count"], 0.5))
        check("non-1to1 bp", near(r["precision_bp"], 1.0) and near(r["recall_bp"], 200 / 300))
        check("count != bp", not near(r["recall_count"], r["recall_bp"]))
        # duplicates counted once
        r = ba.eval_bestmatch({"P1": ["a", "a", "b"]}, lab2)
        check("duplicates once", near(r["precision_count"], 1.0) and near(r["recall_count"], 1.0))

        # no predicted bins: precision blank, recall 0, F1 0
        r = ba.eval_bestmatch({}, labels)
        check("no pred", r["status"] == "no_predicted_bins" and r["precision_count"] is None
              and r["recall_count"] == 0.0 and r["f1_count"] == 0.0 and r["f1_bp"] == 0.0)
        # no truth plasmids: all blank
        nolab = {"a": {"length": 5, "label": "CHROMOSOME", "plasmids": []}}
        r = ba.eval_bestmatch({"P": ["a"]}, nolab)
        check("no truth", r["status"] == "no_truth_plasmid_contigs" and r["f1_count"] is None)
        # reassembled sequences
        r = ba.eval_bestmatch({"P": ["a", "novel_seq"]}, labels)
        check("not assembly", r["status"] == "not_applicable_not_assembly_contigs"
              and r["precision_bp"] is None)
        # fallback to best_plasmid when plasmids column absent
        lab3 = tmp / "labels_noplasmids.tsv"
        write_labels(lab3, [("a", 100, "PLASMID", "T1")], with_plasmids=False)
        check("fallback best_plasmid", ba.truth_bins(ba.read_labels(lab3)) == {"T1": {"a"}})
        # contig in several truth plasmids
        lab4 = tmp / "labels_multi.tsv"
        write_labels(lab4, [("a", 100, "PLASMID", "T1,T2"), ("b", 100, "PLASMID", "T2")])
        check("multi plasmid", ba.truth_bins(ba.read_labels(lab4)) == {"T1": {"a"}, "T2": {"a", "b"}})

        # dissimilarity
        d = ba.dissimilarity({"P1": ["a", "b", "c"], "P2": ["d", "e"]}, tb, lengths, 1.0)
        # e is chromosome here, so it is extra
        check("toy dissim", near(d["split"], 300) and near(d["join"], 300) and near(d["extra"], 500)
              and near(d["missing"], 0) and near(d["norm"], 2500) and near(d["dissim"], 0.44))
        check("empty/empty", ba.dissimilarity({}, {}, lengths)["dissim"] == 0.0)
        check("one empty", ba.dissimilarity({}, tb, lengths)["dissim"] == 1.0
              and ba.dissimilarity(tb, {}, lengths)["dissim"] == 1.0)
        check("identical", ba.dissimilarity(tb, tb, lengths)["dissim"] == 0.0)
        disj = ba.dissimilarity({"Q": ["e"]}, tb, lengths)
        check("disjoint", near(disj["dissim"], 1.0))
        ps = ba.dissimilarity({"P": ["a", "b", "c", "d"]}, tb, lengths, 1.0)
        check("pure split a1", near(ps["split"], 300) and ps["join"] == 0 and ps["extra"] == 0
              and ps["missing"] == 0 and near(ps["dissim"], 0.15))
        ps5 = ba.dissimilarity({"P": ["a", "b", "c", "d"]}, tb, lengths, 0.5)
        norm5 = 2 * sum(lengths[c] ** 0.5 for c in "abcd")
        check("pure split a.5", near(ps5["split"], 300 ** 0.5) and near(ps5["dissim"], 300 ** 0.5 / norm5))
        pj = ba.dissimilarity(tb, {"P": {"a", "b", "c", "d"}}, lengths, 1.0)
        check("pure join", near(pj["join"], 300) and pj["split"] == 0 and near(pj["dissim"], 0.15))
        rp = ba.dissimilarity({"P1": ["a", "b"], "P2": ["b", "c"]}, tb, lengths, 1.0)
        check("repeats dropped", rp["repeats_dropped"] == 1)
        check("pairwise", near(ba.pairwise_dissimilarity({"P": ["a", "b", "c", "d"]}, tb, lengths, 1.0), 0.15))

        # CLI: eval, per-bin, dissim, export
        bp = tmp / "pred_T.bins.tsv"
        write_bins(bp, {"P1": ["a", "b", "c"], "P2": ["d", "e"]})
        out, pb = tmp / "eval.tsv", tmp / "perbin.tsv"
        check("eval rc", ba.main(["eval", "--labels", str(lab), "--bins", str(bp), "--sample", "S",
                                   "--tool", "T", "--out", str(out), "--per-bin-out", str(pb)]) == 0)
        row = read_tsv(out)[0]
        check("eval cols", list(row)[:3] == ["sample", "tool", "bestmatch_status"] and len(row) == 10)
        check("eval values", row["bestmatch_status"] == "ok" and row["bestmatch_precision_count"] == "0.600000"
              and row["bestmatch_f1_bp"] == "0.560000" and row["bestmatch_contigs_excluded"] == "2")
        check("per-bin rows", len(read_tsv(pb)) == 4)
        dout, pre = tmp / "dis.tsv", str(tmp / "exp")
        check("dissim rc", ba.main(["dissim", "--labels", str(lab), "--bins", str(bp), "--sample", "S",
                                     "--tool", "T", "--out", str(dout), "--alpha", "1",
                                     "--export-prefix", pre]) == 0)
        row = read_tsv(dout)[0]
        check("dissim cols", list(row) == ["sample", "tool", "dissim_status", "bin_dissimilarity",
                                           "dissim_split_cost", "dissim_join_cost", "dissim_extra_cost",
                                           "dissim_missing_cost", "dissim_norm", "dissim_repeats_dropped"])
        check("dissim value", row["bin_dissimilarity"] == "0.440000" and row["dissim_repeats_dropped"] == "0")
        for n in ("truth_bins", "pred_bins"):
            first = (tmp / ("exp.%s.tsv" % n)).read_text().splitlines()[0]
            check("export header " + n, first == "plasmid\tcontig\tcontig_len")
        check("export truth rows", len((tmp / "exp.truth_bins.tsv").read_text().splitlines()) == 5)
        # reassembled tool
        bad = tmp / "bad.bins.tsv"
        write_bins(bad, {"P": ["NODE_1_reassembled"]})
        ba.main(["dissim", "--labels", str(lab), "--bins", str(bad), "--sample", "S", "--tool", "R",
                 "--out", str(dout)])
        row = read_tsv(dout)[0]
        check("dissim not applicable", row["dissim_status"] == ba.NOT_ASSEMBLY and row["bin_dissimilarity"] == "")

        # matrix
        res, data = tmp / "results", tmp / "data"
        for s in ("s1", "s2"):
            (res / s).mkdir(parents=True)
            (data / s).mkdir(parents=True)
            write_labels(data / s / "contig_labels.tsv", [("a", 100, "PLASMID", "T1"), ("b", 200, "PLASMID", "T1"),
                                                         ("c", 300, "PLASMID", "T2"), ("d", 400, "PLASMID", "T2")])
            write_bins(res / s / "pred_good.bins.tsv", {"P1": ["a", "b"], "P2": ["c", "d"]})
            write_bins(res / s / "pred_merge.bins.tsv", {"P": ["a", "b", "c", "d"]})
            write_bins(res / s / "pred_reasm.bins.tsv", {"P": ["zzz"]})
        mo = tmp / "matrix.tsv"
        check("matrix rc", ba.main(["matrix", "--results-dir", str(res), "--data-dir", str(data),
                                     "--out", str(mo), "--alpha", "1"]) == 0)
        rows = {(r["tool_a"], r["tool_b"]): r for r in read_tsv(mo)}
        check("matrix keys", set(rows) == {("good", "truth"), ("merge", "truth"), ("good", "merge")})
        check("matrix good vs truth", near(float(rows[("good", "truth")]["mean_dissimilarity"]), 0.0)
              and rows[("good", "truth")]["n_samples"] == "2")
        check("matrix merge", near(float(rows[("merge", "truth")]["mean_dissimilarity"]), 0.15)
              and near(float(rows[("good", "merge")]["mean_dissimilarity"]), 0.15))

    if FAILS:
        print("FAILED:", len(FAILS))
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
