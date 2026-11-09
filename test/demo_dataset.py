#!/usr/bin/env python3
"""Write the synthetic cohort the offline demo scores.

The demo exists to exercise the engine without downloads or installed tools, so
every byte here is fabricated and labelled as such. What it is not is arbitrary:
each record is shaped to drive one behaviour the report claims to show, so that
running the demo actually exercises the tracks, bin flow, structural calls and
drilldown rather than leaving them in their empty states.

Deterministic by construction -- no randomness anywhere -- so two runs produce
byte-identical inputs and any change in the report is a change in the code.

Nothing here is a biological claim. The organism names label cohort filters.
Long records are padding; the short per-method record carries a deterministic
edited sequence with a CIGAR, so the drilldown has real nucleotides to show.
"""

import argparse
import csv
import functools
import json
import random
import sys
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
    "pA": [(0, 1_100, "replicon", "IncFIB"), (30_000, 31_400, "mob", "MOBF"),
           (52_000, 53_100, "insertion_sequence", "ISEcp1")],
    "pC": [(0, 980, "replicon", "IncI1"), (20_000, 21_050, "mob", "MOBP")],
    "pE": [(0, 1_240, "replicon", "IncFII"), (70_000, 71_200, "mob", "MOBH"),
           (120_000, 121_150, "insertion_sequence", "IS26")],
    "pH": [(0, 1_050, "replicon", "IncA/C")],
    "pI": [(0, 900, "replicon", "ColE1"), (9_000, 10_050, "mob", "MOBQ"),
           (20_000, 21_100, "insertion_sequence", "IS903")],
    "pJ": [(0, 820, "replicon", "ColRNAI")],
}

