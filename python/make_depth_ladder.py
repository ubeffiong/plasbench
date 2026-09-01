#!/usr/bin/env python3
"""Create deterministic paired-read depth-ladder inputs for PlasBench."""

import argparse
import csv
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--depths", default="20,40,80,160", help="Comma-separated target depths in x.")
    parser.add_argument("--seed", type=int, default=20260901)
    parser.add_argument("--seqtk", default="seqtk")
    args = parser.parse_args()
    depths = [float(value) for value in args.depths.split(",") if value.strip()]
    if not depths or any(value <= 0 for value in depths) or len(set(depths)) != len(depths):
        raise SystemExit("ERROR: --depths must contain unique positive numeric values")
    if shutil.which(args.seqtk) is None:
        raise SystemExit(f"ERROR: seqtk executable not found: {args.seqtk}")
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
        run = row.get("sra_run", "")
        if not sample or not run:
            raise SystemExit("ERROR: every source row needs sample_id and sra_run")
        source = Path(args.data_dir) / sample
        depth_file = source / "observed_depth.tsv"
        if not depth_file.is_file():
            raise SystemExit(f"ERROR: {sample} has no observed_depth.tsv; run stage 2 first")
        source_depth = float(rows(depth_file)[0]["observed_depth_x"])
        declared = float(row["read_depth_x"]) if row.get("read_depth_x") else source_depth
        if abs(declared - source_depth) / source_depth > 0.20:
            raise SystemExit(f"ERROR: {sample}: declared read_depth_x={declared:g} disagrees with observed depth {source_depth:g}x by more than 20%")
        required = [source / "reference.fna",
                    source / f"{run}_1.fastq.gz", source / f"{run}_2.fastq.gz"]
        missing = [str(path) for path in required if not path.is_file() or not path.stat().st_size]
        # Stage 1 accepts either an NCBI sequence report or a user-supplied
        # truth table, so the ladder must accept the same pair of inputs.
        truth_sources = [path for path in (source / "truth.tsv", source / "sequence_report.jsonl")
                         if path.is_file() and path.stat().st_size]
        if not truth_sources:
            missing.append(f"{source / 'truth.tsv'} or {source / 'sequence_report.jsonl'}")
        if missing:
            raise SystemExit(f"ERROR: {sample} is missing local inputs: {', '.join(missing)}")
        for depth in depths:
            if depth > source_depth:
                raise SystemExit(f"ERROR: {sample}: target {depth:g}x exceeds declared source depth {source_depth:g}x")
            fraction = depth / source_depth
            label = f"{depth:g}x"
            derived_id = f"{sample}__{label}"
            destination = data_root / derived_id
            if destination.exists() and any(destination.iterdir()):
                raise SystemExit(f"ERROR: refusing to overwrite existing derived input: {destination}")
            destination.mkdir(parents=True, exist_ok=True)
            # observed_depth.tsv is deliberately not copied: stage 2 recomputes it
            # from the subsampled reads, and the parent's value would be wrong.
            for source_file in [source / "reference.fna", *truth_sources]:
                link_or_copy(source_file, destination / source_file.name)
            for mate in (1, 2):
                source_reads = source / f"{run}_{mate}.fastq.gz"
                target_reads = destination / source_reads.name
                # seqtk writes decompressed FASTQ to stdout even for a gzip
                # input. Pipe it through gzip: passing a GzipFile directly to
                # subprocess would expose its raw file descriptor and bypass
                # compression for large streamed outputs.
                with target_reads.open("wb") as handle:
                    seqtk = subprocess.Popen(
                        [args.seqtk, "sample", "-s", str(args.seed), str(source_reads), f"{fraction:.12g}"],
                        stdout=subprocess.PIPE,
                    )
                    gzip_result = subprocess.run(["gzip", "-c"], stdin=seqtk.stdout, stdout=handle, check=False)
                    seqtk.stdout.close()
                    seqtk_result = seqtk.wait()
                if seqtk_result or gzip_result.returncode:
                    target_reads.unlink(missing_ok=True)
                    raise SystemExit(f"ERROR: subsampling failed for {sample} mate {mate} at {label}")
            derived = dict(row)
            derived["sample_id"] = derived_id
            derived["read_depth_x"] = f"{depth:g}"
            # Aggregation reads this to detect correlated subsamples wherever the
            # sheet is copied to, rather than relying on a sibling manifest file.
            derived["parent_sample_id"] = sample
            derived_rows.append(derived)
            manifest.append({"sample_id": derived_id, "parent_sample_id": sample,
                             "target_depth_x": depth, "source_depth_x": source_depth,
                             "fraction": fraction, "seed": args.seed})
    headers = list(dict.fromkeys([*source_rows[0], "parent_sample_id"]))
    with open(output / "depth_ladder.samples.tsv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, delimiter="\t")
        writer.writeheader(); writer.writerows(derived_rows)
    with open(output / "depth_ladder.manifest.tsv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(manifest[0]), delimiter="\t")
        writer.writeheader(); writer.writerows(manifest)
    print(f"Wrote {len(derived_rows)} depth-ladder samples under {output}")


if __name__ == "__main__":
    main()
