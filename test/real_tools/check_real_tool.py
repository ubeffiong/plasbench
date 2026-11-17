#!/usr/bin/env python3
"""Run one REAL tool binary on a known input and check what comes out (plan E1; used by .github/workflows/real-tools.yml).

The ordinary tests use stand-in tools, so they cannot notice that a tool's real output format, contig naming or database handling has changed. This
runs the real binary exactly as stage 4 does, passes its output through the real adapter, and checks the result:

  tool          the tool exited 0 (a non-zero exit is a failure, with the tail of its log)
  adapter       the adapter exited 0 and wrote the files adapters/REGISTRY.md promises (pred_<tool>.plasmid.fasta and, for a binning tool, the bins table)
  naming        for a tool whose output is a subset of the input assembly (MOB-suite, Platon): EVERY predicted record id, and every bin member, is a contig id of the
                INPUT (a tool that rewrites contig names breaks scoring silently). A re-assembler (plasmidSPAdes) writes contigs of its own, so this does not apply
  bins          every adapter writes a bins table with the header `bin_id<TAB>sequence_id`, no sequence in two rows, no empty bin
  database      a tool that needs a database reports a clear problem when it is missing, before it runs (never an obscure crash)
  known output  the share of the input called plasmid is compared with test/real_tools/expected.tsv; a floor of 0 means "not yet set": any share above zero passes, a share of zero fails

The input is a plasmid (the fixture is fetched by the workflow), so a tool that calls none of it plasmid is reported, and judged only against the floor in
expected.tsv. The floors start at 0 because no real run had been reviewed when this was written: set each from the first reviewed scheduled run.

One TSV row per run (tool, versions, database, exit codes, problems, plasmid share, status) goes to --summary, for the workflow to upload.
"""
import argparse
import csv
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = Path(__file__).with_name("expected.tsv")
SUMMARY_FIELDS = ["tool", "version", "database", "tool_exit", "adapter_exit", "seconds", "plasmid_share", "expected_min_share", "problems", "status"]
SUBSET_OF_INPUT = {"mob_recon", "platon"}   # their predictions are contigs of the input assembly; a re-assembler's are not
NEEDS_DATABASE = {"platon": "PLATON_DB"}


def fasta_records(path):
    """[(id, length)] in file order; the id is the first word of the header."""
    out, name, length = [], None, 0
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.startswith(">"):
                if name is not None:
                    out.append((name, length))
                name, length = (line[1:].split() or [""])[0], 0
            elif name is not None:
                length += len(line.strip())
    if name is not None:
        out.append((name, length))
    return out


def read_bins(path):
    with open(path, newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle, delimiter="\t"))
    return rows[0] if rows else [], rows[1:]


def database_problem(tool, environ=None):
    """None, or the sentence that says why the tool cannot run: a database it needs is not configured or not there."""
    environ = os.environ if environ is None else environ
    variable = NEEDS_DATABASE.get(tool)
    if not variable:
        return None
    path = environ.get(variable, "")
    if not path:
        return f"{tool} needs a database: {variable} is not set"
    if not Path(path).is_dir():
        return f"{tool} needs a database: {variable}={path} is not a directory"
    return None


def validate_output(tool, predicted, bins, input_ids):
    """The list of problems with an adapter's output, empty when it is sound. `predicted` is the FASTA path, `bins` the bins table path or None."""
    problems = []
    if not Path(predicted).is_file():
        return [f"the adapter wrote no {Path(predicted).name}"]
    ids = [name for name, _length in fasta_records(predicted)]
    if len(ids) != len(set(ids)):
        problems.append("a predicted record id appears twice")
    unknown = sorted(set(ids) - set(input_ids))
    if unknown and tool in SUBSET_OF_INPUT:
        problems.append(f"{len(unknown)} predicted record id(s) are not contigs of the input (the tool renames contigs?): {', '.join(unknown[:3])}")
    # every adapter writes a bins table
    if not bins or not Path(bins).is_file():
        problems.append("the adapter wrote no bins table")
        return problems
    header, rows = read_bins(bins)
    if header != ["bin_id", "sequence_id"]:
        problems.append(f"the bins table header is {header}, not ['bin_id', 'sequence_id']")
    members = [r[1] for r in rows if len(r) > 1]
    if len(members) != len(set(members)):
        problems.append("a sequence is in more than one bin row")
    if any(len(r) < 2 or not r[0] or not r[1] for r in rows):
        problems.append("a bins row has an empty bin or sequence id")
    unknown = sorted(set(members) - set(input_ids))
    if unknown and tool in SUBSET_OF_INPUT:
        problems.append(f"{len(unknown)} bin member(s) are not contigs of the input: {', '.join(unknown[:3])}")
    return problems


def plasmid_share(predicted, input_fasta):
    total = sum(length for _name, length in fasta_records(input_fasta))
    called = sum(length for _name, length in fasta_records(predicted)) if Path(predicted).is_file() else 0
    return called / total if total else None


def expected_floor(tool, path=EXPECTED):
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader((line for line in handle if line.strip() and not line.startswith("#")), delimiter="\t"):
            if row["tool"] == tool:
                return float(row["min_plasmid_share"])
    return 0.0