# Coding sequences, as a reference annotation caller would emit them. The
# category vocabulary is the one the explorer filters on, so every category is
# represented somewhere in the cohort.
PROTEINS = {
    "pA": [(2_000, 3_200, "+", "repE", "replication initiation protein", "replicon"),
           (12_400, 13_277, "+", "blaCTX-M-15", "class A beta-lactamase", "amr"),
           (22_000, 23_600, "-", "traI", "conjugative relaxase", "conjugation"),
           (38_000, 38_900, "+", "parA", "plasmid partitioning protein", "partition"),
           (52_000, 53_100, "-", "tnpA", "IS3 family transposase", "transposase"),
           (66_000, 66_700, "+", "orf_pA_1", "hypothetical protein", "unknown"),
           (26_000, 27_100, "+", "intI1", "class 1 integrase", "integrase"),
           (30_000, 31_400, "+", "mobA", "relaxase MobA", "mob"),
           (59_400, 60_600, "-", "traB", "conjugal transfer protein", "conjugation"),
           (33_000, 33_900, "-", "traA", "conjugal transfer pilin subunit", "conjugation"),
           (45_100, 45_910, "-", "sul1", "dihydropteroate synthase", "amr"),
           (70_000, 71_400, "-", "pcoA", "copper resistance multicopper oxidase", "metal_resistance"),
           (74_000, 74_500, "+", "silE", "silver-binding periplasmic protein", "metal_resistance"),
           (80_000, 81_300, "+", "merA", "mercuric reductase", "metal_resistance"),
           # Wraps the origin of the 90,000 bp circular plasmid: start > end, so it
           # runs 89,400 -> 90,000 -> 0 -> 700 (1,300 bp). The projection builder
           # drops such rows from the explorer payload; the circular maps keep them.
           (89_400, 700, "+", "repA2", "replication initiation protein", "replicon")],
    "pB": [(500, 1_400, "+", "mobA", "relaxase MobA", "mob"),
           (3_000, 3_800, "-", "orf_pB_1", "hypothetical protein", "unknown")],
    "pC": [(1_200, 2_300, "+", "repZ", "replication protein", "replicon"),
           (8_200, 9_013, "+", "blaKPC-2", "class A carbapenemase", "amr"),
           (30_000, 31_500, "-", "traJ", "conjugal transfer protein", "conjugation"),
           (20_000, 21_050, "+", "mobA", "relaxase MobA", "mob"),
           (40_000, 41_300, "-", "aac(6')-Ib", "aminoglycoside N-acetyltransferase", "amr"),
           (45_000, 46_000, "+", "cusA", "copper/silver efflux RND transporter", "metal_resistance"),
           (50_000, 50_900, "+", "arsB", "arsenite efflux pump", "metal_resistance"),
           (55_000, 55_900, "-", "intI1", "class 1 integrase", "integrase")],
    "pE": [(2_000, 3_150, "+", "repA", "replication initiation protein", "replicon"),
           (61_000, 61_813, "+", "blaNDM-1", "metallo-beta-lactamase", "amr"),
           (85_000, 86_400, "-", "virB4", "type IV secretion ATPase", "conjugation"),
           (120_000, 121_150, "+", "tnpA", "IS26 transposase", "transposase"),
           (140_000, 140_950, "+", "parB", "partition protein B", "partition"),
           (30_000, 31_500, "+", "traA", "conjugal transfer pilin subunit", "conjugation"),
           (95_000, 95_800, "+", "tetA", "tetracycline efflux pump", "amr"),
           (100_500, 101_500, "-", "mobA", "relaxase MobA", "mob"),
           (110_000, 110_900, "-", "merP", "mercuric transport protein", "metal_resistance"),
           (125_000, 126_000, "+", "intI1", "class 1 integrase", "integrase"),
           # Genes sitting on the block edges of the demo methods (see project_proteins).
           (36_800, 38_000, "-", "orf_pE_2", "hypothetical protein", "unknown"),
           (49_500, 50_800, "+", "stbB", "plasmid stability protein", "partition"),
           (74_000, 76_000, "+", "orf_pE_1", "hypothetical protein", "unknown"),
           (82_000, 83_200, "-", "trbB", "conjugal transfer protein", "conjugation")],
    "pI": [(1_000, 2_050, "+", "repC", "replication initiation protein", "replicon"),
           (3_100, 3_726, "+", "tetA", "tetracycline efflux pump", "amr"),
           (9_000, 10_050, "-", "mobC", "mobilization protein C", "mob"),
           (14_000, 15_100, "+", "higA", "antitoxin HigA", "toxin_antitoxin"),
           (20_000, 21_100, "-", "tnpA", "IS903 transposase", "transposase"),
           (23_000, 23_800, "+", "orf_pI_1", "hypothetical protein", "unknown"),
           (5_000, 5_900, "-", "aac(3)-IIa", "aminoglycoside N-acetyltransferase", "amr")],
    "pJ": [(200, 1_100, "+", "repB", "replication protein B", "replicon"),
           (2_400, 3_300, "-", "orf_pJ_1", "hypothetical protein", "unknown"),
           (4_500, 5_400, "+", "pemK", "toxin PemK", "toxin_antitoxin")],
}

# One repeat-rich plasmid: four copies of one 3 kb element. The truth QC stage
# computes repeat content from reference.fna, so the repeat is in the sequence, not
# only declared here; four copies is 12 kb of 150 kb (8%), over the 5% threshold.
REPEAT_REGIONS = {"pE": [(20_000, 23_000), (55_000, 58_000), (95_000, 98_000), (120_000, 123_000)]}

TOOLS = ["mob_like", "platon_like", "spades_like", "gplas_like", "weak_like"]
# Only declared binners get bin membership, matching tool_capabilities.tsv.
BINNERS = {"mob_like", "gplas_like"}
# One method fails on one sample: failure must not be scored as a zero.
FAILS = {("abauma_b", "weak_like")}


