"""Study folders: every benchmark run keeps everything it produces in its own folder.

    <workspace>/<study>/
        study.json      what the study is: its sample sheet, cohort, and every run started in it
        results/        predictions, scores, leaderboard and the HTML report
        logs/           tool and mapping logs
        tmp/            scratch space

The workspace is `PLASBENCH_WORKSPACE` (environment, or config/local.env, where the window's Workspace page saves it),
else `<PlasBench folder>/studies`. Downloaded reads, references and tool databases are NOT per study by default: they stay in
the shared data and database folders, so a second study of the same isolates downloads nothing again. A run can instead keep its
downloads inside the study (`run --keep-data-in-study`, <study>/data, git-ignored, deleted with the study) or in another folder
(`run --data-dir`); the choice is recorded in study.json (`data_location`: shared | study | custom, and `data_dir`) and reused by later
runs of the same study.

A study folder can also live OUTSIDE the workspace (`run --study-location PARENT_DIR`, "Add an existing study folder..."): its name and
absolute path are kept in a hidden registry file in the workspace (.external_studies.json, never committed). Every part of PlasBench finds
a study folder through `study_path(root, name)`, so workspace and external studies behave alike; names are unique across both.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import time
from pathlib import Path

from . import loadcache

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
SUBDIRS = ("results", "logs", "tmp")
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


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


REGISTRY = ".external_studies.json"


def _same(a, b) -> bool:
    return os.path.normcase(os.path.realpath(str(a))) == os.path.normcase(os.path.realpath(str(b)))


def registry_path(root) -> Path:
    return workspace(root) / REGISTRY


def registry(root) -> dict:
    """{study name: absolute folder} of the studies kept outside the workspace."""
    try:
        data = json.loads(registry_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    found = data.get("studies") if isinstance(data, dict) else None
    return {str(k): str(v) for k, v in found.items()} if isinstance(found, dict) else {}


def _save_registry(root, entries: dict) -> None:
    path = registry_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"schema_version": 1, "studies": dict(sorted(entries.items()))}, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def register(root, name: str, folder) -> None:
    name = valid_name(name)
    entries = registry(root)
    if name in entries and not _same(entries[name], folder):
        raise ValueError(f"a study named {name} already exists at {entries[name]}")
    if (workspace(root) / name / "study.json").is_file() and not _same(workspace(root) / name, folder):
        raise ValueError(f"a study named {name} already exists in the workspace")
    entries[name] = str(Path(folder).resolve())
    _save_registry(root, entries)


def unregister(root, name: str) -> bool:
    entries = registry(root)
    if entries.pop(name, None) is None:
        return False
    _save_registry(root, entries)
    return True


def study_path(root, name: str, location=None) -> Path:
    """The folder of study `name`: the workspace's <workspace>/<name>, or the registered external folder, or (for a NEW study with `location`) <location>/<name>.
    The one place a study folder is worked out. Raises ValueError for a bad name, a clash between workspace and external names, or a location that is not there."""
    name = valid_name(name)
    entries, ws = registry(root), workspace(root)
    if location:
        loc = Path(str(location)).expanduser()
        if not loc.is_absolute():
            raise ValueError("give the full path of the folder that will hold the study (for example D:\\Studies or /mnt/d/Studies)")
        if _same(loc, ws):
            location = None
        else:
            if not loc.is_dir():
                raise ValueError(f"the study location {loc} does not exist: choose or create the folder first (a disconnected drive is never created for you)")
            target = loc / name
            if name in entries and not _same(entries[name], target):
                raise ValueError(f"a study named {name} already exists at {entries[name]}")
            if (ws / name / "study.json").is_file():
                raise ValueError(f"a study named {name} already exists in the workspace")
            return target
    if name in entries:
        return Path(entries[name])
    return ws / name


def is_external(root, folder) -> bool:
    return not _same(Path(folder).parent, workspace(root))


def external_folders(root) -> list:
    return [Path(p) for p in registry(root).values()]


def valid_name(name: str) -> str:
    name = (name or "").strip()
    if not NAME_RE.match(name):
        raise ValueError(f"study name {name!r}: use letters, digits, '.', '_' or '-', starting with a letter or digit "
                         "(at most 80 characters)")
    if name.endswith((".", " ")) or name.split(".")[0].upper() in WINDOWS_RESERVED:
        raise ValueError(f"study name {name!r} is not allowed: Windows reserves names such as CON, PRN, AUX, NUL, COM1-9 and LPT1-9 "
                         "(with or without an extension), and a name cannot end with a dot or a space")
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


def _after_create(root, folder: Path) -> None:
    """An external study is registered, and gets its own .gitignore (the workspace repository does not cover it): data, results of the samples and reads stay out of git."""
    if not is_external(root, folder):
        return
    register(root, folder.name, folder)
    try:
        from . import gitops
        gitops.ensure_gitignore(folder, "runs")
    except Exception:  # noqa: BLE001 - a missing git helper must not stop a run
        pass


def data_record(folder) -> dict:
    try:
        rec = json.loads((Path(folder) / "study.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {"data_location": rec.get("data_location"), "data_dir": rec.get("data_dir")}


def resolve_data(root, folder, keep_in_study: bool = False, data_dir=None, shared_dir=None) -> tuple:
    """Decide where this run keeps downloaded reads and assemblies and record it in study.json. Returns (folder or None, message).

    --keep-data-in-study -> <study>/data (created); --data-dir X -> X; neither -> what the study recorded earlier (so Resume and later stages find the reads), else None
    (the shared folder from config.sh). An explicit choice overrides and updates the record."""
    folder = Path(folder)
    path = folder / "study.json"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        record = {"name": folder.name, "runs": []}
    chosen, message = None, ""
    if keep_in_study:
        chosen = folder / "data"
        chosen.mkdir(parents=True, exist_ok=True)
        record["data_location"], record["data_dir"] = "study", str(chosen)
        message = f"Downloaded data stays inside the study: {chosen} (git-ignored, deleted with the study)"
    elif data_dir:
        chosen = Path(data_dir)
        record["data_location"], record["data_dir"] = "custom", str(chosen)
        message = f"Downloaded data goes to {chosen} (recorded for this study)"
    elif record.get("data_location") in ("study", "custom") and record.get("data_dir"):
        chosen = Path(record["data_dir"])
        if record["data_location"] == "study":
            chosen.mkdir(parents=True, exist_ok=True)
        message = (f"Downloaded data folder: {chosen} (recorded for this study; give --data-dir or --keep-data-in-study to change it)")
    else:
        record["data_location"] = "shared"
        if shared_dir:
            record["data_dir"] = str(shared_dir)
    if path.parent.is_dir():
        path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return chosen, message


def parse_depth_cap(text):
    """--read-depth-cap / READ_DEPTH_CAP_X: 'off' (also 0, none, false, no, whole) or a number of x coverage. Returns the canonical text ('off' or '150'); ValueError for anything else."""
    value = str(text if text is not None else "").strip().lower()
    if value in ("off", "0", "none", "false", "no", "whole"):
        return "off"
    try:
        number = float(value)
    except ValueError:
        raise ValueError(f"--read-depth-cap must be off or a number of x coverage (for example 150), not {text!r}")
    if number <= 0:
        return "off"
    return str(int(number)) if number == int(number) else str(number)


def resolve_depth_cap(folder, requested=None) -> tuple:
    """The read-depth cap for this run, recorded in study.json like the data folder: (value or None, message).

    `requested` (the --read-depth-cap flag) wins and is recorded; otherwise the study's recorded value is reused (so a resumed or repeated run keeps the choice); with neither, None
    (the READ_DEPTH_CAP_X of config/config.sh or the environment applies, default 150)."""
    path = Path(folder) / "study.json"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        record = {"name": Path(folder).name, "runs": []}
    if requested not in (None, ""):
        value = parse_depth_cap(requested)
        record["read_depth_cap"] = value
        message = f"Read depth cap: {'off (whole read files)' if value == 'off' else value + 'x'} (recorded for this study)"
    elif record.get("read_depth_cap"):
        value = str(record["read_depth_cap"])
        message = f"Read depth cap: {'off (whole read files)' if value == 'off' else value + 'x'} (recorded for this study; give --read-depth-cap to change it)"
    else:
        return None, ""
    if Path(path).parent.is_dir():
        path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return value, message


def prepare(root, name: str, samples=None, cohort=None, argv=None, location=None) -> Path:
    """Create (or reuse) the study folder and record this run in its study.json. Returns the folder."""
    folder = study_path(root, name, location)
    for sub in SUBDIRS:
        (folder / sub).mkdir(parents=True, exist_ok=True)
    _after_create(root, folder)
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
    record.setdefault("runs", []).append({"started": now, "command": "plasbench " + " ".join(argv or []), "via": os.environ.get("PLASBENCH_STARTED_VIA") or "terminal",
                                 "runtime": os.environ.get("PLASBENCH_RUNTIME_EFFECTIVE") or "conda"})
    record["runs"] = record["runs"][-200:]
    record_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return folder


def create(root, name: str, note: str = "", location=None) -> Path:
    """An empty study (from the window's New study button): its folders and a study.json, no run yet. `location` puts it outside the workspace."""
    folder = study_path(root, name, location)
    if (folder / "study.json").exists():
        raise ValueError(f"a study named {folder.name} already exists")
    for sub in SUBDIRS:
        (folder / sub).mkdir(parents=True, exist_ok=True)
    _after_create(root, folder)
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    record = {"schema_version": 1, "name": folder.name, "created": now, "updated": now, "note": note, "tags": [], "runs": []}
    (folder / "study.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return folder


def add_existing(root, folder) -> Path:
    """Register a folder that already holds a study.json (from "Add an existing study folder...")."""
    folder = Path(str(folder)).expanduser()
    if not folder.is_dir() or not (folder / "study.json").is_file():
        raise ValueError(f"{folder} has no study.json: choose a study folder")
    try:
        name = valid_name(json.loads((folder / "study.json").read_text(encoding="utf-8")).get("name") or folder.name)
    except (OSError, ValueError):
        name = valid_name(folder.name)
    if _same(folder.parent, workspace(root)):
        raise ValueError(f"{folder} is already in the workspace")
    if folder.name != name:
        raise ValueError(f"the folder is named {folder.name} but its study is named {name}: rename the folder to {name} first")
    register(root, name, folder)
    return folder


def _data_facts(folder: Path, record: dict) -> dict:
    where = record.get("data_location") or "shared"
    inside = where == "study" and (folder / "data").is_dir()
    out = {"data_location": where, "data_dir": record.get("data_dir"), "data_in_study": inside, "data_bytes": None}
    if inside:
        try:
            from . import runfolders
            counted = runfolders._count(folder / "data", 5000, 0.4)
            out["data_bytes"], out["data_capped"] = counted["bytes"], counted["capped"]
        except Exception:  # noqa: BLE001
            pass
    return out


def _study_entry(folder: Path, external: bool, base: Path):
    """One study's row (everything but the downloaded-data size) and its study.json record. Remembered by list_studies until a file it was built from changes."""
    try:
        record = json.loads((folder / "study.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        record = {}
    results = folder / "results"
    stamp = max([p.stat().st_mtime for p in (folder / "study.json", results / "benchmark.report.html",
                                                results / "benchmark.leaderboard.tsv") if p.exists()] or [folder.stat().st_mtime])
    entry = {"name": folder.name, "path": str(folder), "results": str(results), "modified": stamp,
             "cohort": record.get("cohort"), "sample_sheet": record.get("sample_sheet"),
             "runs": len(record.get("runs", [])), "report": (results / "benchmark.report.html").is_file(),
             "created": record.get("created"), "note": record.get("note", ""), "tags": record.get("tags", []),
             "cloned_from": record.get("cloned_from"), "imported_from": record.get("imported_from"),
             "migrated_from": record.get("migrated_from"), "tracked": (folder / ".git").exists() or ((base / ".git").exists() and not external),
             "tracked_in": "own" if (folder / ".git").exists() else ("workspace" if (base / ".git").exists() and not external else None),
             "last_command": (record.get("runs") or [{}])[-1].get("command"), "external": external, "available": True}
    return entry, record


def list_studies(root) -> list:
    """Every study in the workspace and every registered external one, newest first, with what the window shows about it. An external study whose folder is missing
    (a disconnected drive) is listed with available False and the reason; it is never an exception."""
    base = workspace(root)
    out = []
    todo = []
    if base.is_dir():
        todo += [(f, False) for f in base.iterdir() if f.is_dir() and not f.name.startswith(".")]
    for name, where in registry(root).items():
        todo.append((Path(where), True))
    for folder, external in todo:
        if external and not (folder / "study.json").is_file():
            out.append({"name": folder.name, "path": str(folder), "results": str(folder / "results"), "modified": 0, "cohort": None, "sample_sheet": None, "runs": 0,
                        "report": False, "created": None, "note": "", "tags": [], "cloned_from": None, "imported_from": None, "migrated_from": None, "tracked": False,
                        "tracked_in": None, "last_command": None, "external": True, "available": False,
                        "unavailable": f"not available: {folder} (is the drive connected?)", "data_location": None, "data_dir": None, "data_in_study": False, "data_bytes": None})
            continue
        results = folder / "results"
        signature = loadcache.sig(folder, folder / "study.json", results / "benchmark.report.html", results / "benchmark.leaderboard.tsv", folder / ".git", base / ".git") + (external, str(base))
        entry, record = loadcache.memo(("study", str(folder)), signature, lambda f=folder, e=external: _study_entry(f, e, base))
        out.append(dict(entry, **_data_facts(folder, record)))
    out.sort(key=lambda s: -s["modified"])
    return out