def judge(problems, tool_exit, adapter_exit, share, floor):
    """('pass'|'fail', reasons) from the run: structural problems and exit codes fail; a share under the floor fails; a tool that calls NOTHING as plasmid on an input that is a plasmid fails even where the floor is 0 (a floor of 0 means the value is not yet set, not that zero is acceptable)."""
    reasons = list(problems)
    if tool_exit != 0:
        reasons.append(f"the tool exited {tool_exit}")
    if adapter_exit != 0:
        reasons.append(f"the adapter exited {adapter_exit}")
    if share is not None and share <= 0.0:
        reasons.append("the tool called nothing as plasmid on an input that is a plasmid")
    elif share is not None and share + 1e-12 < floor:
        reasons.append(f"plasmid share {share:.3f} is under the expected {floor:.3f}")
    return ("fail" if reasons else "pass"), reasons


def version_of(command):
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=120)
        return ((done.stdout or done.stderr).strip().splitlines() or ["unknown"])[0][:120]
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"


def run_tool(tool, assembly, workdir, reads=None, threads=2):
    """(command, version command, adapter script, predicted fasta, bins path) for `tool`; the commands are those of scripts/04_run_tools.sh."""
    out = Path(workdir) / tool
    pred = Path(workdir) / f"pred_{tool}.plasmid.fasta"
    if tool == "mob_recon":
        return (["mob_recon", "--infile", str(assembly), "--outdir", str(out), "--num_threads", str(threads), "--force"], ["mob_recon", "--version"],
                "adapt_mob_recon.sh", out, pred, Path(str(pred).replace(".plasmid.fasta", ".bins.tsv")))
    if tool == "platon":
        # --meta: the fixture is a ~4 kb plasmid, too short for Platon's single-genome gene-finder training (it fails with "ORF prediction failed!").
        # Real assemblies are megabases and run without it in scripts/04_run_tools.sh.
        return (["platon", "--db", os.environ.get("PLATON_DB", ""), "--threads", str(threads), "--output", str(out), "--prefix", "fixture", "--meta", str(assembly)],
                ["platon", "--version"], "adapt_platon.sh", out, pred, Path(str(pred).replace(".plasmid.fasta", ".bins.tsv")))
    if tool == "plasmidspades":
        if not reads:
            raise SystemExit("ERROR: plasmidspades needs --reads-1 and --reads-2")
        return (["plasmidspades.py", "-1", reads[0], "-2", reads[1], "-o", str(out), "--threads", str(threads), "--memory", "4"], ["plasmidspades.py", "--version"],
                "adapt_plasmidspades.sh", out, pred, Path(str(pred).replace(".plasmid.fasta", ".bins.tsv")))
    raise SystemExit(f"ERROR: no real-run recipe for {tool}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tool", required=True, choices=("mob_recon", "platon", "plasmidspades"))
    parser.add_argument("--assembly", required=True, help="the input assembly FASTA (the known plasmid)")
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--reads-1")
    parser.add_argument("--reads-2")
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args()
    workdir = Path(args.workdir)
    shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True)
    reads = (args.reads_1, args.reads_2) if args.reads_1 and args.reads_2 else None
    problem = database_problem(args.tool)
    row = {"tool": args.tool, "version": "", "database": os.environ.get(NEEDS_DATABASE.get(args.tool, ""), "") if args.tool in NEEDS_DATABASE else "none required",
           "tool_exit": "", "adapter_exit": "", "seconds": "", "plasmid_share": "", "expected_min_share": "", "problems": "", "status": ""}
    if problem:
        row.update(problems=problem, status="fail")
    else:
        command, version, adapter, out, pred, bins = run_tool(args.tool, args.assembly, workdir, reads)
        row["version"] = version_of(version)
        started = time.time()
        log = workdir / f"{args.tool}.log"
        with open(log, "w", encoding="utf-8") as handle:
            try:
                tool_exit = subprocess.run(command, stdout=handle, stderr=subprocess.STDOUT, timeout=args.timeout).returncode
            except subprocess.TimeoutExpired:
                tool_exit = 124       # the exit code of timeout(1): a summary row is still written, with the reason
        adapter_exit = subprocess.run(["bash", str(ROOT / "adapters" / adapter), str(out), str(args.assembly), str(pred)], capture_output=True, text=True).returncode if tool_exit == 0 else -1
        row.update(tool_exit=tool_exit, adapter_exit=adapter_exit, seconds=f"{time.time() - started:.0f}")
        input_ids = [name for name, _length in fasta_records(args.assembly)]
        problems = validate_output(args.tool, pred, bins, input_ids) if tool_exit == 0 and adapter_exit == 0 else []
        share, floor = plasmid_share(pred, args.assembly), expected_floor(args.tool)
        status, reasons = judge(problems, tool_exit, adapter_exit, share, floor)
        if tool_exit != 0:
            reasons.append("log tail: " + " | ".join(log.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-3:]))
        row.update(plasmid_share="" if share is None else f"{share:.4f}", expected_min_share=f"{floor:.4f}", problems="; ".join(reasons), status=status)
    with open(args.summary, "a+", newline="", encoding="utf-8") as handle:
        handle.seek(0)
        fresh = not handle.read(1)
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS, delimiter="\t", lineterminator="\n")
        if fresh:
            writer.writeheader()
        writer.writerow(row)
    print(f"[{args.tool}] {row['status']}: {row['problems'] or 'no problems'} (plasmid share {row['plasmid_share'] or 'n/a'})")
    sys.exit(0 if row["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
