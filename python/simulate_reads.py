#!/usr/bin/env python3
"""Simulate short+long reads from a REAL, complete reference assembly, for
the truth_source=simulated cohort track (see docs/COHORTS.md).

Unlike truth_source=self_assembled_hybrid (truth is BUILT from real reads,
never independent of them) or ncbi_deposited (truth AND reads both come from
the same real isolate), a simulated row inverts the relationship: the
reference is a real, independently-deposited Complete Genome assembly (so it
IS the truth, unchanged, exactly like ncbi_deposited -- see
validate_cohort.py's verify_simulated_row()), and the READS are generated
locally from it. This is useful for isolates where the read-generating
process itself is the thing being controlled for (a known depth, a known
error profile, a known seed) rather than inherited from whatever real
sequencing run happened to exist.

Short reads: InSilicoSeq (`iss generate`), one row per reference contig in
its --coverage_file, all set to the SAME requested depth -- a deliberate,
documented simplifying assumption (uniform sequencing depth across
chromosome and plasmid(s) alike), not a per-replicon depth model. Verified
directly from InSilicoSeq's own source (iss/abundance.py's
parse_abundance_file(): a whitespace-delimited "genome_id\tcoverage" file,
matched against each FASTA record's .id) and iss/app.py/iss/util.py (no
flag exists for a single flat numeric depth without a coverage/abundance
file; --compress writes "<prefix>_R1.fastq.gz"/"<prefix>_R2.fastq.gz" as a
gzip post-processing step over the plain FASTQ, not a direct-write branch).

Long reads: Badread (`badread simulate`), piped through gzip (matching
python/make_depth_ladder.py's own Popen-piping convention for external
compressors -- passing a GzipFile's raw fd to subprocess would bypass
compression for a large streamed output). Deliberately OMITS a fixed
--length flag: plassembler_simulation_benchmarking's own Snakemake rule
forces every simulated long read to exactly 10,000 bp (`--length
10000,10000`), which is a real fidelity choice worth flagging, not copying
uncritically -- this script instead lets Badread draw from its own natural
read-length distribution, which is closer to what a real long-read run
looks like.

Both binaries are resolved via shutil.which() before use, not left to
subprocess.run's own bare-name lookup, matching build_hybrid_truth.py's
same Windows-PATHEXT-avoidance convention.

Writes:
  --out-r1 / --out-r2   gzipped paired short reads.
  --out-long            gzipped long reads.
  --out-provenance      simulation_provenance.json: tool versions, exact
                        commands, seed, depths, error models -- read by
                        write_manifest.py exactly like
                        annotation_provenance.json already is.

Usage:
  simulate_reads.py --reference reference.fna \\
      --out-r1 SIMULATED_1.fastq.gz --out-r2 SIMULATED_2.fastq.gz \\
      --out-long long_reads.fastq.gz --out-provenance simulation_provenance.json \\
      --seed 42 --short-depth 60 --long-depth 40 --threads 4
"""

import argparse
import gzip
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def read_fasta_ids(path):
    """Return [(seq_id, length)] preserving file order. seq_id is the first
    whitespace-delimited header token -- the same join key InSilicoSeq's own
    parse_abundance_file() matches a coverage_file's genome_id against
    (record.id, not the full description)."""
    records = []
    seq_id = None
    length = 0
    with open(path) as handle:
        for line in handle:
            if line.startswith(">"):
                if seq_id is not None:
                    records.append((seq_id, length))
                seq_id = line[1:].split()[0]
                length = 0
            else:
                length += len(line.strip())
        if seq_id is not None:
            records.append((seq_id, length))
    return records


def tool_version(path, *version_flags):
    try:
        result = subprocess.run([path, *version_flags], capture_output=True, text=True, timeout=30)
        return (result.stdout or result.stderr).strip()
    except Exception as exc:
        return f"unknown ({exc})"


