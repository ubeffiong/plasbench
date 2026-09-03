#!/usr/bin/env python3
"""Write the synthetic cohort the offline demo scores.

The demo exists to exercise the engine without downloads or installed tools, so
every byte here is fabricated and labelled as such. What it is not is arbitrary:
each record is shaped to drive one behaviour the report claims to show, so that
running the demo actually exercises the tracks, bin flow, structural calls and
drilldown rather than leaving them in their empty states.

Deterministic by construction -- no randomness anywhere -- so two runs produce
byte-identical inputs and any change in the report is a change in the code.

Nothing here is a biological claim. The organism names label cohort filters;
the sequences are homopolymer padding of the right length.
"""

import argparse
import csv
from pathlib import Path


# sample -> organism, study, depth, technology, country
SAMPLES = [
    ("ecoli_a", "Escherichia coli", "Demo study A", 120, "hybrid", "Nigeria"),
    ("ecoli_b", "Escherichia coli", "Demo study A", 95, "hybrid", "Nigeria"),
    ("kpneu_a", "Klebsiella pneumoniae", "Demo study B", 210, "hybrid", "Kenya"),
    ("kpneu_b", "Klebsiella pneumoniae", "Demo study B", 65, "long_read", "Kenya"),
    ("abauma_a", "Acinetobacter baumannii", "Demo study C", 140, "hybrid", "Egypt"),
    ("abauma_b", "Acinetobacter baumannii", "Demo study C", 45, "long_read", "Egypt"),
]

# sample -> chromosome length, [(plasmid, length, circular)]
TRUTH = {
    "ecoli_a": (500_000, [("pA", 90_000, True), ("pB", 8_000, False)]),
    "ecoli_b": (480_000, [("pC", 65_000, True), ("pD", 4_500, False)]),
    "kpneu_a": (520_000, [("pE", 150_000, True), ("pF", 12_000, False), ("pG", 3_000, False)]),
    "kpneu_b": (510_000, [("pH", 110_000, True)]),
    "abauma_a": (390_000, [("pI", 25_000, True), ("pJ", 6_000, False)]),
    "abauma_b": (400_000, [("pK", 18_000, False)]),
}

# Curated AMR loci, as a real cohort would supply them.
AMR = {
    "pA": [(12_400, 13_277, "blaCTX-M-15"), (45_100, 45_910, "sul1")],
    "pC": [(8_200, 9_013, "blaKPC-2")],
    "pE": [(61_000, 61_813, "blaNDM-1"), (99_500, 100_121, "armA")],
    "pI": [(3_100, 3_726, "tetA")],
}

# Replicon / mobility context, as an annotation caller would emit it.
FEATURES = {
    "pA": [(0, 1_100, "replicon", "IncFIB"), (30_000, 31_400, "mob", "MOBF")],
    "pC": [(0, 980, "replicon", "IncI1")],
    "pE": [(0, 1_240, "replicon", "IncFII"), (70_000, 71_200, "mob", "MOBH")],
    "pH": [(0, 1_050, "replicon", "IncA/C")],
    "pI": [(0, 900, "replicon", "ColE1")],
}

TOOLS = ["mob_like", "platon_like", "spades_like", "gplas_like", "weak_like"]
# Only declared binners get bin membership, matching tool_capabilities.tsv.
BINNERS = {"mob_like", "gplas_like"}
# One method fails on one sample: failure must not be scored as a zero.
FAILS = {("abauma_b", "weak_like")}


def block(record, qlen, qstart, qend, strand, target, tlen, tstart, tend, identity=1.0, mapq=60):
    span = tend - tstart
    return [record, qlen, qstart, qend, strand, target, tlen, tstart, tend,
            int(span * identity), span, mapq]


