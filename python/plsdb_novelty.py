#!/usr/bin/env python3
"""How novel is each truth plasmid against PLSDB, and does recovery depend on it?

Why: a tool that looks a plasmid up in a database (or was trained on one) recovers a *known* plasmid far more easily than a *novel* one, so a high score on
known plasmids says little about new ones (the plsMD paper's own novel-set results fall from 93 to 78 percent recall). `flag_database_overlap.py`
screens by date and `database_containment.py` asks whether a plasmid is inside a tool's OWN database. This asks one tool-independent question of the
truth: how much of each truth plasmid does the public PLSDB already hold? Each truth plasmid is aligned to a PLSDB FASTA (minimap2, preset asm20) and
classified by the single best PLSDB record:

  known     one record covers >= --known-coverage (0.80) of it at >= --known-identity (0.95)   (a close relative is in PLSDB)
  related   not known, but a record covers >= --related-coverage (0.30)                       (a shared backbone or module)
  novel     otherwise                                                                         (no substantial PLSDB relative)

and recovery (per-plasmid completeness and the share recovered) is tabulated per tool and class with the known-minus-novel gap, whose interval is a
cluster bootstrap that resamples whole studies. Outputs

  <prefix>.tsv           one row per sample and truth plasmid: best PLSDB record, coverage, identity, class
  <prefix>_recovery.tsv  one row per tool, track and class: plasmids, studies, mean completeness, recovered share, and the gap to `known`
  <prefix>.json          PLSDB file and provenance (release, checksum, date), thresholds, class counts, caveats

Limits, stated in the output: novelty is relative to the PLSDB release supplied (see its provenance file), not to all of nature; a plasmid is only as novel as
its best-matching record; alignment-based coverage misses relatedness below roughly 5 percent divergence; and a truth plasmid first deposited after the
PLSDB release is novel by date, not by design. Descriptive: it never changes a score, a ranking or a recommendation. Needs minimap2 (the pipeline's aligner).

  python python/plsdb_novelty.py --data-dir data --results-dir results --samples s1 s2 --plsdb data/db/plsdb/sequences.fasta --out-prefix results/benchmark.plsdb_novelty
"""
import argparse
import csv
import json
import os
import random
import sys
import tempfile
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import database_containment as dc  # noqa: E402

TAB, NL = chr(9), chr(10)
FIELDS = ["sample", "sequence_id", "length", "best_record", "coverage", "identity", "novelty"]
RECOVERY_FIELDS = ["analysis_track", "tool", "novelty", "n_plasmids", "n_studies", "mean_completeness", "recovered_fraction", "gap_to_known", "gap_ci_low", "gap_ci_high", "status"]
CLASSES = ("known", "related", "novel")


def classify(coverage, identity, known_coverage, known_identity, related_coverage):
    if coverage >= known_coverage and identity >= known_identity:
        return "known"
    if coverage >= related_coverage:
        return "related"
    return "novel"


def read_tsv(path):
    if not path or not os.path.isfile(path):
        return None
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader((l for l in handle if l.strip() and not l.startswith("#")), delimiter=TAB))


def gather_queries(data_dir, samples, query_path):
    """Write every sample's truth plasmids into ONE FASTA (so PLSDB is indexed once) and return [(synthetic id, sample, sequence id, length)]."""
    queries = []
    scheme_file = {"evidence": "truth.scored.tsv", "nonchromosomal": "truth.nonchromosomal.tsv"}.get(os.environ.get("TRUTH_LABEL_SCHEME", "ncbi"), "truth.tsv")
    with open(query_path, "w", encoding="utf-8") as handle:
        for sample in samples:
            sample_dir = os.path.join(data_dir, sample)
            truth = os.path.join(sample_dir, scheme_file)
            if not os.path.isfile(truth):
                truth = os.path.join(sample_dir, "truth.tsv")
            reference = os.path.join(sample_dir, "reference.fna")
            if not (os.path.isfile(truth) and os.path.isfile(reference)):
                continue
            plasmids = set(dc.truth_plasmids(truth))
            if not plasmids:
                continue
            sequences = dc.read_fasta(reference, wanted=plasmids)
            for seq_id in sorted(plasmids):
                if seq_id in sequences:
                    synthetic = f"q{len(queries)}"
                    handle.write(f">{synthetic}{NL}{sequences[seq_id]}{NL}")
                    queries.append((synthetic, sample, seq_id, len(sequences[seq_id])))
    return queries