def simulate_short_reads(iss_path, reference, records, depth, model, seed, threads, work_dir):
    coverage_file = work_dir / "coverage.tsv"
    with open(coverage_file, "w") as handle:
        for seq_id, _ in records:
            handle.write(f"{seq_id}\t{depth:g}\n")
    prefix = work_dir / "iss_out"
    command = [iss_path, "generate", "--genomes", str(reference), "--coverage_file", str(coverage_file),
               "--model", model, "--output", str(prefix), "--compress", "--cpus", str(threads),
               "--seed", str(seed)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(f"[simulate_reads] iss generate failed (exit {result.returncode}):\n{result.stderr[-4000:]}\n")
        return None, command
    r1 = Path(f"{prefix}_R1.fastq.gz")
    r2 = Path(f"{prefix}_R2.fastq.gz")
    if not r1.is_file() or not r2.is_file():
        sys.stderr.write("[simulate_reads] iss generate reported success but did not write both R1/R2 files\n")
        return None, command
    return (r1, r2), command


def simulate_long_reads(badread_path, reference, depth, error_model, qscore_model, seed, out_long):
    command = [badread_path, "simulate", "--reference", str(reference), "--quantity", f"{depth:g}x",
               "--error_model", error_model, "--qscore_model", qscore_model, "--seed", str(seed)]
    with open(out_long, "wb") as handle:
        badread = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        gzip_result = subprocess.run(["gzip", "-c"], stdin=badread.stdout, stdout=handle, check=False)
        badread.stdout.close()
        _, badread_stderr = badread.communicate()
        badread_result = badread.returncode
    if badread_result or gzip_result.returncode:
        Path(out_long).unlink(missing_ok=True)
        sys.stderr.write(f"[simulate_reads] badread simulate failed (exit {badread_result}):\n{(badread_stderr or b'').decode(errors='replace')[-4000:]}\n")
        return False, command
    return True, command


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--out-r1", required=True)
    ap.add_argument("--out-r2", required=True)
    ap.add_argument("--out-long", required=True)
    ap.add_argument("--out-provenance", required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--short-depth", type=float, required=True)
    ap.add_argument("--long-depth", type=float, required=True)
    ap.add_argument("--short-model", default="novaseq")
    ap.add_argument("--long-model", default="nanopore2020")
    ap.add_argument("--threads", type=int, default=4)
    args = ap.parse_args()

    iss_path = shutil.which("iss")
    badread_path = shutil.which("badread")
    if not iss_path:
        sys.stderr.write("[simulate_reads] iss (InSilicoSeq) is not installed (or not on PATH)\n")
        sys.exit(1)
    if not badread_path:
        sys.stderr.write("[simulate_reads] badread is not installed (or not on PATH)\n")
        sys.exit(1)

    records = read_fasta_ids(args.reference)
    if not records:
        sys.stderr.write(f"[simulate_reads] {args.reference} has no records\n")
        sys.exit(1)

    with tempfile.TemporaryDirectory(prefix="simulate_reads_") as tmp:
        work_dir = Path(tmp)
        short_result, iss_command = simulate_short_reads(
            iss_path, args.reference, records, args.short_depth, args.short_model,
            args.seed, args.threads, work_dir,
        )
        if short_result is None:
            sys.exit(1)
        r1, r2 = short_result
        Path(args.out_r1).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out_r2).parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(r1), args.out_r1)
        shutil.move(str(r2), args.out_r2)

        Path(args.out_long).parent.mkdir(parents=True, exist_ok=True)
        long_ok, badread_command = simulate_long_reads(
            badread_path, args.reference, args.long_depth, args.long_model, args.long_model,
            args.seed, args.out_long,
        )
        if not long_ok:
            sys.exit(1)

    provenance = {
        "method": "simulated",
        "seed": args.seed,
        "reference_contigs": [{"sequence_id": seq_id, "length": length} for seq_id, length in records],
        "short_reads": {
            "tool": "insilicoseq", "version": tool_version(iss_path, "--version"),
            "model": args.short_model, "depth_x": args.short_depth,
            "coverage_note": "uniform depth across every reference contig (chromosome and plasmid(s) alike)",
            "command": iss_command,
        },
        "long_reads": {
            "tool": "badread", "version": tool_version(badread_path, "--version"),
            "error_model": args.long_model, "qscore_model": args.long_model, "depth_x": args.long_depth,
            "length_note": "Badread's own natural read-length distribution (no fixed --length), unlike plassembler_simulation_benchmarking's fixed 10000,10000",
            "command": badread_command,
        },
    }
    Path(args.out_provenance).write_text(json.dumps(provenance, indent=2) + "\n")

    sys.stderr.write(
        f"[simulate_reads] wrote {args.out_r1}, {args.out_r2} ({args.short_depth}x, {args.short_model}) "
        f"and {args.out_long} ({args.long_depth}x, {args.long_model})\n"
    )


if __name__ == "__main__":
    main()
