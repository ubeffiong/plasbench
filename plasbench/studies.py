"""Study folders: every benchmark run keeps everything it produces in its own folder.

    <workspace>/<study>/
        study.json      what the study is: its sample sheet, cohort, and every run started in it
        results/        predictions, scores, leaderboard and the HTML report
        logs/           tool and mapping logs
        tmp/            scratch space

The workspace is `PLASBENCH_WORKSPACE` (environment, or config/local.env, where the window's Workspace page saves it),
else `<PlasBench folder>/studies`. Downloaded reads, references and tool databases are NOT per study: they stay in
the shared data and database folders, so a second study of the same isolates downloads nothing again.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import time
from pathlib import Path

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
SUBDIRS = ("results", "logs", "tmp")


def _local_env(root: Path) -> dict:
    path = Path(os.environ.get("PLASBENCH_LOCAL_SETTINGS", Path(root) / "config" / "local.env"))
    values = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
            if m:
                try:
                    parts = shlex.split(m.group(2))
                except ValueError:
                    continue
                values[m.group(1)] = parts[0] if parts else ""
    return values


def workspace(root) -> Path:
    """The folder that holds every study."""
    configured = os.environ.get("PLASBENCH_WORKSPACE") or _local_env(root).get("PLASBENCH_WORKSPACE")
    return Path(configured).expanduser() if configured else Path(root) / "studies"


def valid_name(name: str) -> str:
    name = (name or "").strip()
    if not NAME_RE.match(name):
        raise ValueError(f"study name {name!r}: use letters, digits, '.', '_' or '-', starting with a letter or digit "
                         "(at most 80 characters)")
    return name


def default_name(cohort=None, samples=None, meta=False) -> str:
    """cohort1 -> cohort1; my_isolates.tsv -> my_isolates; nothing -> accessions (config/accessions.tsv)."""
    base = cohort or (Path(samples).stem if samples else "accessions")
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", str(base)).strip("-.") or "study"
    return valid_name(("meta-" if meta else "") + base[:75])


def _sha256(path: Path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def prepare(root, name: str, samples=None, cohort=None, argv=None) -> Path:
    """Create (or reuse) the study folder and record this run in its study.json. Returns the folder."""
    folder = workspace(root) / valid_name(name)
    for sub in SUBDIRS:
        (folder / sub).mkdir(parents=True, exist_ok=True)
    record_path = folder / "study.json"
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        record = {"name": folder.name, "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "runs": []}
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    record["updated"] = now
    if samples:
        record["sample_sheet"] = str(Path(samples).resolve())
        record["sample_sheet_sha256"] = _sha256(samples)
    if cohort:
        record["cohort"] = cohort
    record.setdefault("runs", []).append({"started": now, "command": "plasbench " + " ".join(argv or [])})
    record["runs"] = record["runs"][-200:]
    record_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return folder


def create(root, name: str, note: str = "") -> Path:
    """An empty study (from the window's New study button): its folders and a study.json, no run yet."""
    folder = workspace(root) / valid_name(name)
    if (folder / "study.json").exists():
        raise ValueError(f"a study named {folder.name} already exists")
    for sub in SUBDIRS:
        (folder / sub).mkdir(parents=True, exist_ok=True)
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    record = {"name": folder.name, "created": now, "updated": now, "note": note, "runs": []}
    (folder / "study.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return folder


def list_studies(root) -> list:
    """Every study in the workspace, newest first, with what the window shows about it."""
    base = workspace(root)
    out = []
    if not base.is_dir():
        return out
    for folder in base.iterdir():
        if not folder.is_dir() or folder.name.startswith("."):
            continue
        try:
            record = json.loads((folder / "study.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            record = {}
        results = folder / "results"
        stamp = max([p.stat().st_mtime for p in (folder / "study.json", results / "benchmark.report.html",
                                                    results / "benchmark.leaderboard.tsv") if p.exists()] or [folder.stat().st_mtime])
        out.append({"name": folder.name, "path": str(folder), "results": str(results), "modified": stamp,
                    "cohort": record.get("cohort"), "sample_sheet": record.get("sample_sheet"),
                    "runs": len(record.get("runs", [])), "report": (results / "benchmark.report.html").is_file(),
                    "created": record.get("created"), "note": record.get("note", ""),
                    "migrated_from": record.get("migrated_from"),
                    "last_command": (record.get("runs") or [{}])[-1].get("command")})
    out.sort(key=lambda s: -s["modified"])
    return out
