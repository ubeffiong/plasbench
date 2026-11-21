#!/usr/bin/env python3
"""Build the Workflow RO-Crate that WorkflowHub registers: dist/plasbench-score.crate.zip.

  python3 python/make_workflow_crate.py            writes dist/plasbench-score.crate.zip
  python3 python/make_workflow_crate.py --check    builds into a temporary folder and verifies it (exit 1 on a problem)

The crate holds the CWL workflow (workflows/cwl/plasbench-score.cwl) and its four tool descriptions, a job file that runs the synthetic isolate shipped with the Galaxy
wrappers (test-data/), the licence and a README, described in ro-crate-metadata.json following the Workflow RO-Crate profile
(https://w3id.org/workflowhub/workflow-ro-crate/1.0): the main workflow is the entity named by `mainEntity`, typed File, SoftwareSourceCode and ComputationalWorkflow, with
CWL as its programming language. The version comes from pyproject.toml, so a release cannot ship a crate that names another version. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CWL = ROOT / "workflows" / "cwl"
TOOL_FILES = ("align.cwl", "score.cwl", "concat_scores.cwl", "aggregate.cwl")
MAIN = "plasbench-score.cwl"
# crate path -> source file: the synthetic isolate of the Galaxy wrappers (a 3,000 bp plasmid and a 4,000 bp chromosome, and a prediction that is the plasmid)
TEST_DATA = {"reference.fasta": ROOT / "galaxy" / "test-data" / "reference.fasta", "prediction.fasta": ROOT / "galaxy" / "test-data" / "align_prediction.fasta",
             "truth.tsv": CWL / "test-data" / "truth.tsv"}
CWL_LANGUAGE = "https://w3id.org/workflowhub/workflow-ro-crate#cwl"
PROFILE = "https://w3id.org/workflowhub/workflow-ro-crate/1.0"


def project_version() -> str:
    match = re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M)
    if not match:
        raise SystemExit("could not read the version from pyproject.toml")
    return match.group(1)


def release_date() -> str:
    match = re.search(r'^date-released:\s*"([^"]+)"', (ROOT / "CITATION.cff").read_text(encoding="utf-8"), re.M)
    return match.group(1) if match else ""


def metadata(version: str, date: str) -> dict:
    files = [MAIN, *TOOL_FILES, "plasbench-score.job.yml", *["test-data/" + n for n in TEST_DATA], "LICENSE", "README.md"]
    graph = [
        {"@id": "ro-crate-metadata.json", "@type": "CreativeWork", "about": {"@id": "./"},
         "conformsTo": [{"@id": "https://w3id.org/ro/crate/1.1"}, {"@id": PROFILE}]},
        {"@id": "./", "@type": "Dataset", "name": "PlasBench: align, score and aggregate predicted plasmids",
         "description": "Scores the predicted-plasmid FASTA of one or more plasmid-reconstruction tools for one isolate against its complete reference (base-level precision, recall and F1, "
                        "plasmid-level recovery and structural measures) and ranks the tools. The PlasBench Galaxy tools as a CWL workflow: minimap2 alignment, scoring, aggregation. "
                        "The stages that download isolates, assemble reads or run the reconstruction tools are not part of it.",
         "version": version, "datePublished": date, "license": {"@id": "https://spdx.org/licenses/GPL-3.0-only"},
         "author": {"@id": "https://github.com/ubeffiong"}, "creator": {"@id": "https://github.com/ubeffiong"},
         "url": "https://github.com/ubeffiong/plasbench", "isBasedOn": {"@id": "https://github.com/ubeffiong/plasbench"},
         "keywords": ["plasmid", "benchmarking", "genomics", "antimicrobial resistance", "CWL"],
         "mainEntity": {"@id": MAIN}, "hasPart": [{"@id": f} for f in files]},
        {"@id": MAIN, "@type": ["File", "SoftwareSourceCode", "ComputationalWorkflow"], "name": "PlasBench - align, score and aggregate predicted plasmids",
         "programmingLanguage": {"@id": CWL_LANGUAGE}, "version": version, "license": {"@id": "https://spdx.org/licenses/GPL-3.0-only"},
         "input": [{"@id": "#reference"}, {"@id": "#truth"}, {"@id": "#predictions"}, {"@id": "#tool_names"}],
         "output": [{"@id": "#scores"}, {"@id": "#leaderboard"}]},
        {"@id": "#reference", "@type": "FormalParameter", "name": "reference", "additionalType": {"@id": "http://edamontology.org/data_0925"},
         "encodingFormat": "http://edamontology.org/format_1929", "description": "Complete reference assembly (FASTA) used as ground truth."},
        {"@id": "#truth", "@type": "FormalParameter", "name": "truth", "additionalType": {"@id": "http://edamontology.org/data_0006"},
         "encodingFormat": "http://edamontology.org/format_3475", "description": "Truth labels of the reference sequences (TSV)."},
        {"@id": "#predictions", "@type": "FormalParameter", "name": "predictions", "additionalType": {"@id": "http://edamontology.org/data_0925"},
         "encodingFormat": "http://edamontology.org/format_1929", "description": "One predicted-plasmid FASTA per tool."},
        {"@id": "#tool_names", "@type": "FormalParameter", "name": "tool_names", "additionalType": "Text", "description": "The tool that produced each prediction, in the same order."},
        {"@id": "#scores", "@type": "FormalParameter", "name": "scores", "additionalType": {"@id": "http://edamontology.org/data_0006"},
         "encodingFormat": "http://edamontology.org/format_3475", "description": "Per-sample, per-tool scores."},
        {"@id": "#leaderboard", "@type": "FormalParameter", "name": "leaderboard", "additionalType": {"@id": "http://edamontology.org/data_0006"},
         "encodingFormat": "http://edamontology.org/format_3475", "description": "Ranked tool leaderboard."},
        {"@id": CWL_LANGUAGE, "@type": "ComputerLanguage", "name": "Common Workflow Language", "alternateName": "CWL",
         "identifier": {"@id": "https://w3id.org/cwl/v1.2/"}, "url": {"@id": "https://www.commonwl.org/"},
         "version": "v1.2"},
        {"@id": "https://github.com/ubeffiong", "@type": "Person", "name": "Ubokobong Effiong", "url": "https://github.com/ubeffiong"},
        {"@id": "https://spdx.org/licenses/GPL-3.0-only", "@type": "CreativeWork", "name": "GNU General Public License v3.0 only", "identifier": "GPL-3.0-only"},
        {"@id": "https://github.com/ubeffiong/plasbench", "@type": "SoftwareSourceCode", "name": "PlasBench", "version": version},
    ]
    for name in TOOL_FILES:
        graph.append({"@id": name, "@type": ["File", "SoftwareSourceCode"], "name": name[:-4].replace("_", " "), "programmingLanguage": {"@id": CWL_LANGUAGE}})
    graph.append({"@id": "plasbench-score.job.yml", "@type": "File", "name": "Test job: the synthetic isolate", "encodingFormat": "text/yaml"})
    for name in TEST_DATA:
        graph.append({"@id": "test-data/" + name, "@type": "File", "name": name})
    graph.append({"@id": "LICENSE", "@type": "File", "name": "Licence (GPL-3.0-only)"})
    graph.append({"@id": "README.md", "@type": "File", "name": "README", "encodingFormat": "text/markdown"})
    return {"@context": "https://w3id.org/ro/crate/1.1/context", "@graph": graph}


JOB = """# Test job: the synthetic isolate shipped with the PlasBench Galaxy wrappers. Run with:
#   cwltool plasbench-score.cwl plasbench-score.job.yml
reference:
  class: File
  path: test-data/reference.fasta
