#!/usr/bin/env python3
"""
baseline_predictors.py -- trivial reference points that every benchmarked
tool should beat.

A benchmark without baselines cannot say whether a tool adds anything over
the obvious (question bank Q62, Q78, Q108). Three baselines run like tools on
each isolate's short-read assembly and are scored exactly like them, on the
classification track (they never group contigs into plasmids):

  baseline_coverage   a contig is called plasmid when its assembler-reported
                      depth is >= --ratio x the assembly's length-weighted
                      median depth (plasmids are often multi-copy). No
                      database; reads SPAdes (`cov_`) or Unicycler
                      (`depth=...x`) headers.
  baseline_reference  a contig is called plasmid when >= --min-query-coverage
                      of it aligns (minimap2, primary, identity >=
                      --min-identity) to the local plasmid reference set
                      (DATA_DIR/db/plasmid_reference/reference.fasta, built by
                      build_plasmid_reference_set.py) -- a stand-in for a
                      "PLSDB BLAST/Mash" search. Every contig also gets a
                      probability (its best aligned fraction), so this
                      baseline feeds the PR-curve and calibration outputs.

  baseline_replicon   a contig is called plasmid when it carries a replicon
                      marker hit (Abricate-style TSV from e.g. `abricate --db
                      plasmidfinder`, given with --replicon-hits) of identity >=
                      --min-identity and coverage >= --min-coverage (percent).
                      plsMD's Col-vs-Inc rule is the default: a Col* hit is
                      dropped when an Inc* hit is on the same contig (it points
                      to a co-integrate, not a separate plasmid); disable with
                      --keep-col-with-inc. Contigs shorter than --min-length
                      are never called. A missing or empty hits file exits 3
                      (not applicable).

All write the standard adapter outputs: <out>.plasmid.fasta, a one-contig-
per-bin <out>.bins.tsv, and (reference only) <out>.candidates.fasta and
<out>.scores.tsv (adapters/SCORES.md contract).

Standard library only (minimap2 is called for the reference baseline).
"""

import argparse
import re
import statistics
import subprocess
import sys

COV = re.compile(r"(?:_cov_|\bdepth=)([0-9.]+)", re.IGNORECASE)
# Exit status meaning "this baseline cannot apply to this input" -- stage 4
# records it as skipped, never as a failed run scored zero.
NOT_APPLICABLE = 3


def read_fasta(path):
    records, name, header, chunks = [], None, "", []
    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.rstrip("\n")
            if line.startswith(">"):
                if name is not None:
                    records.append((name, header, "".join(chunks)))
                header = line[1:]
                name, chunks = header.split()[0], []
            elif line.strip():
                chunks.append(line.strip())
    if name is not None:
        records.append((name, header, "".join(chunks)))
    return records


def write_outputs(prefix, records, chosen):
    with open(prefix + ".plasmid.fasta", "w", encoding="utf-8") as handle:
        for name, _, seq in records:
            if name in chosen:
                handle.write(f">{name}\n{seq}\n")
    with open(prefix + ".bins.tsv", "w", encoding="utf-8") as handle:
        handle.write("bin_id\tsequence_id\n")
        for name, _, _ in records:
            if name in chosen:
                handle.write(f"{name}\t{name}\n")


def coverage_baseline(args):
    records = read_fasta(args.contigs)
    depth = {}
    for name, header, seq in records:
        match = COV.search(header)
        if match:
            depth[name] = float(match.group(1))
    if not depth:
        sys.stderr.write("NOT APPLICABLE: no contig header carries a depth (SPAdes cov_ or Unicycler "
                         "depth=); the coverage baseline cannot run on this assembly\n")
        sys.exit(NOT_APPLICABLE)
    weighted = sorted((depth[n], len(s)) for n, _, s in records if n in depth)
    half, running, median = sum(w for _, w in weighted) / 2, 0, weighted[-1][0]
    for value, weight in weighted:
        running += weight
        if running >= half:
            median = value
            break
    chosen = {n for n, _, s in records
              if n in depth and len(s) >= args.min_length and depth[n] >= args.ratio * median}
    write_outputs(args.out_prefix, records, chosen)
    sys.stderr.write(f"[baseline_coverage] median depth {median:.1f}; {len(chosen)} contig(s) >= "
                     f"{args.ratio}x called plasmid\n")


