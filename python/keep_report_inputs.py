#!/usr/bin/env python3
"""
keep_report_inputs.py -- keep the small per-sample inputs the report needs inside the results folder.

A results folder can only rebuild its report on another machine when it holds what the report reads. The truth tables live in the data
folder, so a results folder that is copied alone loses them (the plasmid maps lose their feature and AMR tracks, the replicon table its
features). At the end of stage 5, when KEEP_REPORT_INPUTS=1 (the default), this copies into <results>/<sample>/:

  truth.tsv truth_features.tsv truth_amr.tsv truth_circular.tsv truth_proteins.tsv truth_repeat_content.tsv truth_repeat_regions.tsv
      small text tables, copied when they exist in the data folder (a file the data folder does not have is not invented)
  <tool>.prediction_summary.tsv
      one row per predicted record (sequence_id, length_bp, sha256), written from pred_<tool>.plasmid.fasta; it lets a later rebuild
      check that predictions supplied from elsewhere are the ones that were scored, without keeping the sequences
  report_inputs.json
      what was kept, the size of each file and its hash, what was left out and why

Not kept: reads, assemblies, reference FASTAs, alignments (the pipeline already keeps the PAF files and visualization/alignment_blocks.json).
Those are sequence data, which the managed .gitignore of a study folder leaves out of git on purpose.

The budget is KEEP_REPORT_INPUTS_MAX_KB per sample (default 2048): files are added in the order above until the next would exceed it; what did not
fit is listed under "skipped" in report_inputs.json. Existing files are replaced when the data folder's copy differs, unless --no-overwrite.

  python3 python/keep_report_inputs.py --data-dir D --results-dir R --sample S [--max-kb 2048] [--no-overwrite] [--dry-run]

Standard library only (plasbench_common for the FASTA reader).
"""
import argparse
import hashlib
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from plasbench_common import iter_fasta  # noqa: E402

KEEP_FILES = ("truth.tsv", "truth_features.tsv", "truth_amr.tsv", "truth_circular.tsv", "truth_proteins.tsv",
              "truth_repeat_content.tsv", "truth_repeat_regions.tsv")
DEFAULT_MAX_KB = 2048
SCHEMA_VERSION = "1"


def enabled(environ=None):
    """KEEP_REPORT_INPUTS (default 1)."""
    return str((environ if environ is not None else os.environ).get("KEEP_REPORT_INPUTS", "1")).strip() not in ("0", "false", "no", "off", "")


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def summary_rows(fasta_path):
    """[(sequence_id, length_bp, sha256 of the upper-cased sequence)] of a prediction FASTA, in file order."""
    rows = []
    for name, _header, sequence in iter_fasta(fasta_path):
        rows.append((name, len(sequence), hashlib.sha256(sequence.upper().encode("ascii", "replace")).hexdigest()))
    return rows


def write_summary(fasta_path, out_path):
    rows = summary_rows(fasta_path)
    text = "sequence_id\tlength_bp\tsha256\n" + "".join(f"{n}\t{l}\t{h}\n" for n, l, h in rows)
    with open(out_path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    return len(rows)


def read_summary(path):
    """{sequence_id: (length_bp, sha256)} of a prediction summary, or None when it is absent or unreadable."""
    try:
        with open(path, encoding="utf-8", newline="") as handle:
            lines = handle.read().splitlines()
        return {f[0]: (int(f[1]), f[2]) for f in (line.split("\t") for line in lines[1:]) if len(f) >= 3}
    except (OSError, ValueError):
        return None


def keep(data_dir, results_dir, sample, max_kb=DEFAULT_MAX_KB, overwrite=True, dry_run=False):
    """Copy the small inputs and write the prediction summaries. Returns the manifest dict (also written unless dry_run)."""
    rdir = os.path.join(results_dir, sample)
    ddir = os.path.join(data_dir, sample) if data_dir else None
    same = bool(ddir) and os.path.abspath(ddir) == os.path.abspath(rdir)
    budget = int(max_kb) * 1024
    kept, skipped, used = [], [], 0
    if not dry_run:
        os.makedirs(rdir, exist_ok=True)
    for name in KEEP_FILES:
        dest = os.path.join(rdir, name)
        src = os.path.join(ddir, name) if ddir else None
        if src and os.path.isfile(src) and not same:
            size = os.path.getsize(src)
            if os.path.isfile(dest) and not overwrite and sha256_file(dest) != sha256_file(src):
                skipped.append({"file": name, "reason": "the results folder already has a different copy and --no-overwrite was given"})
                used += os.path.getsize(dest)
                continue
            if used + size > budget:
                skipped.append({"file": name, "reason": f"{size} bytes would exceed the {max_kb} KB budget (KEEP_REPORT_INPUTS_MAX_KB)"})
                continue
            if not dry_run:
                shutil.copyfile(src, dest)
            used += size
            kept.append({"file": name, "bytes": size, "sha256": sha256_file(src), "source": "data folder"})
        elif os.path.isfile(dest):
            used += os.path.getsize(dest)
            kept.append({"file": name, "bytes": os.path.getsize(dest), "sha256": sha256_file(dest), "source": "already in the results folder"})
    summaries = []
    if os.path.isdir(rdir):
        for entry in sorted(os.listdir(rdir)):
            if entry.startswith("pred_") and entry.endswith(".plasmid.fasta"):
                tool = entry[len("pred_"):-len(".plasmid.fasta")]
                dest = os.path.join(rdir, f"{tool}.prediction_summary.tsv")
                if not dry_run:
                    count = write_summary(os.path.join(rdir, entry), dest)
                    size = os.path.getsize(dest)
                else:
                    count, size = len(summary_rows(os.path.join(rdir, entry))), 0
                summaries.append({"file": f"{tool}.prediction_summary.tsv", "records": count, "bytes": size})
                used += size
    manifest = {"schema_version": SCHEMA_VERSION, "sample": sample, "budget_kb": int(max_kb), "total_bytes": used, "kept": kept,
                "prediction_summaries": summaries, "skipped": skipped,
                "not_kept": "reads, assemblies, reference FASTAs (sequence data); alignments are kept by stage 5 itself"}
    if not dry_run:
        with open(os.path.join(rdir, "report_inputs.json"), "w", encoding="utf-8", newline="") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True)
            handle.write("\n")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--sample", required=True)
    parser.add_argument("--max-kb", type=int, default=int(os.environ.get("KEEP_REPORT_INPUTS_MAX_KB") or DEFAULT_MAX_KB))
    parser.add_argument("--no-overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    manifest = keep(args.data_dir, args.results_dir, args.sample, args.max_kb, not args.no_overwrite, args.dry_run)
    print(f"{args.sample}: kept {len(manifest['kept'])} input file(s), {len(manifest['prediction_summaries'])} prediction summary(ies), "
          f"{manifest['total_bytes']} bytes of {args.max_kb} KB; skipped {len(manifest['skipped'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
