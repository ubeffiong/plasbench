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
    if not source_rows or any(not row.get("read_depth_x") for row in source_rows):
        raise SystemExit("ERROR: every source row needs read_depth_x for deterministic depth fractions")
    output = Path(args.out_dir)
    data_root = output / "data"
    output.mkdir(parents=True, exist_ok=True)
    manifest = []
    derived_rows = []
    for row in source_rows:
        source_depth = float(row["read_depth_x"])
        sample = row.get("sample_id", "")
        run = row.get("sra_run", "")
        if not sample or not run:
            raise SystemExit("ERROR: every source row needs sample_id and sra_run")
        source = Path(args.data_dir) / sample
        required = [source / "reference.fna", source / "sequence_report.jsonl",
                    source / f"{run}_1.fastq.gz", source / f"{run}_2.fastq.gz"]
        missing = [str(path) for path in required if not path.is_file() or not path.stat().st_size]
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
            for source_file in required[:2]:
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
            derived_rows.append(derived)
            manifest.append({"sample_id": derived_id, "parent_sample_id": sample,
                             "target_depth_x": depth, "source_depth_x": source_depth,
                             "fraction": fraction, "seed": args.seed})
    headers = list(source_rows[0])
    with open(output / "depth_ladder.samples.tsv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, delimiter="\t")
        writer.writeheader(); writer.writerows(derived_rows)
    with open(output / "depth_ladder.manifest.tsv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(manifest[0]), delimiter="\t")
        writer.writeheader(); writer.writerows(manifest)
    print(f"Wrote {len(derived_rows)} depth-ladder samples under {output}")


if __name__ == "__main__":
    main()