# A fixed 4-base cycle stepped by a position-dependent stride: deterministic,
# reproducible, and clearly synthetic. Not a biological sequence.
def dna(length, seed=0):
    bases = "ACGT"
    return "".join(bases[(index * 7 + seed * 13 + index // 11) % 4] for index in range(length))


@functools.lru_cache(maxsize=None)
def reference_sequence(sample, plasmid, length):
    """Deterministic pseudo-random plasmid sequence with a drifting GC content.

    Random rather than the cyclic dna(): a cyclic sequence is all repeats (every
    plasmid would be repeat-rich) and has flat GC. GC steps between 3 kb blocks so
    the GC and skew rings show structure. Plasmids in REPEAT_REGIONS carry the
    same random element at each listed region. Not a biological sequence.
    """
    rng = random.Random(f"{sample}/{plasmid}")
    out = []
    for block in range((length + 2_999) // 3_000):
        gc = 0.36 + 0.24 * ((block * 37 + len(plasmid)) % 7) / 6
        for _ in range(min(3_000, length - block * 3_000)):
            r = rng.random()
            out.append(("G" if r < gc / 2 else "C") if r < gc else ("A" if r < gc + (1 - gc) / 2 else "T"))
    regions = REPEAT_REGIONS.get(plasmid, [])
    if regions and length >= max(e for _, e in regions):
        element = [rng.choice("ACGT") for _ in range(max(e - s for s, e in regions))]
        for start, end in regions:
            out[start:end] = element[:end - start]
    return "".join(out)


def zoom_segment(sample, plasmids):
    """Reference window the short per-method record is edited from."""
    target, tlen, _ = plasmids[-1]
    return reference_sequence(sample, target, tlen)[:min(1_200, tlen)]


def project_proteins(sample, tool, rows, plasmids):
    """Predicted CDS in the method's own record coordinates, as an annotation caller would emit.

    Each truth CDS is carried through every alignment block that overlaps it, so a gene
    cut by a block edge is only partly covered there and its projection_fraction falls
    below 1. PROTEINS places genes across the block edges the methods produce (the halves
    of spades_like, the thirds of gplas_like, the gap of platon_like, the quarter of
    weak_like), so the methods differ and straddle the 0.9 annotation-concordance cut.
    """
    genes = []
    for pname, _, _ in plasmids:
        genes += [(pname, g) for g in PROTEINS.get(pname, []) if g[0] < g[1]]
    out = []
    for pname, (start, end, strand, gene, product, category) in genes:
        length = end - start
        for row in rows:
            record, qlen, qs, qe, bstrand, target, _, ts, te = row[:9]
            if target != pname or min(end, te) <= max(start, ts):
                continue
            if bstrand == "+":
                q0 = qs + (start - ts)
                flip = strand
            else:
                q0 = qs + (te - end)
                flip = "-" if strand == "+" else "+"
            if q0 < 0:
                continue
            q1 = q0 + length
            out.append([record, q0, q1, flip, f"{tool}_{record}_{q0}", gene, product, category,
                        f"{tool}_annotator", "0.0-synthetic", "synthetic"])
    return out


def edited(segment, seed):
    """Apply a fixed edit pattern, returning the query and its CIGAR.

    One substitution every 97 bases and a single 3-base deletion, so the
    drilldown shows genuine mismatch and gap columns rather than a clean run.
    """
    bases = "ACGT"
    out, cigar, run = [], [], 0
    cut = len(segment) // 2
    for index, base in enumerate(segment):
        if index in (cut, cut + 1, cut + 2):
            if run:
                cigar.append(f"{run}M"); run = 0
            continue                      # deleted from the query
        if index and index % 97 == 0:
            # Offset by 1..3 so the base always changes: +4 would be a no-op.
            out.append(bases[(bases.index(base) + 1 + seed % 3) % 4])
        else:
            out.append(base)
        run += 1
        if index == cut - 1:
            cigar.append(f"{run}M"); cigar.append("3D"); run = 0
    if run:
        cigar.append(f"{run}M")
    return "".join(out), "".join(cigar)


def block(record, qlen, qstart, qend, strand, target, tlen, tstart, tend, identity=1.0,
          mapq=60, cigar=None):
    span = tend - tstart
    row = [record, qlen, qstart, qend, strand, target, tlen, tstart, tend,
           int(span * identity), span, mapq]
    if cigar:
        row.append("cg:Z:" + cigar)
    return row


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
        # Its largest plasmid comes back as one record in two blocks with a gap on
        # the query as well as the reference: the prediction stops, so the uncovered
        # middle is missing reference rather than an adjacency it wrongly asserts.
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
        # Clamp to the reference end: a target span running past the reference
        # length is not a valid PAF row, and it drives completeness above 1.
        fill_start = half + 3_000
        fill_end = min(length, fill_start + length // 2)
        rows.append(block("spa_fill", fill_end - fill_start, 0, fill_end - fill_start, "+",
                          name, length, fill_start, fill_end, identity=0.95))
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

    # Every method also emits one short, CIGAR-bearing record on the smallest
    # plasmid. build_visualization_data only derives a nucleotide alignment for
    # blocks under its bp cap, so without this the drilldown has no sequence.
    target, tlen, _ = plasmids[-1]
    window = min(1_200, tlen)
    seed = TOOLS.index(tool)
    query, cigar = edited(zoom_segment(sample, plasmids), seed)
    rows.append(block(f"{tool.split('_')[0]}_zoom", len(query), 0, len(query), "+",
                      target, tlen, 0, window, identity=0.98, cigar=cigar))
    return rows


def write_assembly(sdir, sample, chrom_len, plasmids):
    """A synthetic short-read assembly for the contig layer.

    reference.full.fna adds a random chromosome to the plasmid records (the demo's
    reference.fna holds plasmids only, for the nucleotide viewer). The assembly has
    one contig per plasmid, named as mob_like reports them (so that method is scored
    at contig level), two chromosome contigs, and an exact contigs_vs_ref.paf -- a
    stand-in for minimap2, which the demo does not run.
    """
    import random
    rng = random.Random(sum(map(ord, sample)))
    chromosome = "".join(rng.choice("ACGT") for _ in range(chrom_len))
    # Random, not dna(): the viewer's cyclic sequence has too few distinct k-mers
    # for the alignment-free cross-check (it would be LOW_INFORMATION).
    plasmid_seqs = {pname: "".join(rng.choice("ACGT") for _ in range(plen)) for pname, plen, _ in plasmids}
    with (sdir / "reference.full.fna").open("w", encoding="utf-8") as handle:
        handle.write(f">chr_{sample}\n{chromosome}\n")
        for pname, seq in plasmid_seqs.items():
            handle.write(f">{pname}\n{seq}\n")
    half = chrom_len // 2
    contigs = [(f"mob_ctg{i}", pname, 0, plen) for i, (pname, plen, _) in enumerate(plasmids, start=1)]
    contigs += [("chr_contig_1", f"chr_{sample}", 0, half), ("chr_contig_2", f"chr_{sample}", half, chrom_len)]
    with (sdir / "contigs.fasta").open("w", encoding="utf-8") as fasta, \
            (sdir / "contigs_vs_ref.paf").open("w", encoding="utf-8") as paf:
        for name, target, start, end in contigs:
            seq = chromosome[start:end] if target.startswith("chr_") else plasmid_seqs[target][start:end]
            tlen = chrom_len if target.startswith("chr_") else len(plasmid_seqs[target])
            fasta.write(f">{name}\n{seq}\n")
            n = end - start
            paf.write(f"{name}\t{n}\t0\t{n}\t+\t{target}\t{tlen}\t{start}\t{end}\t{n}\t{n}\t60\n")


def write_tsv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(header)
        writer.writerows(rows)


# Versions for the synthetic methods. A real run records these from the
# installed executables; the demo installs nothing, so it declares them under
# ``method_versions``, which the report reads by report label. Without this the
# explorer and dashboard have no version to show and say "not recorded".
METHOD_VERSIONS = {
    "mob_like": "0.0-synthetic",
    "platon_like": "0.0-synthetic",
    "spades_like": "0.0-synthetic",
    "gplas_like": "0.0-synthetic",
    "weak_like": "0.0-synthetic",
}


def write_manifest(root):
    """A run manifest for the demo, labelled as synthetic throughout.

    It carries the same shape a real run writes so the report exercises the
    same code path, but every value states that nothing was installed and
    nothing was executed.
    """
    # The cohort is fabricated, but the software that produced it is not: record
    # the real checkout version, resolved by the same helper stage 6 uses.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))
    from write_manifest import prereg_status, tool_version

    manifest = {
        "schema_version": "1",
        "tool_version": tool_version(),
        "synthetic": True,
        "meaning": ("Fabricated by test/demo_dataset.py. No reconstruction tool was "
                    "installed or executed, and no sequence here is biological."),
        "method_versions": dict(METHOD_VERSIONS),
        # No executable was probed, so nothing is reported as available.
        "tools": {name: {"available": False} for name in
                  ("mob_recon", "platon", "plasmidspades.py", "gplas", "minimap2")},
        "samples": [{"sample_id": sample, "organism": organism, "study": study,
                     "depth": depth, "technology": technology, "country": country}
                    for sample, organism, study, depth, technology, country in SAMPLES],
        "settings": {"source": "test/demo_dataset.py"},
        # The real pre-registration state of this checkout (config/prereg.tsv).
        "preregistration": prereg_status(Path(__file__).resolve().parent.parent),
    }
    path = Path(root) / "run_manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


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

        # Reference FASTA: the nucleotide view aligns the predicted record
        # against this, so without it the drilldown has nothing to compare to.
        with (sdir / "reference.fna").open("w", encoding="utf-8") as handle:
            for pname, plen, _ in plasmids:
                handle.write(f">{pname}\n")
                sequence = reference_sequence(sample, pname, plen)
                for start in range(0, plen, 60):
                    handle.write(sequence[start:start + 60] + "\n")

        write_assembly(sdir, sample, chrom_len, plasmids)

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

        # Coding sequences in the normalized protein schema the visualization
        # builder reads, so the explorer's protein track and category filters
        # have real spans to work on.
        proteins = [[name, start, end, strand, f"{name}_{start}", gene, product, category,
                     "demo_annotator", "0.0-synthetic", "synthetic"]
                    for name, _, _ in plasmids
                    for start, end, strand, gene, product, category in PROTEINS.get(name, [])]
        if proteins:
            write_tsv(sdir / "truth_proteins.tsv",
                      ["sequence_id", "start", "end", "strand", "feature_id", "gene", "product",
                       "category", "source", "version", "confidence"], proteins)

        regions = [[name, start, end, f"repeat_{i}"] for name, _, _ in plasmids
                   for i, (start, end) in enumerate(REPEAT_REGIONS.get(name, []), start=1)]
        if regions:
            write_tsv(sdir / "truth_repeat_regions.tsv", ["sequence_id", "start", "end", "label"], regions)

        for index, tool in enumerate(TOOLS):
            failed = (sample, tool) in FAILS
            if failed:
                status.append([sample, tool, "failed", "", "synthetic failure for demonstration", "", ""])
                continue
            rows = predictions(sample, tool, chrom_len, plasmids)
            paf = sdir / f"{tool}.pred_vs_ref.paf"
            with paf.open("w", encoding="utf-8") as handle:
                for row in rows:
                    tags = [f"NM:i:{int(row[10]) - int(row[9])}", f"cg:Z:{int(row[10])}M"]
                    handle.write("\t".join(str(x) for x in list(row) + tags) + "\n")
            write_tsv(sdir / f"{tool}.proteins.tsv",
                      ["sequence_id", "start", "end", "strand", "feature_id", "gene", "product",
                       "category", "source", "version", "confidence"],
                      project_proteins(sample, tool, rows, plasmids))
            # Prediction FASTA: one record per aligned query, padded to length.
            lengths = {}
            for row in rows:
                lengths.setdefault(row[0], row[1])
            # Records are written at their declared length: the scorer checks the
            # PAF query length against the FASTA and rejects any disagreement.
            zoom_record = f"{tool.split('_')[0]}_zoom"
            zoom_target, zoom_tlen, _ = plasmids[-1]
            with (sdir / f"pred_{tool}.plasmid.fasta").open("w", encoding="utf-8") as handle:
                for record, qlen in lengths.items():
                    # The short record carries real edited sequence so its CIGAR
                    # reconstructs against the reference; the rest is padding.
                    if record == zoom_record:
                        sequence = edited(zoom_segment(sample, plasmids), TOOLS.index(tool))[0]
                    else:
                        sequence = "A" * qlen
                    handle.write(f">{record}\n")
                    for start in range(0, len(sequence), 60):
                        handle.write(sequence[start:start + 60] + "\n")
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
    write_manifest(root)
    print(f"Wrote synthetic cohort: {len(SAMPLES)} samples x {len(TOOLS)} methods "
          f"({sum(len(v[1]) for v in TRUTH.values())} truth plasmids) under {root}")


if __name__ == "__main__":
    main()
