"""Managing studies in the working directory: rename, clone, archive and restore, delete safely, export and import a bundle, edit notes and tags.

A study is a folder in the workspace (the working directory) with a study.json (see studies.py). Everything here works on that folder only, never outside the workspace,
and refuses to touch a study while a run is using it (the caller says so with `busy`). Nothing is deleted without the study's own name typed back, and an archive keeps
the folder (moved to `<workspace>/.archive/`) so it can be restored.

The ideas follow the way GenoSuv keeps its working folder: validate before you act, never fall back silently, confine every path to the workspace, show what a delete
will remove before it happens, and keep an operational record. Rename, clone, archive and bundles are additions beyond it.

Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import time
import zipfile
from pathlib import Path

from . import studies

SCHEMA_VERSION = 1
ARCHIVE_DIR = ".archive"
BUNDLE_MANIFEST = "plasbench_study_bundle.json"
BUNDLE_SCHEMA = 1
MAX_TAGS = 12
MAX_TAG_LEN = 32
MAX_UNPACKED = 8 * 2**30            # a bundle that unpacks to more than this is refused
MAX_RATIO = 200                      # compressed-to-unpacked ratio above this looks like a zip bomb
SCAN_CAP = 200_000
# a bundle without results keeps the record and the study-level tables and reports; per-sample folders and heavy data stay out
LIGHT_SUFFIXES = (".tsv", ".csv", ".json", ".md", ".html", ".pdf", ".txt", ".png", ".svg")
SKIP_PARTS = {".git", "tmp", "__pycache__"}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _write_json(path: Path, record: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def study_dir(root, name: str) -> Path:
    """The folder of an existing study, confined to the workspace (a name is a name, never a path)."""
    name = studies.valid_name(name)
    ws = Path(os.path.realpath(studies.workspace(root)))
    folder = Path(os.path.realpath(ws / name))
    if folder.parent != ws:
        raise ValueError("that is not a study of this workspace")
    if not (folder / "study.json").is_file():
        raise ValueError(f"there is no study named {name}")
    return folder


def _guard_busy(busy, action: str) -> None:
    if busy:
        raise ValueError(f"a run is using this study: wait for it to finish (or cancel it) before you {action}")


def _readonly_ok(function, path, _exc) -> None:      # Windows: clear the read-only bit (git objects are read-only) and retry
    os.chmod(path, stat.S_IWRITE)
    function(path)


def facts(root, name: str) -> dict:
    """What a delete or archive would involve: files, bytes, steps, whether it is tracked by git; counted, capped, never followed through links."""
    folder = study_dir(root, name)
    files = size = 0
    capped = False
    for base, dirs, names in os.walk(folder):
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(base, d))]
        for n in names:
            files += 1
            if files > SCAN_CAP:
                capped = True
                break
            try:
                size += os.path.getsize(os.path.join(base, n))
            except OSError:
                pass
        if capped:
            break
    record = _read_json(folder / "study.json")
    return {"name": folder.name, "path": str(folder), "files": files, "bytes": size, "capped": capped, "runs": len(record.get("runs", [])),
            "report": (folder / "results" / "benchmark.report.html").is_file(), "tracked": (folder / ".git").exists()}


# ---------------------------------------------------------------- metadata
def clean_tags(tags) -> list:
    out = []
    for tag in tags or []:
        tag = " ".join(str(tag).split())[:MAX_TAG_LEN]
        if tag and tag.lower() not in [t.lower() for t in out]:
            out.append(tag)
    return out[:MAX_TAGS]


def update_meta(root, name: str, note=None, tags=None) -> dict:
    """Edit a study's note and tags. study.json gains schema_version on the way."""
    folder = study_dir(root, name)
    record = _read_json(folder / "study.json")
    if note is not None:
        record["note"] = str(note).strip()[:2000]
    if tags is not None:
        record["tags"] = clean_tags(tags)
    record["schema_version"] = SCHEMA_VERSION
    record["updated"] = _now()
    _write_json(folder / "study.json", record)
    return {"name": folder.name, "note": record.get("note", ""), "tags": record.get("tags", [])}


