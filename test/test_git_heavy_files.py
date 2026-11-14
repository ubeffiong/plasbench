#!/usr/bin/env python3
"""Heavy files never go into git (plasbench/gitops.py), in a real repository.

- a study (runs) repository: reads, BAM/SAM/CRAM and their indexes, variants, nanopore signal, aligner indexes and
  databases, archives and sequences are ignored; tables, reports, logs, figures and study.json are tracked
- the developer (program) rules ignore the same heavy formats, except sequences (the program has small fixtures)
- a force-added heavy file is blocked by the commit check
- an older managed block is brought up to date, and the user's own lines outside it are kept
- heavy files committed before a rule existed are found and can be untracked (they stay on disk)
"""

import fnmatch
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


HEAVY_FILES = ["S1.bam", "S1.bam.bai", "S1.sam", "S1.cram", "S1.cram.crai", "calls.vcf.gz", "calls.vcf", "calls.bcf",
               "reads_1.fastq.gz", "reads.fq.bz2", "run.fast5", "run.pod5", "SRR1.sra", "ref.mmi", "idx.1.bt2", "ref.fa.bwt",
               "k2/hash.k2d", "sketch.msh", "db.dmnd", "blast/db.nhr", "model.h5", "db.sqlite", "download.tar.gz",
               "bundle.zip", "contigs.fasta", "assembly_graph.gfa", "aln.paf", "genes.gff3", "cov.bw", "S1.BAM"]
KEEP_FILES = ["study.json", "results/benchmark.leaderboard.tsv", "results/benchmark.report.html", "results/report.pdf",
              "results/fig.png", "results/fig.svg", "results/scores.json", "results/table.tsv.gz", "logs/run.log",
              "notes.md", "results/regions.bed"]


