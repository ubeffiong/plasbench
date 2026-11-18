"""Deleting a run's results folder from the window, safely, and browsing the workspace tree.

Two separate things (the window shows both):
  * "Remove from list" only forgets a folder in the saved Runs list (webui `runs/forget`): the files stay.
  * "Delete run folder" (`runs/delete`) removes the folder and everything in it. It is allowed ONLY for
      (a) a `results` / `results_*` folder directly inside a study folder (one with a study.json) of the workspace, or
      (b) a folder registered in the Runs list whose contents look like a PlasBench results folder (it has tool_status.tsv, run_manifest.json, scores.tsv,
          benchmark.leaderboard.tsv or benchmark.report.html),
    never the PlasBench program folder, the workspace, a study folder that is not named results*, the home folder, a drive or filesystem root, a parent of any
    of those, or a symbolic link; and never while a run that is going uses it. A refusal is a RunFolderError with the HTTP status the window shows (403, 404, 409).

`list_dir` / `properties` back the Workspace page's folder tree: confined to the workspace (and the program folder's own studies), never following symlinks out.
Standard library only.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import time
from pathlib import Path

RESULT_MARKERS = ("tool_status.tsv", "run_manifest.json", "scores.tsv", "benchmark.leaderboard.tsv", "benchmark.report.html")
LIST_CAP = 1000
WALK_ENTRIES = 20000
WALK_SECONDS = 2.0
FACTS_CAP = 200_000


class RunFolderError(ValueError):
    """A refused folder action; `status` is the HTTP status (403 refused, 404 missing, 409 busy)."""

    def __init__(self, message, status=403):
        super().__init__(message)
        self.status = status


def _real(path) -> Path:
    return Path(os.path.realpath(str(path)))


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def looks_like_results(folder) -> bool:
    folder = Path(folder)
    return any((folder / m).is_file() for m in RESULT_MARKERS)


def _study_json(folder: Path) -> dict:
    try:
        return json.loads((folder / "study.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def git_tracked(folder: Path, workspace: Path) -> bool:
    """True when the folder sits in a git repository of the working directory: its own, a study's, or the workspace's."""
    ws = _real(workspace)
    cur = _real(folder)
    while True:
        if (cur / ".git").exists():
            return True
        if cur == ws or cur.parent == cur:
            return False
        cur = cur.parent


def check_deletable(project_root, workspace, home, path, registered=(), running_results=()) -> Path:
    """The real folder for `path` when it may be deleted as a run folder; otherwise raises RunFolderError."""
    raw = str(path or "").strip()
    if not raw:
        raise RunFolderError("no folder was given", 400)
    p = Path(raw).expanduser()
    if not p.exists():
        raise RunFolderError(f"{p} does not exist", 404)
    if p.is_symlink():
        raise RunFolderError(f"{p} is a symbolic link: refusing to delete through it")
    real = _real(p)
    if not real.is_dir():
        raise RunFolderError(f"{real} is not a folder")
    ws, root, home_dir = _real(workspace), _real(project_root), _real(home)
    if real.parent == real:
        raise RunFolderError("a drive or filesystem root is never deleted")
    for name, protected in (("the PlasBench program folder", root), ("the workspace", ws), ("your home folder", home_dir)):
        if real == protected or _inside(protected, real):
            raise RunFolderError(f"{real} is or contains {name}: refusing")
    allowed = False
    if real.parent.parent == ws and (real.name == "results" or real.name.startswith("results_")) and (real.parent / "study.json").is_file():
        allowed = True                                       # (a) a results folder of a study
    elif any(real == _real(r) for r in registered):
        if (real / "study.json").is_file():
            raise RunFolderError("this is a study folder, not a results folder: manage or delete it from Manage study")
        if not looks_like_results(real):
            raise RunFolderError("this folder does not look like a PlasBench results folder (no tool_status.tsv, run_manifest.json, scores.tsv, leaderboard or report)")
        allowed = True                                       # (b) a registered run that looks like results
    if not allowed:
        if real.parent == ws and (real / "study.json").is_file():
            raise RunFolderError("this is a study folder, not a results folder: manage or delete it from Manage study")
        raise RunFolderError("only a study's results folder, or a folder in the Runs list that holds PlasBench results, can be deleted here")
    for res in running_results:
        if not res:
            continue
        other = _real(res)
        if other == real or _inside(other, real) or _inside(real, other):
            raise RunFolderError("a run is using this folder: Cancel the run first", 409)
    return real


def _readonly_ok(function, path, _exc) -> None:
    os.chmod(path, stat.S_IWRITE)
    function(path)


def _count(folder: Path, max_entries=FACTS_CAP, max_seconds=None) -> dict:
    files = dirs = size = 0
    newest = 0.0
    capped = False
    deadline = time.monotonic() + max_seconds if max_seconds else None
    for base, subdirs, names in os.walk(folder):
        keep = []
        for d in subdirs:
            if not os.path.islink(os.path.join(base, d)):
                keep.append(d)
                dirs += 1
        subdirs[:] = keep
        for n in names:
            full = os.path.join(base, n)
            files += 1
            if files + dirs > max_entries or (deadline and time.monotonic() > deadline):
                capped = True
                break
            try:
                st = os.lstat(full)
                size += st.st_size
                newest = max(newest, st.st_mtime)
            except OSError:
                pass
        if capped:
            break
    return {"files": files, "dirs": dirs, "bytes": size, "capped": capped, "newest": newest or None}


def tool_status_counts(folder: Path) -> dict:
    """Rows of tool_status.tsv by status (when it has a status column), read lightly."""
    path = folder / "tool_status.tsv"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[:20001]
    except OSError:
        return {}
    if len(lines) < 2:
        return {"rows": 0}
    head = lines[0].split("\t")
    out = {"rows": len(lines) - 1}
    if "status" in head:
        i = head.index("status")
        by = {}
        for line in lines[1:]:
            cells = line.split("\t")
            if len(cells) > i:
                by[cells[i]] = by.get(cells[i], 0) + 1
        out["by_status"] = by
    return out


def facts(workspace, folder) -> dict:
    """What deleting a run folder removes: files, bytes, what it holds, whether git tracks it."""
    folder = Path(folder)
    out = {"name": folder.name, "path": str(folder)}
    out.update(_count(folder))
    out.update({"report": (folder / "benchmark.report.html").is_file(), "leaderboard": (folder / "benchmark.leaderboard.tsv").is_file(),
                "tool_status": tool_status_counts(folder), "tracked": git_tracked(folder, workspace)})
    return out


def delete(project_root, workspace, home, path, confirm, registered=(), running_results=()) -> dict:
    """Delete a run folder after check_deletable and the folder's own name typed back. Returns the facts of what was removed."""
    real = check_deletable(project_root, workspace, home, path, registered, running_results)
    if (confirm or "").strip() != real.name:
        raise RunFolderError("type the folder's name exactly to confirm the delete", 400)
    removed = facts(workspace, real)
    shutil.rmtree(real, onerror=_readonly_ok)
    removed["removed"] = True
    return removed