truth:
  class: File
  path: test-data/truth.tsv
predictions:
  - class: File
    path: test-data/prediction.fasta
tool_names: [demo_perfect]
sample: synthetic
"""

README = """# PlasBench - align, score and aggregate predicted plasmids (CWL)

Scores the predicted-plasmid FASTA of one or more plasmid-reconstruction tools for one isolate against its complete reference and ranks the tools. This is the PlasBench
Galaxy tool chain (align, score, aggregate) as a CWL workflow.

    cwltool plasbench-score.cwl plasbench-score.job.yml

Without Docker, `plasbench` (conda or the GitHub release archive) and `minimap2` must be on PATH, and cwltool is run with `--no-container`. The stages that download
isolates, assemble reads or run the reconstruction tools themselves are not part of this workflow: use `plasbench run`.

Source, documentation and licence (GPL-3.0-only): https://github.com/ubeffiong/plasbench
"""


def build(out: Path) -> Path:
    version = project_version()
    stage = Path(tempfile.mkdtemp(prefix="plasbench-crate-"))
    try:
        for name in (MAIN, *TOOL_FILES):
            shutil.copyfile(CWL / name, stage / name)
        (stage / "test-data").mkdir()
        for name in TEST_DATA:
            shutil.copyfile(TEST_DATA[name], stage / "test-data" / name)
        shutil.copyfile(ROOT / "LICENSE", stage / "LICENSE")
        (stage / "plasbench-score.job.yml").write_text(JOB, encoding="utf-8", newline="\n")
        (stage / "README.md").write_text(README, encoding="utf-8", newline="\n")
        (stage / "ro-crate-metadata.json").write_text(json.dumps(metadata(version, release_date()), indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():
            out.unlink()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    info = zipfile.ZipInfo(path.relative_to(stage).as_posix(), date_time=(2026, 1, 1, 0, 0, 0))   # fixed time: the same crate every build
                    info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(info, path.read_bytes())
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return out


def verify(crate: Path) -> list[str]:
    """Problems with a built crate (empty = fine)."""
    problems = []
    with zipfile.ZipFile(crate) as archive:
        names = set(archive.namelist())
        if "ro-crate-metadata.json" not in names:
            return ["ro-crate-metadata.json is missing"]
        doc = json.loads(archive.read("ro-crate-metadata.json").decode("utf-8"))
    graph = {entity["@id"]: entity for entity in doc["@graph"]}
    root = graph.get("./", {})
    descriptor = graph.get("ro-crate-metadata.json", {})
    conforms = [c.get("@id") for c in (descriptor.get("conformsTo") or [])]
    if PROFILE not in conforms:
        problems.append("the descriptor does not declare the Workflow RO-Crate profile")
    main = graph.get((root.get("mainEntity") or {}).get("@id", ""), {})
    if not {"File", "SoftwareSourceCode", "ComputationalWorkflow"} <= set(main.get("@type") or []):
        problems.append("mainEntity is not typed File, SoftwareSourceCode and ComputationalWorkflow")
    if (main.get("programmingLanguage") or {}).get("@id") != CWL_LANGUAGE or CWL_LANGUAGE not in graph:
        problems.append("the main workflow does not name CWL as its programming language with a matching ComputerLanguage entity")
    for part in root.get("hasPart", []):
        if part["@id"] not in names:
            problems.append("hasPart names a file that is not in the crate: " + part["@id"])
        if part["@id"] not in graph:
            problems.append("hasPart names a file with no entity: " + part["@id"])
    for field in ("name", "description", "license", "author", "datePublished", "version"):
        if not root.get(field):
            problems.append("the root dataset has no " + field)
    if root.get("version") != project_version():
        problems.append("the crate says version %s but pyproject.toml says %s" % (root.get("version"), project_version()))
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / "plasbench-score.crate.zip")
    parser.add_argument("--check", action="store_true", help="build into a temporary folder and verify; exit 1 on a problem")
    args = parser.parse_args(argv)
    if args.check:
        tmp = Path(tempfile.mkdtemp(prefix="plasbench-crate-check-"))
        try:
            crate = build(tmp / "plasbench-score.crate.zip")
            problems = verify(crate)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        for line in problems:
            print("PROBLEM:", line, file=sys.stderr)
        return 1 if problems else 0
    crate = build(args.out)
    problems = verify(crate)
    for line in problems:
        print("PROBLEM:", line, file=sys.stderr)
    print("wrote", crate)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
