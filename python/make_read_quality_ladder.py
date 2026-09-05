#!/usr/bin/env python3
"""Create deterministic long-read read-quality-ladder inputs for PlasBench.

Analogous to make_depth_ladder.py, but for the long-read/hybrid track's
sensitivity to read length and quality (e.g. R9 vs R10 chemistry) rather than
depth. Uses filtlong to apply absolute length/quality thresholds -- a
deterministic filter, not a random subsample, so unlike the depth ladder there
is no --seed: the same rung on the same input always produces the same
output.
"""

import argparse
import csv
import gzip
import shutil
import subprocess
from pathlib import Path


def rows(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader((line for line in handle if line.strip() and not line.startswith("#")), delimiter="\t"))


def link_or_copy(source, destination):
    try:
        destination.symlink_to(source.resolve())
    except OSError:
        shutil.copy2(source, destination)


def parse_rungs(value):
    rungs = []
    for chunk in value.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            min_length_str, min_mean_q_str = chunk.split(":")
            min_length, min_mean_q = int(min_length_str), float(min_mean_q_str)
        except ValueError:
            raise SystemExit(f"ERROR: --rungs entries must be MIN_LENGTH:MIN_MEAN_Q, got {chunk!r}")
        if min_length <= 0 or min_mean_q < 0:
            raise SystemExit(f"ERROR: --rungs entry {chunk!r} must have a positive length and non-negative quality")
        rungs.append((min_length, min_mean_q))
    if not rungs:
        raise SystemExit("ERROR: --rungs must contain at least one MIN_LENGTH:MIN_MEAN_Q entry")
    if len(set(rungs)) != len(rungs):
        raise SystemExit("ERROR: --rungs entries must be unique")
    return rungs


def retained_read_count(path):
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
        return sum(1 for _ in handle) // 4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--rungs", default="1000:8,5000:10,20000:15",
                        help="Comma-separated MIN_LENGTH:MIN_MEAN_Q pairs, strictest last is not required.")
    parser.add_argument("--long-reads-file", default="long_reads.fastq.gz",
                        help="Long-read filename within each sample directory (default: long_reads.fastq.gz, "
                             "matching config/config.sh's LONG_READS_FILE default).")
    parser.add_argument("--min-retained-reads", type=int, default=1,
                        help="Fail a rung if fewer than this many reads survive filtering (default: 1).")
    parser.add_argument("--filtlong", default="filtlong")
    args = parser.parse_args()
    rungs = parse_rungs(args.rungs)
    if shutil.which(args.filtlong) is None:
        raise SystemExit(f"ERROR: filtlong executable not found: {args.filtlong}")
    if shutil.which("gzip") is None:
        raise SystemExit("ERROR: gzip executable not found; it is required to write valid .fastq.gz outputs")
    source_rows = rows(args.samples)
    if not source_rows:
        raise SystemExit("ERROR: source sample sheet has no rows")
    output = Path(args.out_dir)
    data_root = output / "data"
    output.mkdir(parents=True, exist_ok=True)
    manifest = []
    derived_rows = []
    for row in source_rows:
        sample = row.get("sample_id", "")
        if not sample:
            raise SystemExit("ERROR: every source row needs sample_id")
        source = Path(args.data_dir) / sample
        long_reads = source / args.long_reads_file
        required = [source / "reference.fna", long_reads]
        missing = [str(path) for path in required if not path.is_file() or not path.stat().st_size]
        truth_sources = [path for path in (source / "truth.tsv", source / "sequence_report.jsonl")
                         if path.is_file() and path.stat().st_size]
        if not truth_sources:
            missing.append(f"{source / 'truth.tsv'} or {source / 'sequence_report.jsonl'}")
        if missing:
            raise SystemExit(f"ERROR: {sample} is missing local inputs: {', '.join(missing)}")
        for min_length, min_mean_q in rungs:
            label = f"len{min_length}_q{min_mean_q:g}"
            derived_id = f"{sample}__{label}"
            destination = data_root / derived_id
            if destination.exists() and any(destination.iterdir()):
                raise SystemExit(f"ERROR: refusing to overwrite existing derived input: {destination}")
            destination.mkdir(parents=True, exist_ok=True)
            for source_file in [source / "reference.fna", *truth_sources]:
                link_or_copy(source_file, destination / source_file.name)
            target_reads = destination / args.long_reads_file
            with target_reads.open("wb") as handle:
                filtlong = subprocess.Popen(
                    [args.filtlong, "--min_length", str(min_length), "--min_mean_q", str(min_mean_q), str(long_reads)],
                    stdout=subprocess.PIPE,
                )
                gzip_result = subprocess.run(["gzip", "-c"], stdin=filtlong.stdout, stdout=handle, check=False)
                filtlong.stdout.close()
                filtlong_result = filtlong.wait()
            if filtlong_result or gzip_result.returncode:
                target_reads.unlink(missing_ok=True)
                raise SystemExit(f"ERROR: filtering failed for {sample} at {label}")
            retained = retained_read_count(target_reads)
            if retained < args.min_retained_reads:
                raise SystemExit(
                    f"ERROR: {sample} at {label} retained only {retained} read(s) "
                    f"(minimum {args.min_retained_reads}); this rung is too strict for this sample's data"
                )
            derived = dict(row)
            derived["sample_id"] = derived_id
            # Aggregation reads this to detect correlated derived samples
            # wherever the sheet is copied to, rather than relying on a
            # sibling manifest file -- same mechanism make_depth_ladder.py uses.
            derived["parent_sample_id"] = sample
            derived_rows.append(derived)
            manifest.append({"sample_id": derived_id, "parent_sample_id": sample,
                             "rung_label": label, "min_length": min_length, "min_mean_q": min_mean_q,
                             "retained_reads": retained})
    headers = list(dict.fromkeys([*source_rows[0], "parent_sample_id"]))
    with open(output / "read_quality_ladder.samples.tsv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, delimiter="\t")
        writer.writeheader(); writer.writerows(derived_rows)
    with open(output / "read_quality_ladder.manifest.tsv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(manifest[0]), delimiter="\t")
        writer.writeheader(); writer.writerows(manifest)
    print(f"Wrote {len(derived_rows)} read-quality-ladder samples under {output}")


if __name__ == "__main__":
    main()