# ---------------------------------------------------------------- the workspace tree
def roots(project_root, workspace) -> list:
    out = [_real(workspace)]
    own = _real(Path(project_root) / "studies")
    if own not in out and own.is_dir():
        out.append(own)
    return out


def resolve(project_root, workspace, path) -> tuple:
    """(real path, the root it is under) for a path inside the workspace tree. A relative path is relative to the workspace. Refuses anything outside, and any path that
    passes through a symbolic link below the root."""
    rts = roots(project_root, workspace)
    raw = str(path or "").strip()
    p = Path(raw).expanduser() if raw else rts[0]
    if not p.is_absolute():
        p = rts[0] / p
    lexical = Path(os.path.abspath(str(p)))
    for rt in rts:
        base = Path(os.path.abspath(str(workspace if rt == rts[0] else rt)))
        for candidate_base in {base, rt}:
            if lexical == candidate_base or _inside(lexical, candidate_base):
                walk = candidate_base
                for part in lexical.relative_to(candidate_base).parts:
                    walk = walk / part
                    if walk.is_symlink():
                        raise RunFolderError("a symbolic link on the way: not followed", 403)
                real = _real(lexical)
                if real == rt or _inside(real, rt):
                    if not real.exists():
                        raise RunFolderError(f"{lexical} does not exist", 404)
                    return real, rt
    raise RunFolderError("that folder is outside the workspace", 403)


