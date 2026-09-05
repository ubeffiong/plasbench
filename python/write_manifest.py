#!/usr/bin/env python3
"""Write a portable, machine-readable provenance manifest for a PlasBench run."""

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


TOOLS = ("datasets", "prefetch", "fasterq-dump", "fastp", "spades.py", "unicycler",
         "mob_recon", "platon", "plasmidspades.py", "gplas", "minimap2", "python3",
         "plassembler", "flye", "hybracter", "trycycler", "genomad", "PLASMe.py",
         "plASgraph2_classify.py")


def tool_version():
    """Report the version of the checkout that actually produced this run.

    Stage 6 invokes this script from the source tree, so the sibling package is
    the code that ran. An installed `plasbench` may be older than the checkout
    (a stale `pip install .`), and recording that version would misattribute the
    results, so the checkout wins and the installed package is only a fallback.
    """
    init = Path(__file__).resolve().parent.parent / "plasbench" / "__init__.py"
    if init.is_file():
        match = re.search(r"""__version__\s*=\s*["']([^"']+)["']""",
                          init.read_text(encoding="utf-8"))
        if match:
            return match.group(1)
    try:
        from plasbench import __version__
        return __version__
    except ImportError:
        return "unknown"


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


def status_rows(results_dir):
    path = Path(results_dir) / "tool_status.tsv"
    if not path.is_file():
        return []
    import csv
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


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
                "RUN_MOB_RECON", "RUN_PLATON", "RUN_PLASMIDSPADES", "RUN_GPLAS2_MOB", "RUN_GPLAS2_EXTERNAL",
                "PLASMID_RECOVERY_THRESHOLD", "AMR_GENE_RECOVERY_THRESHOLD", "PLATON_DB",
                "MIN_ALIGNMENT_LENGTH", "MIN_ALIGNMENT_IDENTITY", "MIN_ALIGNMENT_MAPQ", "MIN_ALIGNMENT_QUERY_COVERAGE",
                "REPORT_MAPPING_AMBIGUITY",
                "RECOMMENDATION_MIN_SAMPLES", "RECOMMENDATION_MIN_COVERAGE", "ANALYSIS_TRACK", "ANALYSIS_TRACK_FILTER",
                # Long-read/hybrid track (previously missing from this allow-list
                # despite being real config knobs -- a reproducibility gap).
                "RUN_FLYE_MOB_RECON", "FLYE_READ_TYPE", "FLYE_MOB_RECON_ALLOW_CIRCULAR_TRUTH",
                "RUN_PLASSEMBLER", "PLASSEMBLER_DB", "PLASSEMBLER_CHROMOSOME_LENGTH", "PLASSEMBLER_ALLOW_CIRCULAR_TRUTH",
                "LONG_READS_FILE",
                "RUN_HYBRACTER_LONG", "RUN_HYBRACTER_HYBRID", "HYBRACTER_CHROMOSOME_LENGTH",
                "HYBRACTER_LONG_ALLOW_CIRCULAR_TRUTH", "HYBRACTER_HYBRID_ALLOW_CIRCULAR_TRUTH",
                "RUN_TRYCYCLER_MOB_RECON", "TRYCYCLER_ASSEMBLY_COUNT", "TRYCYCLER_READ_TYPE",
                "TRYCYCLER_MEDAKA_POLISH", "TRYCYCLER_MOB_RECON_ALLOW_CIRCULAR_TRUTH",
                "RUN_GENOMAD", "GENOMAD_DB", "RUN_PLASME", "PLASME_DB", "PLASME_PROBABILITY",
                "PLASME_VERSION", "PLASME_CHECKOUT_DIR",
                "RUN_PLASGRAPH2", "PLASGRAPH2_MODEL_DIR", "PLASGRAPH2_CPU_ONLY", "PLASGRAPH2_VERSION")
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
    selected_candidates = {}
    for report in Path(args.results_dir).glob("*/selected_candidate/selection_report.json"):
        sample = report.parents[1].name
        selected_candidates[sample] = {
            "selection_report": {"sha256": sha256(report), "bytes": report.stat().st_size},
            "files": sorted(path.name for path in report.parent.iterdir() if path.is_file()),
        }
    manifest = {
        "schema_version": "1.0", "tool": "PlasBench", "tool_version": tool_version(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_root": str(Path(args.project_root).resolve()),
        "platform": {"python": sys.version, "system": platform.platform()},
        "container": {"image": os.environ.get("CONTAINER_IMAGE"),
                      "image_digest": os.environ.get("CONTAINER_IMAGE_DIGEST")},
        "databases": {"platon": directory_identity(os.environ.get("PLATON_DB", "")),
                      "genomad": directory_identity(os.environ.get("GENOMAD_DB", "")),
                      "plasme": directory_identity(os.environ.get("PLASME_DB", ""))},
        # Not downloaded databases -- plASgraph2's pretrained model and
        # PLASMe's code both ship inside their own git checkouts.
        # directory_identity() (filename+size+mtime hash, not content hash)
        # still cheaply identifies which checkout/model produced a run,
        # without re-hashing model weights every time. PLASME_CHECKOUT_DIR is
        # optional -- unlike PLASGRAPH2_MODEL_DIR, nothing else in the
        # pipeline requires the PLASMe checkout's path, so this entry is only
        # ever populated if the user chooses to record it.
        "models": {"plasgraph2": directory_identity(os.environ.get("PLASGRAPH2_MODEL_DIR", "")),
                   "plasme": directory_identity(os.environ.get("PLASME_CHECKOUT_DIR", ""))},
        "settings": {key: os.environ.get(key) for key in settings},
        "input_checksums": {"sample_sheet": sha256(sample_sheet), "truth_tables": truth_tables},
        "samples": samples, "tools": {name: command_version(name) for name in TOOLS},
        "execution_profiles": status_rows(args.results_dir),
        "outputs": outputs, "selected_candidates": selected_candidates,
    }
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(f"Wrote run manifest: {args.out}")


if __name__ == "__main__":
    main()
