#!/usr/bin/env python3
"""The AI help's knowledge index: it is current with its sources, built the same every time, shipped as package data, and finds the right guide for realistic questions.

The gold set (test/fixtures/ai_gold.tsv) has more than 40 support questions across installing, Docker, WSL, commands, inputs, metrics, the workflow, troubleshooting, exit codes
and error messages quoted from logs, some of them misspelt. A question passes when one of the top three chunks comes from an acceptable source."""
import fnmatch
import gzip
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "python"))
import build_ai_kb  # noqa: E402
from plasbench import ai_kb  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(f"  {'ok  ' if good else 'FAIL'}  {label}{'' if good else ' -> ' + str(detail)[:300]}")
    ok &= bool(good)


print("freshness and determinism")
raw = build_ai_kb.build_raw()
fresh = build_ai_kb.build_bytes(raw)
check("the shipped index has exactly the content the sources give now (run python python/build_ai_kb.py)", build_ai_kb.is_current(raw=raw))
check("building twice gives the same content, and the compressed file is stable on this system", build_ai_kb.build_raw() == raw and build_ai_kb.build_bytes(raw) == fresh)
data = json.loads(gzip.decompress(fresh).decode("utf-8"))
chunks = data["chunks"]
check("an index of several hundred chunks", len(chunks) > 500, len(chunks))
srcs = {c["src"] for c in chunks}
for need in ("README.md", "FAQ.md", "INSTALL.md", "SUPPORT.md", "docs/USER_GUIDE.md", "docs/METHODS.md", "docs/SCIENTIFIC_GUIDE.md", "docs/METAGENOMICS.md", "docs/ADDING_TOOLS.md",
             "docs/RESOURCE_ADAPTATION.md", "docs/TOOL_INSTALL_AUDIT.md", "docs/publishing/README.md", "config/workflow_steps.tsv", "config/tool_capabilities.tsv", "config/config.sh",
             "python/report_help_text.py", "plasbench/ui_help.py", "plasbench/cli.py", "config/resource_signatures.tsv", "python/docker_diagnosis.py", "python/assembler_diagnosis.py", "plasbench/exitcodes.py"):
    check(f"source in the index: {need}", need in srcs)
check("every chunk has id, source, title, text", all({"id", "src", "title", "anchor", "kind", "text"} <= set(c) and c["text"].strip() for c in chunks))
sizes = [len(c["text"].split()) for c in chunks]
check("chunks are mostly 70-350 words (the rest are unsplittable tables or code)", sum(1 for n in sizes if n <= 400) / len(sizes) > 0.97, max(sizes))
cli = " ".join(c["text"] for c in chunks if c["kind"] == "cli")
from plasbench import ui_schema  # noqa: E402
check("every plasbench command of the real parser is in the index", all(f"plasbench {c['name']}" in cli for c in ui_schema.schema()["commands"]))
check("a settings chunk gives key, default and comment", any("MEMORY_GB" in c["text"] and "default" in c["text"] for c in chunks if c["kind"] == "settings"))
check("the workflow has stages 0 to 8", all(any(f"Workflow stage {n}" in c["title"] for c in chunks) for n in range(0, 9)))
check("no secret-looking text in the index", not re.search(r"sk-or-v1-|GOCSPX-|hf_[A-Za-z0-9]{30,}", gzip.decompress(fresh).decode("utf-8")))

print("package data")
pp = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
pats = re.search(r'\[tool\.setuptools\.package-data\]\s*plasbench\s*=\s*\[(.*?)\]', pp, re.S).group(1)
patterns = re.findall(r'"([^"]+)"', pats)
check("pyproject package-data covers data/ai_kb.json.gz", any(fnmatch.fnmatch("data/ai_kb.json.gz", p) for p in patterns), patterns)
check("MANIFEST.in ships plasbench/data *.gz", re.search(r"recursive-include plasbench/data .*\*\.gz", (ROOT / "MANIFEST.in").read_text(encoding="utf-8")))
check("the Dockerfile copies the whole tree (so the index is in the image)", re.search(r"^COPY .*\. /opt/plasbench", (ROOT / "Dockerfile").read_text(encoding="utf-8"), re.M))
check("the conda recipe installs with pip install . (package data included)", "pip install ." in (ROOT / "recipes" / "bioconda" / "build.sh").read_text(encoding="utf-8"))
try:
    import setuptools  # noqa: F401
    import tempfile
    out = tempfile.mkdtemp(prefix="pb_whl_")
    r = subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "-q", "-w", out, str(ROOT)], capture_output=True, text=True, timeout=240)
    if r.returncode == 0:
        import zipfile
        whl = next(Path(out).glob("plasbench-*.whl"))
        check("the built wheel contains plasbench/data/ai_kb.json.gz", "plasbench/data/ai_kb.json.gz" in zipfile.ZipFile(whl).namelist())
    else:
        print("  (wheel build not available here; the pattern checks above stand)", r.stderr[-120:].replace("\n", " "))
except ImportError:
    print("  (setuptools not installed; the pattern checks above stand)")

print("retrieval gold set")
kb = ai_kb.load()
rows = [l.rstrip("\n").split("\t") for l in (ROOT / "test" / "fixtures" / "ai_gold.tsv").read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
check("at least 40 gold questions", len(rows) >= 40, len(rows))
hits, misses = 0, []
for row in rows:
    q, src = row[0], row[1].split("|")
    need = row[2].lower() if len(row) > 2 else ""
    top = kb.search(q, 3)
    good = any(any(a in r["src"] for a in src) and (not need or need in (r["title"] + " " + r["text"]).lower()) for r in top)
    hits += good
    if not good:
        misses.append(q)
rate = hits / len(rows)
print(f"  retrieval hit rate in the top 3: {hits}/{len(rows)} = {rate:.0%}")
check("hit rate is at least 90%", rate >= 0.9, misses)
for q, src in (("You need approx 5.2 GB of free RAM", "config/resource_signatures.tsv|python/assembler_diagnosis.py|docs/USER_GUIDE.md"), ("Could not open lockfile", "python/docker_diagnosis.py|FAQ.md")):
    top = kb.search(q, 3)
    check(f"error string: {q}", any(any(a in r["src"] for a in src.split("|")) for r in top))
check("a misspelt word finds the right guide ('instal-tools', 'gziped')", any("install" in r["text"].lower() for r in kb.search("instal-tools failed", 3)) and any("gzip" in r["text"].lower() for r in kb.search("my reads are not gziped", 3)))
check("synonym: 'frozen' finds the stuck-run section", any("stuck" in (r["title"] + r["text"]).lower() or "stalled" in r["text"].lower() for r in kb.search("my run is frozen", 3)))
res = kb.search("how do I stop plasbench", 5)
check("results are deduplicated: at most two chunks per section", max(__import__("collections").Counter((r["src"], r["anchor"]) for r in res).values()) <= 2)
check("an unrelated question still returns a list without failing", isinstance(kb.search("zxqv wlmn", 3), list))
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