def novelty_table(data_dir, samples, plsdb, threads, thresholds):
    rows = []
    with tempfile.TemporaryDirectory(prefix="plasbench_novelty_") as tmp:
        query = os.path.join(tmp, "truth_plasmids.fa")
        queries = gather_queries(data_dir, samples, query)
        best = dc.containment(query, plsdb, threads, preset="asm20") if queries else {}
        for synthetic, sample, seq_id, length in queries:
            record, coverage, identity = best.get(synthetic, ("", 0.0, 0.0))
            rows.append({"sample": sample, "sequence_id": seq_id, "length": length, "best_record": record, "coverage": coverage, "identity": identity,
                         "novelty": classify(coverage, identity, *thresholds)})
    rows.sort(key=lambda r: (r["sample"], r["sequence_id"]))
    return rows


def mean(values):
    return sum(values) / len(values) if values else None


def recovery_table(results_dir, novelty_rows, sample_sheet, seed, bootstrap):
    cls = {(r["sample"], r["sequence_id"]): r["novelty"] for r in novelty_rows}
    sheet = {r["sample_id"]: r for r in (read_tsv(sample_sheet) or []) if r.get("sample_id")}
    cells = defaultdict(lambda: defaultdict(list))  # (track, tool) -> (cluster, class) -> [(completeness, recovered)]
    for sample in sorted({s for s, _ in cls}):
        sdir = os.path.join(results_dir, sample)
        if not os.path.isdir(sdir):
            continue
        meta = sheet.get(sample, {})
        cluster = meta.get("cluster_key") or meta.get("bioproject") or sample
        for name in sorted(os.listdir(sdir)):
            if not name.endswith(".per_plasmid.tsv"):
                continue
            tool = name[:-len(".per_plasmid.tsv")]
            for row in read_tsv(os.path.join(sdir, name)) or []:
                key = (sample, row.get("sequence_id"))
                try:
                    completeness = float(row["completeness"])
                except (KeyError, TypeError, ValueError):
                    continue
                if key in cls:
                    cells[(row.get("analysis_track") or "short_read", tool)][(cluster, cls[key])].append((completeness, 1.0 if row.get("recovered") == "1" else 0.0))
    rng = random.Random(seed)
    out = []
    for (track, tool), groups in sorted(cells.items()):
        clusters = sorted({c for c, _ in groups})
        known_all = [v for (c, k), vs in groups.items() if k == "known" for v in vs]
        for klass in CLASSES:
            vals = [v for (c, k), vs in groups.items() if k == klass for v in vs]
            if not vals:
                continue
            row = {"analysis_track": track, "tool": tool, "novelty": klass, "n_plasmids": len(vals), "n_studies": len({c for (c, k) in groups if k == klass}),
                   "mean_completeness": mean([v[0] for v in vals]), "recovered_fraction": mean([v[1] for v in vals]), "gap_to_known": None, "gap_ci_low": None,
                   "gap_ci_high": None, "status": "reference" if klass == "known" else ""}
            if klass != "known":
                if not known_all:
                    row["status"] = "no known plasmids to compare with"
                elif len({c for (c, k) in groups if k == klass}) < 3 or len(clusters) < 5:
                    gap = mean([v[0] for v in known_all]) - row["mean_completeness"]
                    row.update(gap_to_known=gap, status="too few studies for an interval")
                else:
                    gap = mean([v[0] for v in known_all]) - row["mean_completeness"]
                    draws = []
                    for _ in range(bootstrap):
                        pick = [rng.choice(clusters) for _ in clusters]
                        a = [v[0] for c in pick for v in groups.get((c, "known"), [])]
                        b = [v[0] for c in pick for v in groups.get((c, klass), [])]
                        if a and b:
                            draws.append(mean(a) - mean(b))
                    draws.sort()
                    if len(draws) >= bootstrap // 2:
                        row.update(gap_to_known=gap, gap_ci_low=draws[int(0.025 * (len(draws) - 1))], gap_ci_high=draws[int(0.975 * (len(draws) - 1))],
                                   status="gap supported" if (draws[int(0.025 * (len(draws) - 1))] > 0 or draws[int(0.975 * (len(draws) - 1))] < 0) else "no clear gap")
                    else:
                        row.update(gap_to_known=gap, status="too few studies for an interval")
            out.append(row)
    return out