# ---------------------------------------------------------------- rename, clone
def rename(root, name: str, new_name: str, busy: bool = False) -> Path:
    folder = study_dir(root, name)
    new_name = studies.valid_name(new_name)
    _guard_busy(busy, "rename it")
    target = folder.parent / new_name
    if target.exists():
        raise ValueError(f"a study named {new_name} already exists")
    if new_name.lower() == folder.name.lower() and new_name != folder.name:
        tmp = folder.parent / (new_name + ".renaming")      # a case-only change on a case-insensitive disk
        os.rename(folder, tmp)
        os.rename(tmp, target)
    else:
        os.rename(folder, target)
    record = _read_json(target / "study.json")
    record["renamed_from"] = folder.name
    record["name"] = new_name
    record["schema_version"] = SCHEMA_VERSION
    record["updated"] = _now()
    _write_json(target / "study.json", record)
    return target


def clone(root, name: str, new_name: str, with_results: bool = False) -> Path:
    """A new study with the same sample sheet, cohort, note and tags and an empty run history. Results are copied only when asked (they can be large)."""
    folder = study_dir(root, name)
    new_name = studies.valid_name(new_name)
    target = folder.parent / new_name
    if target.exists():
        raise ValueError(f"a study named {new_name} already exists")
    for sub in studies.SUBDIRS:
        (target / sub).mkdir(parents=True)
    if with_results and (folder / "results").is_dir():
        shutil.copytree(folder / "results", target / "results", dirs_exist_ok=True, symlinks=False)
    record = _read_json(folder / "study.json")
    now = _now()
    out = {"schema_version": SCHEMA_VERSION, "name": new_name, "created": now, "updated": now, "cloned_from": folder.name, "note": record.get("note", ""),
           "tags": record.get("tags", []), "runs": []}
    for key in ("sample_sheet", "sample_sheet_sha256", "cohort"):
        if record.get(key):
            out[key] = record[key]
    _write_json(target / "study.json", out)
    return target


# ---------------------------------------------------------------- archive, restore, delete
def archive_root(root) -> Path:
    return Path(studies.workspace(root)) / ARCHIVE_DIR


def archive(root, name: str, busy: bool = False) -> Path:
    """Move a study to <workspace>/.archive/<name>-<timestamp>. Nothing is deleted; restore() brings it back."""
    folder = study_dir(root, name)
    _guard_busy(busy, "archive it")
    dest_root = archive_root(root)
    dest_root.mkdir(parents=True, exist_ok=True)
    dest = dest_root / f"{folder.name}-{time.strftime('%Y%m%d-%H%M%S')}"
    n = 1
    while dest.exists():
        n += 1
        dest = dest_root / f"{folder.name}-{time.strftime('%Y%m%d-%H%M%S')}-{n}"
    shutil.move(str(folder), str(dest))
    record = _read_json(dest / "study.json")
    record["archived"] = _now()
    record["archived_as"] = dest.name
    _write_json(dest / "study.json", record)
    return dest


def list_archived(root) -> list:
    base = archive_root(root)
    out = []
    if not base.is_dir():
        return out
    for folder in sorted(base.iterdir(), reverse=True):
        if folder.is_dir() and (folder / "study.json").is_file():
            record = _read_json(folder / "study.json")
            out.append({"archive": folder.name, "name": record.get("name", folder.name), "archived": record.get("archived"), "note": record.get("note", "")})
    return out


def restore(root, archive_name: str) -> Path:
    """Bring an archived study back under its own name (a number is added when that name is taken)."""
    base = Path(os.path.realpath(archive_root(root)))
    folder = Path(os.path.realpath(base / archive_name))
    if folder.parent != base or not (folder / "study.json").is_file():
        raise ValueError("that is not an archived study")
    record = _read_json(folder / "study.json")
    want = studies.valid_name(record.get("name") or archive_name)
    ws = Path(studies.workspace(root))
    target, n = ws / want, 1
    while target.exists():
        n += 1
        target = ws / f"{want[:70]}-{n}"
    shutil.move(str(folder), str(target))
    record["name"] = target.name
    record.pop("archived", None)
    record.pop("archived_as", None)
    record["restored"] = _now()
    _write_json(target / "study.json", record)
    return target


def delete(root, name: str, confirm_name: str, busy: bool = False) -> dict:
    """Delete a study for good (no recycle bin). Needs its own name typed back; returns what was removed."""
    folder = study_dir(root, name)
    if (confirm_name or "").strip() != folder.name:
        raise ValueError("type the study's name exactly to confirm the delete")
    _guard_busy(busy, "delete it")
    removed = facts(root, folder.name)
    shutil.rmtree(folder, onerror=_readonly_ok)
    return removed