def _entry(full: Path, deadline) -> dict:
    try:
        st = os.lstat(full)
    except OSError:
        return {"name": full.name, "kind": "unknown", "size": None, "mtime": None, "children": None}
    if stat.S_ISLNK(st.st_mode):
        return {"name": full.name, "kind": "link", "size": None, "mtime": st.st_mtime, "children": None}
    if stat.S_ISDIR(st.st_mode):
        children = None
        if time.monotonic() < deadline:
            try:
                children = sum(1 for _ in os.scandir(full))
            except OSError:
                children = None
        entry = {"name": full.name, "kind": "dir", "size": None, "mtime": st.st_mtime, "children": children}
        if (full / "study.json").is_file():
            rec = _study_json(full)
            entry["study"] = {"name": rec.get("name", full.name), "note": rec.get("note", ""), "tags": rec.get("tags", [])}
        elif full.name == "results" or full.name.startswith("results_") or looks_like_results(full):
            entry["results"] = looks_like_results(full)
        return entry
    return {"name": full.name, "kind": "file", "size": st.st_size, "mtime": st.st_mtime, "children": None}


def list_dir(project_root, workspace, path) -> dict:
    real, root = resolve(project_root, workspace, path)
    if not real.is_dir():
        raise RunFolderError(f"{real} is not a folder", 400)
    deadline = time.monotonic() + WALK_SECONDS
    names = []
    truncated = False
    try:
        with os.scandir(real) as it:
            for e in it:
                if len(names) >= LIST_CAP:
                    truncated = True
                    break
                names.append(e.name)
    except OSError as exc:
        raise RunFolderError(f"cannot read {real}: {exc.strerror}", 403)
    entries = [_entry(real / n, deadline) for n in names]
    entries.sort(key=lambda e: (e["kind"] != "dir", e["name"].lower()))
    return {"path": str(real), "name": real.name, "root": str(root), "is_root": real == root,
            "parent": None if real == root else str(real.parent), "entries": entries, "truncated": truncated}


def properties(project_root, workspace, path) -> dict:
    real, root = resolve(project_root, workspace, path)
    st = os.lstat(real)
    out = {"path": str(real), "name": real.name, "kind": "dir" if real.is_dir() else "file", "modified": st.st_mtime,
           "created": getattr(st, "st_birthtime", None) or (st.st_ctime if os.name == "nt" else None),
           "tracked": git_tracked(real, workspace), "is_root": real == root, "relative": "" if real == root else str(real.relative_to(root)).replace(os.sep, "/")}
    if real.is_dir():
        out.update(_count(real, WALK_ENTRIES, WALK_SECONDS))
        if (real / "study.json").is_file():
            rec = _study_json(real)
            runs = rec.get("runs") or []
            out["study"] = {"name": rec.get("name", real.name), "note": rec.get("note", ""), "tags": rec.get("tags", []), "created": rec.get("created"),
                            "runs": len(runs), "last_command": (runs[-1] if runs else {}).get("command")}
        if looks_like_results(real) or real.name == "results" or real.name.startswith("results_"):
            out["results"] = {"leaderboard": (real / "benchmark.leaderboard.tsv").is_file(), "report": (real / "benchmark.report.html").is_file(),
                              "tool_status": tool_status_counts(real)}
    else:
        out.update({"files": 1, "dirs": 0, "bytes": st.st_size, "capped": False})
    return out