def write_tsv(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter=TAB, lineterminator=NL)
        writer.writerow(fields)
        for r in rows:
            writer.writerow(["" if r.get(c) is None else (f"{r[c]:.4f}" if isinstance(r[c], float) else r[c]) for c in fields])


def run(data_dir, results_dir, samples, plsdb, sample_sheet, out_prefix, thresholds=(0.80, 0.95, 0.30), threads=1, seed=20261117, bootstrap=500):
    rows = novelty_table(data_dir, samples, plsdb, threads, thresholds)
    recovery = recovery_table(results_dir, rows, sample_sheet, seed, bootstrap)
    write_tsv(out_prefix + ".tsv", FIELDS, rows)
    write_tsv(out_prefix + "_recovery.tsv", RECOVERY_FIELDS, recovery)
    provenance = {}
    prov_path = os.path.join(os.path.dirname(plsdb), "sequences.provenance.json")
    if os.path.isfile(prov_path):
        with open(prov_path, encoding="utf-8") as handle:
            provenance = json.load(handle)
    counts = {k: sum(1 for r in rows if r["novelty"] == k) for k in CLASSES}
    summary = {"plsdb_file": os.path.basename(plsdb), "plsdb_provenance": provenance or "no sequences.provenance.json beside the file: the PLSDB release is not recorded",
               "thresholds": {"known_coverage": thresholds[0], "known_identity": thresholds[1], "related_coverage": thresholds[2]}, "alignment": "minimap2 -x asm20",
               "truth_plasmids": len(rows), "classes": counts,
               "caveats": ["Novelty is relative to the PLSDB release supplied, not to all known plasmids.",
                           "A plasmid is only as novel as its best-matching PLSDB record; relatedness below about 5 percent divergence is not detected by alignment.",
                           "A truth plasmid deposited after the PLSDB release is novel by date, not by design.",
                           "Descriptive: never changes a score, a ranking or a recommendation."]}
    with open(out_prefix + ".json", "w", encoding="utf-8", newline="") as handle:
        json.dump(summary, handle, indent=2, ensure_ascii=False)
        handle.write(NL)
    return rows, recovery, summary


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--results-dir", required=True)
    ap.add_argument("--samples", nargs="+", required=True)
    ap.add_argument("--plsdb", required=True, help="PLSDB sequences FASTA (env/download_plsdb.sh writes data/db/plsdb/sequences.fasta)")
    ap.add_argument("--sample-sheet", help="for the study (cluster) of each sample")
    ap.add_argument("--out-prefix", required=True)
    ap.add_argument("--known-coverage", type=float, default=0.80)
    ap.add_argument("--known-identity", type=float, default=0.95)
    ap.add_argument("--related-coverage", type=float, default=0.30)
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--bootstrap", type=int, default=500)
    ap.add_argument("--seed", type=int, default=20261117)
    args = ap.parse_args()
    if not os.path.isfile(args.plsdb):
        sys.exit(f"ERROR: PLSDB FASTA not found: {args.plsdb} (run env/download_plsdb.sh with PLSDB_URL)")
    rows, recovery, summary = run(args.data_dir, args.results_dir, args.samples, args.plsdb, args.sample_sheet, args.out_prefix,
                                  (args.known_coverage, args.known_identity, args.related_coverage), args.threads, args.seed, args.bootstrap)
    print(f"PLSDB novelty: {summary['truth_plasmids']} truth plasmids: " + ", ".join(f"{n} {k}" for k, n in summary["classes"].items()) + f"; wrote {args.out_prefix}.tsv")


if __name__ == "__main__":
    main()