# ---------------------------------------------------------------- bundles
def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _bundle_files(folder: Path, include_results: bool):
    for base, dirs, names in os.walk(folder):
        rel_base = Path(base).relative_to(folder)
        dirs[:] = sorted(d for d in dirs if d not in SKIP_PARTS and not os.path.islink(os.path.join(base, d)))
        for n in sorted(names):
            rel = rel_base / n
            parts = rel.parts
            if any(p in SKIP_PARTS for p in parts) or os.path.islink(os.path.join(base, n)):
                continue
            if not include_results and parts[0] == "results" and not (len(parts) == 2 and n.lower().endswith(LIGHT_SUFFIXES)):
                continue
            yield rel
    # study.json is at the top level and always included by the walk above


def export_bundle(root, name: str, out_path, include_results: bool = False, version: str = "") -> dict:
    """Write a zip of a study with a manifest (schema version, file list, sizes and SHA-256). Without results: the record and the study-level tables and reports."""
    folder = study_dir(root, name)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    files = []
    tmp = out_path.with_name(out_path.name + ".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in _bundle_files(folder, include_results):
            src = folder / rel
            z.write(src, arcname="study/" + rel.as_posix())
            files.append({"path": rel.as_posix(), "bytes": src.stat().st_size, "sha256": _sha256(src)})
        manifest = {"bundle_schema": BUNDLE_SCHEMA, "kind": "plasbench-study", "study": folder.name, "created": _now(), "plasbench_version": version,
                    "include_results": bool(include_results), "files": files}
        z.writestr(BUNDLE_MANIFEST, json.dumps(manifest, indent=2) + "\n")
    os.replace(tmp, out_path)
    return {"path": str(out_path), "files": len(files), "bytes": out_path.stat().st_size, "include_results": bool(include_results)}


def import_bundle(root, bundle_path, new_name=None) -> Path:
    """Unpack a bundle into the workspace as a new study. Every member path is checked (no traversal), the unpacked size is capped, and every file's SHA-256
    is verified against the manifest. An existing study is never overwritten."""
    bundle_path = Path(bundle_path)
    if not zipfile.is_zipfile(bundle_path):
        raise ValueError("that file is not a study bundle (a .zip made by Export)")
    with zipfile.ZipFile(bundle_path) as z:
        if BUNDLE_MANIFEST not in z.namelist():
            raise ValueError("that zip has no PlasBench manifest; it was not made by Export")
        manifest = json.loads(z.read(BUNDLE_MANIFEST).decode("utf-8"))
        if manifest.get("kind") != "plasbench-study" or int(manifest.get("bundle_schema", 0)) > BUNDLE_SCHEMA:
            raise ValueError("this bundle comes from a newer PlasBench or is not a study bundle")
        name = studies.valid_name(new_name or manifest.get("study", ""))
        ws = Path(os.path.realpath(studies.workspace(root)))
        target = ws / name
        if target.exists():
            raise ValueError(f"a study named {name} already exists: choose another name")
        members = [i for i in z.infolist() if i.filename != BUNDLE_MANIFEST and not i.is_dir()]
        total = sum(i.file_size for i in members)
        packed = sum(i.compress_size for i in members) or 1
        if total > MAX_UNPACKED or (total > 50 * 2**20 and total / packed > MAX_RATIO):
            raise ValueError("this bundle unpacks to an unreasonable size and was refused")
        listed = {f["path"]: f for f in manifest.get("files", [])}
        staging = ws / f".import-{name}-{os.getpid()}"
        shutil.rmtree(staging, ignore_errors=True)
        try:
            for info in members:
                if not info.filename.startswith("study/"):
                    raise ValueError(f"unexpected file in the bundle: {info.filename}")
                rel = info.filename[len("study/"):]
                dest = Path(os.path.realpath(staging / rel))
                if not str(dest).startswith(str(Path(os.path.realpath(staging))) + os.sep) or ".." in Path(rel).parts or Path(rel).is_absolute():
                    raise ValueError(f"unsafe path in the bundle: {info.filename}")
                dest.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
                expected = listed.get(rel)
                if expected and _sha256(dest) != expected.get("sha256"):
                    raise ValueError(f"{rel} does not match its checksum in the manifest: the bundle is damaged")
            if not (staging / "study.json").is_file():
                raise ValueError("the bundle has no study.json")
            for sub in studies.SUBDIRS:
                (staging / sub).mkdir(exist_ok=True)
            record = _read_json(staging / "study.json")
            record.update(name=name, schema_version=SCHEMA_VERSION, imported=_now(), imported_from=manifest.get("study"), updated=_now())
            _write_json(staging / "study.json", record)
            os.rename(staging, target)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    return target
