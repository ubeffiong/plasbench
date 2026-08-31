#!/usr/bin/env python3
"""Write a portable, machine-readable provenance manifest for a PlasBench run."""

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


TOOLS = ("datasets", "prefetch", "fasterq-dump", "fastp", "spades.py", "unicycler",
         "mob_recon", "platon", "plasmidspades.py", "gplas", "minimap2", "python3")


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def command_version(name):
    executable = shutil.which(name)
    if not executable:
        return {"available": False}
    for flag in ("--version", "-V", "version"):
        try:
            result = subprocess.run([executable, flag], text=True, capture_output=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            continue
        output = (result.stdout or result.stderr).strip().splitlines()
        if output:
            return {"available": True, "path": executable, "version": output[0]}
    return {"available": True, "path": executable, "version": "unreported"}


def sample_rows(path):
    rows, header = [], None
    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            fields = raw.rstrip("\n").split("\t")
            if header is None:
                header = fields
            else:
                rows.append(dict(zip(header, fields)))
    return rows


def directory_identity(path):
    """Identify a database without hashing multi-gigabyte contents on every run."""
    if not path:
        return {"available": False, "path": None}
    path = Path(path)
    if not path.is_dir():
        return {"available": False, "path": str(path)}
    files = sorted(item for item in path.rglob("*") if item.is_file())
    digest = hashlib.sha256()
    for item in files:
        stat = item.stat()
        digest.update(f"{item.relative_to(path)}\t{stat.st_size}\t{stat.st_mtime_ns}\n".encode())
    return {"available": True, "path": str(path.resolve()), "file_count": len(files),
            "identity_sha256": digest.hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--sample-sheet", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    settings = ("THREADS", "MEMORY_GB", "ASSEMBLER", "MIN_READ_LEN", "MINIMAP2_PRESET",
                "RUN_MOB_RECON", "RUN_PLATON", "RUN_PLASMIDSPADES", "RUN_GPLAS",
                "PLASMID_RECOVERY_THRESHOLD", "AMR_GENE_RECOVERY_THRESHOLD", "PLATON_DB")
    sample_sheet = Path(args.sample_sheet)
    samples = sample_rows(sample_sheet)
    truth_tables = {}
    for sample in samples:
        truth = Path(args.data_dir) / sample["sample_id"] / "truth.tsv"
        if truth.is_file():
            truth_tables[sample["sample_id"]] = {"sha256": sha256(truth), "bytes": truth.stat().st_size}
    outputs = {}
    for path in Path(args.results_dir).glob("benchmark*"):
        if path.is_file():
            outputs[path.name] = {"sha256": sha256(path), "bytes": path.stat().st_size}
    manifest = {
        "schema_version": "1.0", "tool": "PlasBench", "tool_version": "0.1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_root": str(Path(args.project_root).resolve()),
        "platform": {"python": sys.version, "system": platform.platform()},
        "container": {"image": os.environ.get("CONTAINER_IMAGE"),
                      "image_digest": os.environ.get("CONTAINER_IMAGE_DIGEST")},
        "databases": {"platon": directory_identity(os.environ.get("PLATON_DB", ""))},
        "settings": {key: os.environ.get(key) for key in settings},
        "input_checksums": {"sample_sheet": sha256(sample_sheet), "truth_tables": truth_tables},
        "samples": samples, "tools": {name: command_version(name) for name in TOOLS},
        "outputs": outputs,
    }
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(f"Wrote run manifest: {args.out}")


if __name__ == "__main__":
    main()