def main():
    from plasbench import gitops
    if not gitops.find_git():
        print("  skip  git is not installed")
        return 0
    tmp = Path(tempfile.mkdtemp())

    print("rules")
    for name, block, pats, skip in (("study", gitops.RUNS_IGNORE, gitops.RUN_DATA_PATTERNS, ()),
                                    ("program", gitops.SAFE_IGNORE, gitops.DATA_PATTERNS, ("contigs.fasta", "genes.gff3"))):
        globs = [l for l in block.splitlines() if l and not l.startswith("#")]
        ign = [f for f in HEAVY_FILES if f not in skip and not any(fnmatch.fnmatch(Path(f).name.lower(), g.lower()) for g in globs)]
        blk = [f for f in HEAVY_FILES if f not in skip and not any(p.search(f) for p, _ in pats)]
        check(f"{name} rules ignore every heavy format", not ign, ign)
        check(f"{name} commit check blocks every heavy format", not blk, blk)
    runs_globs = [l for l in gitops.RUNS_IGNORE.splitlines() if l and not l.startswith("#")]
    wrong = [f for f in KEEP_FILES if any(fnmatch.fnmatch(Path(f).name.lower(), g.lower()) for g in runs_globs)]
    check("results, reports, logs, figures and study.json are not ignored", not wrong, wrong)

    print("a study repository")
    study = tmp / "ws" / "cohort1"
    study.mkdir(parents=True)
    gitops.init(study, "main", False, kind="runs")
    gitops.run(study, "config", "user.name", "T")
    gitops.run(study, "config", "user.email", "t@example.org")
    for f in HEAVY_FILES + KEEP_FILES:
        p = study / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x\n")
    gitops.stage(study, None)
    staged = set(gitops.run(study, "diff", "--cached", "--name-only").stdout.split())
    check("staging everything takes the run's files", set(KEEP_FILES) | {".gitignore"} <= staged, set(KEEP_FILES) - staged)
    leaked = sorted(f for f in HEAVY_FILES if f in staged)
    check("and none of the heavy files", not leaked, leaked)
    check("the commit check passes", not gitops.scan_staged(study), gitops.scan_staged(study))
    gitops.run(study, "add", "-f", "S1.bam")
    found = gitops.scan_staged(study)
    check("a force-added BAM blocks the commit", any(f["path"] == "S1.bam" and f["level"] == "block" for f in found), found)
    try:
        gitops.commit(study, "first run")
        check("the blocked commit is refused", False)
    except Exception as exc:        # noqa: BLE001 - GitError or ValueError, both refuse
        check("the blocked commit is refused", "S1.bam" in str(exc) or "block" in str(exc).lower(), exc)

    print("already tracked")
    gitops.run(study, "commit", "-q", "-m", "an old commit that let a BAM in")   # as if made before the rule
    heavy = gitops.heavy_tracked(study)
    check("a heavy file committed earlier is found", [h["path"] for h in heavy] == ["S1.bam"], heavy)
    gitops.untrack(study, ["S1.bam"])
    check("untracking keeps it on disk and out of the index", (study / "S1.bam").exists()
          and "S1.bam" not in gitops.run(study, "ls-files").stdout.split())

    print("an older repository gets the new rules")
    old = tmp / "ws" / "cohort0"
    old.mkdir(parents=True)
    gitops.run(old, "init", "-q")
    (old / ".gitignore").write_text("# mine\nscratch/\n\n# --- PlasBench runs block (managed) ---\ntmp/\n*.bam\n"
                                    "# --- end PlasBench runs block ---\n\n# also mine\n*.local\n", encoding="utf-8")
    changed = gitops.refresh_gitignore(old)
    text = (old / ".gitignore").read_text(encoding="utf-8")
    check("the managed block is updated", changed and "*.vcf.gz" in text and "*.pod5" in text and "*.sam" in text)
    check("the user's own lines are kept", text.startswith("# mine\nscratch/\n") and text.rstrip().endswith("*.local"))
    check("and the block appears once", text.count("PlasBench runs block (managed)") == 1)
    check("a second refresh changes nothing", gitops.refresh_gitignore(old) is False)
    plain = tmp / "plain"
    plain.mkdir()
    (plain / ".gitignore").write_text("*.log\n", encoding="utf-8")
    check("a .gitignore PlasBench did not make is left alone", gitops.refresh_gitignore(plain) is False
          and (plain / ".gitignore").read_text(encoding="utf-8") == "*.log\n")

    print("editing .gitignore")
    ed = tmp / "ws" / "cohort2"
    ed.mkdir(parents=True)
    gitops.init(ed, "main", False, kind="runs")
    parts = gitops.gitignore_parts(ed)
    check("the editor shows PlasBench's block and no user rules yet", "PlasBench runs block" in parts["managed"] and parts["user"] == "")
    mine = "scratch/\n!results/keep.fasta\n!results/S1.bam\n"
    gitops.save_gitignore(ed, mine)
    text = (ed / ".gitignore").read_text(encoding="utf-8")
    check("the user's rules are saved after the block, which is unchanged", text.startswith(gitops.RUNS_IGNORE)
          and text.endswith(mine))
    check("Test a path: the deciding rule", gitops.check_ignore(ed, "results/S1.bam")["pattern"] == "!results/S1.bam"
          and gitops.check_ignore(ed, "results/x.bam")["ignored"] and gitops.check_ignore(ed, "scratch/a")["pattern"] == "scratch/"
          and gitops.check_ignore(ed, "results/t.tsv")["ignored"] is False)
    (ed / "results").mkdir()
    for n in ("keep.fasta", "S1.bam", "other.fasta"):
        (ed / "results" / n).write_bytes(b"x\n")
    gitops.stage(ed, None)
    levels = {f["path"]: f["level"] for f in gitops.scan_staged(ed)}
    check("a FASTA you keep with your own rule is a warning", levels.get("results/keep.fasta") == "warn", levels)
    check("a BAM stays blocked whatever the rules say", levels.get("results/S1.bam") == "block", levels)
    check("other FASTA files stay out", "results/other.fasta" not in gitops.run(ed, "diff", "--cached", "--name-only").stdout)
    gitops.refresh_gitignore(ed)
    check("refreshing the block keeps the user's rules", (ed / ".gitignore").read_text(encoding="utf-8").endswith("!results/S1.bam\n"))
    for bad in ("../x", ""):
        try:
            gitops.check_ignore(ed, bad)
            check(f"Test a path refuses {bad!r}", False)
        except ValueError:
            check(f"Test a path refuses {bad!r}", True)
    page = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
    check("the Version control page has the editor", all(x in page for x in ('id="gi_user"', 'id="gi_block"', 'id="gi_test"', '"gitignore_save"')))

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{'FAILED: ' + ', '.join(FAILED) if FAILED else 'all heavy-file checks passed'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