def predictions(sample, tool, chrom_len, plasmids):
    """Alignment blocks for one method, shaped to drive a named behaviour."""
    rows, chrom = [], f"chr_{sample}"
    first = plasmids[0]
    name, length, _ = first

    if tool == "mob_like":
        # Strong binner: clean full-length recovery of every plasmid.
        for index, (pname, plen, _) in enumerate(plasmids, start=1):
            rows.append(block(f"mob_ctg{index}", plen, 0, plen, "+", pname, plen, 0, plen))

    elif tool == "platon_like":
        # Contig classifier: good, but leaves the smallest plasmid uncovered and
        # drags in a chromosomal contig -> false positives without a bin story.
        # Its largest plasmid is recovered in two pieces with a genuine query gap,
        # so the uncovered middle is missing reference rather than a false join.
        # One record, two blocks, with a gap on the query as well as the reference:
        # the prediction stops, so the uncovered middle is missing reference rather
        # than an adjacency the record wrongly asserts.
        head = int(length * 0.55)
        tail_start = int(length * 0.68)
        tail_len = length - tail_start
        qlen = head + tail_len + 4_000
        rows.append(block("plt_ctg1", qlen, 0, head, "+", name, length, 0, head))
        rows.append(block("plt_ctg1", qlen, head + 4_000, head + 4_000 + tail_len,
                          "+", name, length, tail_start, length))
        for index, (pname, plen, _) in enumerate(plasmids[1:-1] or plasmids[1:], start=2):
            rows.append(block(f"plt_ctg{index}", plen, 0, plen, "+", pname, plen, 0, plen))
        rows.append(block("plt_chr", 6_000, 0, 6_000, "+", chrom, chrom_len, 1_000, 7_000))

    elif tool == "spades_like":
        # Re-assembler: fragments the largest plasmid, duplicates a repeat, and
        # joins two distant loci on one contig -> unsupported join.
        half = length // 2
        rows.append(block("spa_ctg1", half, 0, half, "+", name, length, 0, half, identity=0.97))
        # duplicated: the same reference interval covered twice by one record
        rows.append(block("spa_dup", 4_000, 0, 2_000, "+", name, length, half, half + 2_000))
        rows.append(block("spa_dup", 4_000, 2_000, 4_000, "+", name, length, half + 1_000, half + 3_000))
        # unsupported join: query runs straight on, reference jumps
        rows.append(block("spa_join", 3_000, 0, 1_500, "+", name, length, length - 9_000, length - 7_500))
        rows.append(block("spa_join", 3_000, 1_500, 3_000, "+", name, length, length - 3_000, length - 1_500))
        # Cover most of the remaining reference so completeness stays high while the
        # rearrangements above keep collinearity low: a complete but discordant
        # reconstruction, which completeness alone would report as a clean win.
        rows.append(block("spa_fill", length // 2, 0, length // 2, "+", name, length,
                          half + 3_000, half + 3_000 + length // 2, identity=0.95))
        for index, (pname, plen, _) in enumerate(plasmids[1:], start=1):
            rows.append(block(f"spa_small{index}", plen, 0, plen, "+", pname, plen, 0, plen, identity=0.86))

    elif tool == "gplas_like":
        # Graph binner: splits the largest plasmid across two bins, and emits one
        # inverted segment plus a chimeric contig spanning two plasmids.
        third = length // 3
        rows.append(block("gpl_a", third, 0, third, "+", name, length, 0, third))
        rows.append(block("gpl_b", third, 0, third, "-", name, length, third, 2 * third))
        if len(plasmids) > 1:
            other, olen, _ = plasmids[1]
            rows.append(block("gpl_chimera", olen + 2_000, 0, 2_000, "+", name, length, 2 * third, 2 * third + 2_000))
            rows.append(block("gpl_chimera", olen + 2_000, 2_000, 2_000 + olen, "+", other, olen, 0, olen))
        else:
            rows.append(block("gpl_c", third, 0, third, "+", name, length, 2 * third, 3 * third))

    elif tool == "weak_like":
        # Poor method: partial coverage, low identity, and a record that reaches
        # the chromosome and a second plasmid at once -> ambiguous assignment.
        rows.append(block("wk_part", length // 4, 0, length // 4, "+", name, length, 0, length // 4, identity=0.82))
        rows.append(block("wk_amb", 5_000, 0, 1_500, "+", name, length, length // 2, length // 2 + 1_500))
        rows.append(block("wk_amb", 5_000, 1_500, 3_000, "+", chrom, chrom_len, 5_000, 6_500))
        if len(plasmids) > 1:
            other, olen, _ = plasmids[1]
            rows.append(block("wk_amb", 5_000, 3_000, 4_000, "+", other, olen, 0, 1_000))
    return rows


def write_tsv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(header)
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    root = args.out_dir
    root.mkdir(parents=True, exist_ok=True)

    write_tsv(root / "samples.tsv",
              ["sample_id", "organism", "truth_technology", "sample_origin",
               "read_depth_x", "source_study", "gram_group", "collection_country"],
              [[s, organism, tech, "synthetic", depth, study,
                "Gram-negative", country]
               for s, organism, study, depth, tech, country in SAMPLES])

    status = [["sample", "tool", "status", "prediction_fasta", "reason",
               "runtime_seconds", "peak_rss_kb"]]
    for sample, _, _, depth, _, _ in SAMPLES:
        chrom_len, plasmids = TRUTH[sample]
        sdir = root / sample
        sdir.mkdir(parents=True, exist_ok=True)

        write_tsv(sdir / "truth.tsv", ["sequence_id", "molecule_type", "length"],
                  [[f"chr_{sample}", "CHROMOSOME", chrom_len]]
                  + [[name, "PLASMID", length] for name, length, _ in plasmids])
        circular = [[name] for name, _, is_circular in plasmids if is_circular]
        if circular:
            write_tsv(sdir / "truth_circular.tsv", ["sequence_id"], circular)
        amr = [[name, start, end, gene] for name, _, _ in plasmids
               for start, end, gene in AMR.get(name, [])]
        if amr:
            write_tsv(sdir / "truth_amr.tsv", ["sequence_id", "start", "end", "gene_name"], amr)
        features = [[name, start, end, kind, label, "demo_annotator", "0.0-synthetic"]
                    for name, _, _ in plasmids for start, end, kind, label in FEATURES.get(name, [])]
        if features:
            write_tsv(sdir / "truth_features.tsv",
                      ["sequence_id", "start", "end", "feature_type", "label", "source", "version"],
                      features)

        for index, tool in enumerate(TOOLS):
            failed = (sample, tool) in FAILS
            if failed:
                status.append([sample, tool, "failed", "", "synthetic failure for demonstration", "", ""])
                continue
            rows = predictions(sample, tool, chrom_len, plasmids)
            paf = sdir / f"{tool}.pred_vs_ref.paf"
            with paf.open("w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write("\t".join(str(x) for x in row) + "\n")
            # Prediction FASTA: one record per aligned query, padded to length.
            lengths = {}
            for row in rows:
                lengths.setdefault(row[0], row[1])
            # Records are written at their declared length: the scorer checks the
            # PAF query length against the FASTA and rejects any disagreement.
            with (sdir / f"pred_{tool}.plasmid.fasta").open("w", encoding="utf-8") as handle:
                for record, qlen in lengths.items():
                    handle.write(f">{record}\n")
                    for start in range(0, qlen, 60):
                        handle.write("A" * min(60, qlen - start) + "\n")
            if tool in BINNERS:
                # One bin per contig for the strong binner; the splitter puts two
                # contigs in one bin so a merge edge appears in the flow.
                membership = []
                for record in lengths:
                    bin_id = "bin_1" if tool == "gplas_like" and record.startswith("gpl_") else f"bin_{record}"
                    membership.append([bin_id, record])
                write_tsv(sdir / f"pred_{tool}.bins.tsv", ["bin_id", "sequence_id"], membership)
            status.append([sample, tool, "completed", str(sdir / f"pred_{tool}.plasmid.fasta"), "",
                           str(40 + index * 25 + depth // 10), str(1_200_000 + index * 480_000)])

    write_tsv(root / "tool_status.tsv", status[0], status[1:])
    print(f"Wrote synthetic cohort: {len(SAMPLES)} samples x {len(TOOLS)} methods "
          f"({sum(len(v[1]) for v in TRUTH.values())} truth plasmids) under {root}")


if __name__ == "__main__":
    main()