def reference_baseline(args):
    records = read_fasta(args.contigs)
    result = subprocess.run(["minimap2", "-c", "--secondary=no", "-x", "asm5", "-t", str(args.threads),
                             args.reference, args.contigs], text=True, capture_output=True)
    if result.returncode != 0:
        sys.exit(f"ERROR: minimap2 failed: {result.stderr.strip()[:300]}")
    covered = {}
    for line in result.stdout.splitlines():
        f = line.split("\t")
        if len(f) < 12:
            continue
        block, matches = int(f[10]), int(f[9])
        if not block or matches / block < args.min_identity:
            continue
        covered.setdefault(f[0], []).append((int(f[2]), int(f[3])))
    fraction = {}
    for name, _, seq in records:
        total, end = 0, -1
        for start, stop in sorted(covered.get(name, [])):
            total += max(0, stop - max(end, start))
            end = max(end, stop)
        fraction[name] = min(1.0, total / len(seq)) if seq else 0.0
    chosen = {n for n, f in fraction.items() if f >= args.min_query_coverage}
    write_outputs(args.out_prefix, records, chosen)
    with open(args.out_prefix + ".candidates.fasta", "w", encoding="utf-8") as handle:
        for name, _, seq in records:
            handle.write(f">{name}\n{seq}\n")
    with open(args.out_prefix + ".scores.tsv", "w", encoding="utf-8") as handle:
        handle.write("record_id\tprobability\n")
        for name, _, _ in records:
            handle.write(f"{name}\t{fraction[name]:.4f}\n")
    sys.stderr.write(f"[baseline_reference] {len(chosen)} of {len(records)} contig(s) match the plasmid "
                     f"reference over >= {args.min_query_coverage:.0%}\n")


def read_replicon_hits(path, min_identity, min_coverage):
    """{contig: [gene, ...]} for Abricate-style hits passing the thresholds, or None if no data rows."""
    try:
        with open(path, encoding="utf-8") as handle:
            lines = [ln.rstrip("\r\n") for ln in handle if ln.strip()]
    except OSError:
        return None
    if not lines:
        return None
    header = [c.lstrip("#").strip().upper() for c in lines[0].split("\t")]
    try:
        i_seq, i_gene = header.index("SEQUENCE"), header.index("GENE")
        i_cov, i_id = header.index("%COVERAGE"), header.index("%IDENTITY")
    except ValueError:
        sys.exit("ERROR: --replicon-hits is not an Abricate-style TSV (need SEQUENCE, GENE, "
                 "%COVERAGE, %IDENTITY columns)")
    rows = [ln.split("\t") for ln in lines[1:]]
    if not rows:
        return None
    hits = {}
    for f in rows:
        try:
            if float(f[i_id]) < min_identity or float(f[i_cov]) < min_coverage:
                continue
            hits.setdefault(f[i_seq], []).append(f[i_gene])
        except (ValueError, IndexError):
            continue
    return hits


def replicon_baseline(args):
    records = read_fasta(args.contigs)
    hits = read_replicon_hits(args.replicon_hits, args.min_identity, args.min_coverage)
    if hits is None:
        sys.stderr.write("NOT APPLICABLE: no replicon hits file or no hit rows; the replicon baseline "
                         "cannot run on this assembly\n")
        sys.exit(NOT_APPLICABLE)
    chosen, dropped = set(), 0
    for name, _, seq in records:
        genes = hits.get(name, [])
        if len(seq) < args.min_length or not genes:
            continue
        if not args.keep_col_with_inc:
            has_inc = any(g.lower().startswith("inc") for g in genes)
            kept = [g for g in genes if not (has_inc and g.lower().startswith("col"))]
            dropped += len(genes) - len(kept)
            genes = kept
        if genes:
            chosen.add(name)
    write_outputs(args.out_prefix, records, chosen)
    sys.stderr.write(f"[baseline_replicon] {len(chosen)} contig(s) carry a replicon marker "
                     f"({dropped} Col hit(s) dropped by the Col-vs-Inc rule)\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    c = sub.add_parser("coverage")
    c.add_argument("--contigs", required=True)
    c.add_argument("--out-prefix", required=True, help="writes <prefix>.plasmid.fasta and <prefix>.bins.tsv")
    c.add_argument("--ratio", type=float, default=1.5)
    c.add_argument("--min-length", type=int, default=1000)
    c.set_defaults(func=coverage_baseline)
    r = sub.add_parser("reference")
    r.add_argument("--contigs", required=True)
    r.add_argument("--reference", required=True, help="plasmid reference FASTA")
    r.add_argument("--out-prefix", required=True)
    r.add_argument("--min-query-coverage", type=float, default=0.8)
    r.add_argument("--min-identity", type=float, default=0.95)
    r.add_argument("--threads", type=int, default=1)
    r.set_defaults(func=reference_baseline)
    p = sub.add_parser("replicon")
    p.add_argument("--contigs", required=True)
    p.add_argument("--replicon-hits", required=True, help="Abricate-style TSV of replicon hits on the contigs")
    p.add_argument("--out-prefix", required=True)
    p.add_argument("--min-identity", type=float, default=90.0, help="percent (default 90)")
    p.add_argument("--min-coverage", type=float, default=60.0, help="percent (default 60)")
    p.add_argument("--min-length", type=int, default=1000)
    p.add_argument("--keep-col-with-inc", action="store_true",
                   help="disable the default rule that drops Col* hits on contigs that also carry an Inc* hit")
    p.set_defaults(func=replicon_baseline)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
