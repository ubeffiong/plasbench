#!/usr/bin/env python3
"""The files that publish PlasBench to other platforms stay valid and stay in step with the release:

  bio.tools      docs/publishing/biotools.json: the required fields, EDAM terms of the right shape, links and downloads of the right types, the version of this release,
                 and (when PLASBENCH_BIOTOOLS_SCHEMA names the official biotoolsj.json) validation against the official JSON schema
  Bioconda       recipes/bioconda/meta.yaml: a real SHA-256 of a release archive (no placeholder), the release-asset URL, the pipeline's tools in the run requirements
  WorkflowHub    workflows/cwl/*.cwl: every step's file exists, container images are pinned (never :latest) and the PlasBench image is this release's;
                 python/make_workflow_crate.py builds a crate that passes its own checks (Workflow RO-Crate profile)
  Container      the Dockerfile tells the per-step entry points where the pipeline is (PLASBENCH_HOME), so Galaxy and CWL can call them from any directory
  Galaxy         the wrappers' version token is this release
Standard library only.
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OK = True


def check(label, good, detail=""):
    global OK
    print(f"  {label}: {'PASS' if good else 'FAIL'}" + ("" if good else f"  [{detail}]"))
    OK = OK and bool(good)


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


VERSION = re.search(r'^version\s*=\s*"([^"]+)"', read("pyproject.toml"), re.M).group(1)

# ---- bio.tools ----------------------------------------------------------------------------------------------------------------------------------------------------
tool = json.loads(read("docs", "publishing", "biotools.json"))
check("bio.tools: the required fields are there (name, description, homepage) and the description is 10 to 1000 characters",
      all(tool.get(k) for k in ("name", "description", "homepage")) and 10 <= len(tool["description"]) <= 1000, len(tool.get("description", "")))
check("bio.tools: biotoolsID matches the identifier the Bioconda recipe declares", tool.get("biotoolsID") == "plasbench" and "biotools:plasbench" in read("recipes", "bioconda", "meta.yaml"))
check("bio.tools: the version is this release", tool.get("version") == [VERSION], tool.get("version"))
check("bio.tools: every download of a versioned file names this release (in its address, or for the container in its note)",
      all(VERSION in d["url"] for d in tool["download"] if d["type"] in ("Software package", "Source code"))
      and all(("v" + VERSION) in d.get("note", "") for d in tool["download"] if d["type"] == "Container file"), tool["download"])
topics = tool.get("topic", [])
ops = [op for f in tool.get("function", []) for op in f["operation"]]
check("bio.tools: topics and operations are EDAM terms of the right shape, each with a label",
      topics and ops and all(re.fullmatch(r"http://edamontology\.org/topic_\d{4}", t["uri"]) and t["term"] for t in topics)
      and all(re.fullmatch(r"http://edamontology\.org/operation_\d{4}", o["uri"]) and o["term"] for o in ops))
check("bio.tools: a licence the bio.tools list has, an open cost and access, and a repository link",
      tool.get("license") == "GPL-3.0" and tool.get("cost") == "Free of charge" and tool.get("accessibility") == "Open access" and any("Repository" in link["type"] for link in tool["link"]))
check("bio.tools: no e-mail address and no placeholder text in the entry", "@" not in json.dumps(tool) and not re.search(r"REPLACE|TODO|YOUR_", json.dumps(tool)))
schema_path = os.environ.get("PLASBENCH_BIOTOOLS_SCHEMA", "")
if schema_path and os.path.isfile(schema_path):
    try:
        import jsonschema
        errors = list(jsonschema.Draft4Validator(json.load(open(schema_path, encoding="utf-8"))).iter_errors([tool]))
        check("bio.tools: valid against the official biotoolsj.json schema", not errors, [e.message[:120] for e in errors[:3]])
    except ImportError:
        print("  n/a   bio.tools: official schema check needs the jsonschema package")
else:
    print("  n/a   bio.tools: official schema check (set PLASBENCH_BIOTOOLS_SCHEMA to the biotoolsj.json path; the schema is CC-BY-SA, so it is not copied here)")

# ---- Bioconda -----------------------------------------------------------------------------------------------------------------------------------------------------
recipe = read("recipes", "bioconda", "meta.yaml")
sha = re.search(r"^\s*sha256:\s*(\S+)", recipe, re.M).group(1)
check("Bioconda: the source checksum is a real SHA-256, not a placeholder", re.fullmatch(r"[0-9a-f]{64}", sha) is not None, sha)
check("Bioconda: the source is the release archive with its published checksum", "releases/download/v{{ version }}/plasbench-{{ version }}.tar.gz" in recipe)
check("Bioconda: the pipeline's own tools are run requirements (minimap2, unzip, bash, python)", all(re.search(r"^\s*-\s*" + name, recipe, re.M) for name in ("minimap2", "unzip", "bash", "python")))
check("Bioconda: the old template is gone, so the recipe has one source of truth", not os.path.exists(os.path.join(ROOT, "recipes", "bioconda", "meta.yaml.template")))

# ---- WorkflowHub (CWL) --------------------------------------------------------------------------------------------------------------------------------------------
cwl_dir = os.path.join(ROOT, "workflows", "cwl")
cwl = {n: read("workflows", "cwl", n) for n in os.listdir(cwl_dir) if n.endswith(".cwl")}
check("CWL: the workflow and its four tools are there", {"plasbench-score.cwl", "align.cwl", "score.cwl", "concat_scores.cwl", "aggregate.cwl"} <= set(cwl), sorted(cwl))
runs = re.findall(r"^\s+run:\s*(\S+)", cwl["plasbench-score.cwl"], re.M)
check("CWL: every step's file exists", runs and all(r in cwl for r in runs), runs)
images = re.findall(r"dockerPull:\s*(\S+)", "\n".join(cwl.values()))
check("CWL: every container image is pinned to a tag or digest, never :latest or untagged", images and all(":" in i and not i.endswith(":latest") for i in images), images)
check("CWL: the PlasBench image is this release", all(i.endswith(":v" + VERSION) for i in images if "plasbench" in i), images)
check("CWL: the job file points at files that exist",
      all(os.path.exists(os.path.join(cwl_dir, p)) for p in re.findall(r"path:\s*(\S+)", read("workflows", "cwl", "plasbench-score.job.yml"))))
done = subprocess.run([sys.executable, os.path.join(ROOT, "python", "make_workflow_crate.py"), "--check"], capture_output=True, text=True)
check("WorkflowHub: the Workflow RO-Crate builds and passes its own checks (profile, main workflow, files, version)", done.returncode == 0, done.stdout + done.stderr)

# ---- container and Galaxy -----------------------------------------------------------------------------------------------------------------------------------------
check("Container: the Dockerfile sets PLASBENCH_HOME so the entry points find the pipeline from any directory", re.search(r"^ENV PLASBENCH_HOME=/opt/plasbench\s*$", read("Dockerfile"), re.M) is not None)
check("Galaxy: the wrappers' version token is this release", re.search(r'name="@TOOL_VERSION@">' + re.escape(VERSION) + "<", read("galaxy", "macros.xml")) is not None)
print("ALL PUBLISHING TESTS PASSED" if OK else "PUBLISHING TESTS FAILED")
sys.exit(0 if OK else 1)
