#!/usr/bin/env python3
"""Every python/*.py script is reachable, and the new commands really run.

A script nobody calls is a feature that does not exist for users. This test fails when a
script under python/ is not referenced by a stage script, the CLI, an adapter/installer or
another module, unless it is one of the documented one-off scripts below. It also drives
the `derive-amr-truth` and `audit-truth-labels` commands through the real CLI, and checks
the stage-2 and stage-6 hooks.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Documented one-off / hand-run scripts (each states this in its own docstring or docs).
ONE_OFF = {
    "compare_scoring_methods",     # BLASTN-vs-minimap2 cross-check, "never wired into any stage script"
    "audit_three_class_scoring",   # imported by compare_scoring_methods; METHODS.md documents it
    "parse_teixeira2025_supplement",  # one-time cohort migration, docs/FINDING_DATA.md
}


def text_files(*parts):
    for part in parts:
        base = ROOT / part
        if base.is_file():
            yield base
        elif base.is_dir():
            for path in base.rglob("*"):
                if path.is_file() and path.suffix in {".sh", ".py", ".toml", ".yml", ".cfg"} \
                        and "__pycache__" not in path.parts:
                    yield path


def main():
    corpus = {p: p.read_text(encoding="utf-8", errors="replace")
              for p in text_files("scripts", "adapters", "env", "plasbench", "python", "config",
                                  "install.sh", "update.sh", "pyproject.toml")}
    unwired = []
    for script in sorted((ROOT / "python").glob("*.py")):
        name = script.stem
        if name in ONE_OFF:
            continue
        if not any(name in body for path, body in corpus.items() if path != script):
            unwired.append(name)
    assert not unwired, f"python scripts referenced nowhere: {unwired}"
    print("every python script is wired or a documented one-off -> PASS")

    stage2 = (ROOT / "scripts" / "02_truth.sh").read_text(encoding="utf-8")
    assert "derive_amr_truth.py" in stage2 and "DERIVE_AMR_TRUTH_DRAFT" in stage2
    assert "truth_amr.draft.tsv" in stage2 and '/truth_amr.tsv"' not in stage2.split("derive_amr_truth.py")[1].split("fi\n")[0]
    stage6 = (ROOT / "scripts" / "06_aggregate.sh").read_text(encoding="utf-8")
    for needle in ("audit_truth_labels.py", "--truth-label-audit", "--rank-robustness"):
        assert needle in stage6, needle
    print("stage 2 and stage 6 hooks present, and the draft never targets truth_amr.tsv -> PASS")

    env = {**os.environ, "PYTHONPATH": str(ROOT)}

    def cli(*args):
        return subprocess.run([sys.executable, "-m", "plasbench", "--project-root", str(ROOT), *args],
                              cwd=ROOT, env=env, capture_output=True, text=True)

    with tempfile.TemporaryDirectory() as d:
        sample = Path(d) / "data" / "s1"
        sample.mkdir(parents=True)
        (sample / "truth.tsv").write_text("sequence_id\tmolecule_type\tlength\np1\tPLASMID\t1000\nchr\tCHROMOSOME\t5000\n")
        (sample / "truth_features.tsv").write_text(
            "sequence_id\tstart\tend\tfeature_type\tlabel\tsource\tversion\n"
            "p1\t10\t200\tamr\tblaCTX-M-15\tamrfinderplus\t4.0.3\n")
        draft = sample / "truth_amr.draft.tsv"
        result = cli("derive-amr-truth", "--features", str(sample / "truth_features.tsv"),
                     "--truth", str(sample / "truth.tsv"), "--out", str(draft))
        assert result.returncode == 0, result.stderr
        assert draft.is_file() and "auto_derived" in draft.read_text()
        refused = cli("derive-amr-truth", "--features", str(sample / "truth_features.tsv"),
                      "--truth", str(sample / "truth.tsv"), "--out", str(sample / "truth_amr.tsv"))
        assert refused.returncode != 0 and not (sample / "truth_amr.tsv").exists()
        print("plasbench derive-amr-truth writes a draft and refuses truth_amr.tsv -> PASS")

        audit = Path(d) / "audit.tsv"
        result = cli("audit-truth-labels", "--data-dir", str(Path(d) / "data"), "--out", str(audit))
        assert result.returncode == 0, result.stderr
        assert "not_evaluated" in audit.read_text(), "no provenance file: nothing may be called consistent"
        print("plasbench audit-truth-labels runs and does not over-claim -> PASS")
    print("ALL SCRIPT WIRING TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
