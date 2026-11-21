"""File plans for the AI help: validate, preview (dry run), apply, undo.

The assistant may PROPOSE a plan (a ```pb-files block); it never runs one. This module is PlasBench's own code and is the only thing that touches the person's files, and only
inside a folder the person granted (plasbench/ai_folder.py), only from a closed set of operations, only after the person has reviewed the dry run and pressed Apply.

Operations (and nothing else; there is no delete, no overwrite without a backup, no symbolic link, no permission change, no program run, no binary edit):
    mkdir        {"op":"mkdir","path":"data/S1"}
    copy         {"op":"copy","from":"raw/a.fastq.gz","to":"data/S1/S1_1.fastq.gz"}      a file; the target must not exist; streamed in chunks with progress and cancel
    move         {"op":"move","from":"a.fastq.gz","to":"data/a.fastq.gz"}                 also renames; the target must not exist
    write_sheet  {"op":"write_sheet","path":"config/mine.tsv","columns":[...],"rows":[[...]]}  a new sample sheet (tab separated); an existing file is backed up first
    patch_sheet  {"op":"patch_sheet","path":"x.tsv","edits":[{"type":"rename_column","from":"id","to":"sample_id"}, {"type":"fix_delimiter"}, {"type":"normalise_ids"},
                 {"type":"set_cell","row":3,"column":"organism","value":"Escherichia coli"}, {"type":"fill","column":"gram_group","value":"Gram-negative"}]}
compress and decompress are not offered: a safe bounded implementation of both (bomb limits, partial files) is not worth the risk here.

Every applied plan writes an undo journal (~/.plasbench/ai/journal/<id>/journal.json plus backups of overwritten files); Undo restores the previous state and refuses a step whose
file changed since. Rate limits keep a runaway page or model from hammering the disk. Standard library only.
"""
from __future__ import annotations

import difflib
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import threading
import time
import unicodedata
from pathlib import Path

from . import ai_folder
from .ai_folder import FolderError, clean

OPS = ("mkdir", "copy", "move", "write_sheet", "patch_sheet")
MAX_OPS = 40
MAX_COPY_BYTES = 200 * 2**30
MAX_SHEET_BYTES = 1_000_000
MAX_ROWS = 5000
MAX_COLS = 40
MAX_CELL = 200
EDIT_TYPES = ("rename_column", "fix_delimiter", "normalise_ids", "set_cell", "fill")
SPACE_MARGIN = 50 * 2**20
CHUNK = 1 << 20


class RateLimit:
    """At most `n` calls per `per` seconds (a sliding window)."""

    def __init__(self, n: int, per: float):
        self.n, self.per, self.t, self.lock = n, per, [], threading.Lock()

    def allow(self) -> bool:
        now = time.time()
        with self.lock:
            self.t = [x for x in self.t if now - x < self.per]
            if len(self.t) >= self.n:
                return False
            self.t.append(now)
            return True


LIMITS = {"scan": RateLimit(10, 60), "plan": RateLimit(30, 60), "apply": RateLimit(8, 60), "undo": RateLimit(8, 60), "ui": RateLimit(60, 60)}


def journal_dir() -> Path:
    from . import ai_openrouter as orr
    return orr.ai_home() / "journal"


def audit(action: str, outcome: str, **counts) -> None:
    """One line in ~/.plasbench/ui/ai.log: the action id, the outcome and counts. Never contents, and never a path."""
    from . import ai_openrouter as orr
    try:
        p = orr.log_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        extra = " ".join("%s=%d" % (re.sub(r"[^a-z_]", "", k)[:20], int(v)) for k, v in counts.items() if isinstance(v, (int, float)))
        with open(p, "a", encoding="utf-8") as fh:
            fh.write("%s action=%s outcome=%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), re.sub(r"[^a-z_.]", "", action)[:30], re.sub(r"[^a-z_]", "", outcome)[:20], extra))
    except OSError:
        pass


def _fold(name: str) -> str:
    return unicodedata.normalize("NFC", name).casefold()


# --------------------------------------------------------------------------------------------------------------------------- sheets
def _read_text(path: Path):
    size = os.path.getsize(path)
    if size > MAX_SHEET_BYTES:
        raise FolderError("the sheet is larger than %d KB; it is not edited from here" % (MAX_SHEET_BYTES // 1000))
    raw = path.read_bytes()
    if b"\x00" in raw[:4096]:
        raise FolderError("this is a binary file, not a text sheet")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise FolderError("the sheet is not UTF-8 text")
    return text, raw.startswith(b"\xef\xbb\xbf")


def _parse_table(text: str):
    """(comment_lines_before_header, rows, delimiter) keeping comment lines that precede the header."""
    lines = text.splitlines()
    comments, body = [], []
    for ln in lines:
        if not body and (not ln.strip() or ln.lstrip().startswith("#")):
            comments.append(ln)
        elif ln.strip() and not ln.lstrip().startswith("#"):
            body.append(ln)
    if not body:
        raise FolderError("the sheet has no header line")
    delim = max(("\t", ",", ";"), key=lambda d: body[0].count(d))
    if body[0].count(delim) == 0:
        delim = "\t"
    import csv
    rows = [r for r in csv.reader(io.StringIO("\n".join(body)), delimiter=delim)]
    return comments, rows, delim


def _render(comments: list, rows: list) -> str:
    out = list(comments)
    for r in rows:
        out.append("\t".join(c.replace("\t", " ").replace("\r", " ").replace("\n", " ") for c in r))
    return "\n".join(out) + "\n"


def _norm_id(v: str) -> str:
    v = unicodedata.normalize("NFKD", v.strip())
    v = "".join(c for c in v if ord(c) < 128)
    v = re.sub(r"[^A-Za-z0-9._-]+", "_", v).strip("._-")
    return v


def apply_edits(text: str, edits: list):
    """(new_text, identity_changes, notes) after the edits; raises FolderError for an edit that cannot be applied. identity_changes is a list of (old_id, new_id)."""
    comments, rows, delim = _parse_table(text)
    head = [h.strip() for h in rows[0]]
    identity, notes = [], []
    if len(edits) > 60:
        raise FolderError("too many edits in one operation")
    for e in edits:
        t = e.get("type")
        if t not in EDIT_TYPES:
            raise FolderError("unknown edit type %s" % clean(t, 30))
        if t == "fix_delimiter":
            if delim == "\t":
                notes.append("the sheet is already tab separated")
            delim = "\t"
        elif t == "rename_column":
            a, b = str(e.get("from") or ""), str(e.get("to") or "")
            if a not in head or not re.fullmatch(r"[a-z][a-z0-9_]{0,40}", b) or b in head:
                raise FolderError("cannot rename column %s to %s" % (clean(a, 30), clean(b, 30)))
            if a == "sample_id" or b == "sample_id":
                identity.append(("column " + a, "column " + b))
            head[head.index(a)] = b
        elif t == "normalise_ids":
            if "sample_id" not in head:
                raise FolderError("there is no sample_id column")
            i = head.index("sample_id")
            for r in rows[1:]:
                if i < len(r) and r[i].strip() != _norm_id(r[i]):
                    identity.append((r[i].strip(), _norm_id(r[i])))
                    r[i] = _norm_id(r[i])
        elif t in ("set_cell", "fill"):
            col = str(e.get("column") or "")
            val = str(e.get("value") if e.get("value") is not None else "")
            if col not in head:
                raise FolderError("there is no column %s" % clean(col, 30))
            if len(val) > MAX_CELL or re.search(r"[\t\r\n\x00]", val) or any(unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp") for ch in val):
                raise FolderError("the value for %s contains characters that are not allowed in a cell" % clean(col, 30))
            i = head.index(col)
            if t == "set_cell":
                n = e.get("row")
                if not isinstance(n, int) or isinstance(n, bool) or not 2 <= n <= len(rows):
                    raise FolderError("row %s is outside the sheet (rows count from the header as row 1)" % clean(n, 10))
                rows_targets = [rows[n - 1]]
            else:
                rows_targets = [r for r in rows[1:] if i >= len(r) or not r[i].strip()]
            for r in rows_targets:
                while len(r) < len(head):
                    r.append("")
                if col == "sample_id":
                    identity.append((r[i].strip(), val))
                r[i] = val
    rows[0] = head
    width = len(head)
    for r in rows[1:]:
        while len(r) < width:
            r.append("")
    return _render(comments, rows), identity, notes


def diff_text(old: str, new: str, name: str) -> str:
    d = list(difflib.unified_diff(old.splitlines(), new.splitlines(), "a/" + name, "b/" + name, lineterm="", n=1))
    s = "\n".join(clean_line(x) for x in d)
    return s[:6000] + ("\n... (diff cut)" if len(s) > 6000 else "")


def clean_line(x: str) -> str:
    return "".join(ch for ch in x if unicodedata.category(ch) not in ("Cc", "Cf", "Zl", "Zp") or ch == "\t")[:400]


# ------------------------------------------------------------------------------------------------------------------------------- plan
def _need_str(op: dict, key: str) -> str:
    v = op.get(key)
    if not isinstance(v, str):
        raise FolderError("%s needs %s" % (op.get("op"), key))
    return v


def _free_space(path: str) -> int:
    p = path
    while p and not os.path.exists(p):
        np_ = os.path.dirname(p)
        if np_ == p:
            break
        p = np_
    try:
        return shutil.disk_usage(p).free
    except OSError:
        return 0


def plan(grant: "ai_folder.Grant", raw_ops) -> dict:
    """The dry run of a proposed plan. {"ok", "ops": [per-operation preview with "error" or "can_apply"], "bytes", "free", "problems", "identity_changes", "n"}. Nothing is written."""
    if not isinstance(raw_ops, list) or not raw_ops:
        raise FolderError("the plan has no operations")
    if len(raw_ops) > MAX_OPS:
        raise FolderError("the plan has more than %d operations; split it" % MAX_OPS)
    out, planned = [], {}                                  # planned: folded rel path -> op index that creates it
    total = 0
    for i, op in enumerate(raw_ops):
        item = {"i": i, "op": str(op.get("op")) if isinstance(op, dict) else "?", "error": "", "can_apply": False, "lines": [], "bytes": 0, "diff": "", "identity": []}
        out.append(item)
        try:
            if not isinstance(op, dict) or op.get("op") not in OPS:
                raise FolderError("not an allowed operation (allowed: %s)" % ", ".join(OPS))
            kind = op["op"]
            if kind == "mkdir":
                rel = _need_str(op, "path")
                p = grant.resolve(rel, parent_must_exist=False)
                item["target"] = rel
                if p.exists() and not p.is_dir():
                    raise FolderError("a file with that name exists")
                _collide(p, rel, planned, i, allow_existing_dir=True)
                item["lines"] = ["create folder %s" % clean(rel, 100)] if not p.exists() else ["folder %s already exists (nothing to do)" % clean(rel, 100)]
                item["noop"] = p.exists()
                planned[_fold(rel.strip("/"))] = i
            elif kind in ("copy", "move"):
                src_rel, dst_rel = _need_str(op, "from"), _need_str(op, "to")
                src = grant.resolve(src_rel, must_exist=True)
                if not src.is_file():
                    raise FolderError("%s is not a file (folders are not copied or moved as a whole)" % clean(src_rel, 60))
                dst = grant.resolve(dst_rel, parent_must_exist=False)
                if dst.exists() or os.path.lexists(dst):
                    raise FolderError("%s already exists: nothing is overwritten" % clean(dst_rel, 80))
                if _fold(src_rel.strip("/")) == _fold(dst_rel.strip("/")) and kind == "move" and src_rel != dst_rel:
                    pass                                                 # a case-only rename is allowed
                else:
                    _collide(dst, dst_rel, planned, i)
                size = src.stat().st_size
                if size > MAX_COPY_BYTES:
                    raise FolderError("the file is larger than %d GB" % (MAX_COPY_BYTES // 2**30))
                item.update(source=src_rel, target=dst_rel, bytes=size if kind == "copy" else 0)
                item["lines"] = ["%s %s -> %s (%s)" % ("copy" if kind == "copy" else "move", clean(src_rel, 70), clean(dst_rel, 70), ai_folder.human(size))]
                total += size if kind == "copy" else 0
                planned[_fold(dst_rel.strip("/"))] = i
            elif kind == "write_sheet":
                rel = _need_str(op, "path")
                if not rel.lower().endswith((".tsv", ".txt")):
                    raise FolderError("a sheet is written as .tsv")
                p = grant.resolve(rel, parent_must_exist=False)
                cols, rows = op.get("columns"), op.get("rows")
                if not isinstance(cols, list) or not isinstance(rows, list) or not cols or len(cols) > MAX_COLS or len(rows) > MAX_ROWS:
                    raise FolderError("columns and rows must be lists (at most %d columns and %d rows)" % (MAX_COLS, MAX_ROWS))
                table = [[_cell(c) for c in cols]] + [[_cell(c) for c in (r if isinstance(r, list) else [])] for r in rows]
                if any(len(r) != len(cols) for r in table):
                    raise FolderError("every row must have exactly %d cells" % len(cols))
                problems = ai_folder.validate_sheet(table, "\t")
                if problems:
                    raise FolderError("PlasBench's sheet check refuses it: row %d: %s" % (problems[0]["row"], problems[0]["text"]))
                new = _render([], table)
                old = ""
                if p.exists():
                    if not p.is_file():
                        raise FolderError("that name is a folder")
                    old, _bom = _read_text(p)
                    item["lines"] = ["replace %s (the old file is saved first and can be restored with Undo)" % clean(rel, 80)]
                else:
                    _collide(p, rel, planned, i)
                    item["lines"] = ["create sheet %s with %d rows" % (clean(rel, 80), len(table) - 1)]
                item.update(target=rel, diff=diff_text(old, new, os.path.basename(rel)), bytes=len(new.encode("utf-8")), new_text=new, replaces=p.exists())
                planned[_fold(rel.strip("/"))] = i
            elif kind == "patch_sheet":
                rel = _need_str(op, "path")
                p = grant.resolve(rel, must_exist=True)
                if not p.is_file():
                    raise FolderError("that is not a file")
                edits = op.get("edits")
                if not isinstance(edits, list) or not edits or not all(isinstance(e, dict) for e in edits):
                    raise FolderError("give a list of edits")
                old, bom = _read_text(p)
                new, identity, notes = apply_edits(old, edits)
                before = _problems(old)
                after = _problems(new)
                if new == old:
                    raise FolderError("the edits change nothing")
                if after:
                    raise FolderError("the patched sheet would still have %d problem(s) (%s): not offered until it is valid" % (len(after), clean(after[0], 120)))
                item.update(target=rel, diff=diff_text(old, new, os.path.basename(rel)), bytes=len(new.encode("utf-8")), new_text=new, bom=bom, replaces=True,
                            identity=[[clean(a, 40), clean(b, 40)] for a, b in identity[:30]], fixed=len(before))
                item["lines"] = ["edit %s: %d change(s); the sheet check goes from %d problem(s) to none%s" % (clean(rel, 70), len(edits), len(before), " (sample identities change: confirm)" if identity else "")]
                if notes:
                    item["lines"] += [clean(n_, 100) for n_ in notes]
                planned[_fold(rel.strip("/"))] = i
            item["can_apply"] = True
        except FolderError as exc:
            item["error"] = str(exc)
        except OSError as exc:
            item["error"] = "could not be checked (%s)" % clean(exc.strerror or exc, 60)
    free = _free_space(grant.root)
    problems = []
    if total and free < total + SPACE_MARGIN:
        problems.append("not enough free space: %s needed, %s free" % (ai_folder.human(total), ai_folder.human(free)))
    return {"ok": all(o["can_apply"] for o in out) and not problems, "ops": out, "bytes": total, "free": free, "problems": problems, "n": len(out),
            "identity_changes": any(o["identity"] for o in out)}


def _problems(text: str) -> list:
    try:
        _c, rows, delim = _parse_table(text)
    except FolderError as exc:
        return [str(exc)]
    return ["row %d: %s" % (p["row"], p["text"]) if p["row"] else p["text"] for p in ai_folder.validate_sheet(rows, delim)]


def _cell(c) -> str:
    s = "" if c is None else str(c)
    if len(s) > MAX_CELL or re.search(r"[\t\r\n\x00]", s) or any(unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp") for ch in s):
        raise FolderError("a cell contains a line break, tab, control or invisible character, or is too long")
    return s.strip()


def _collide(p: Path, rel: str, planned: dict, i: int, allow_existing_dir: bool = False) -> None:
    key = _fold(rel.strip("/"))
    if key in planned and planned[key] != i:
        raise FolderError("%s collides with another operation of this plan (names are compared without case on Windows and macOS)" % clean(rel, 60))
    parent = p.parent
    if parent.is_dir():
        for name in os.listdir(parent):
            if _fold(name) == _fold(p.name) and name != p.name:
                raise FolderError("%s differs only in letter case from the existing %s" % (clean(p.name, 40), clean(name, 40)))


# -------------------------------------------------------------------------------------------------------------------------------- apply
def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _copy_stream(src: Path, dst: Path, progress, cancel) -> int:
    tmp = dst.with_name(dst.name + ".plasbench-part")
    n = 0
    try:
        with open(src, "rb") as a, open(tmp, "xb") as b:
            for chunk in iter(lambda: a.read(CHUNK), b""):
                if cancel is not None and cancel.is_set():
                    raise InterruptedError("cancelled")
                b.write(chunk)
                n += len(chunk)
                if progress:
                    progress(len(chunk))
        os.replace(tmp, dst)
        shutil.copystat(src, dst, follow_symlinks=False)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return n


def _save_journal(jdir: Path, data: dict) -> None:
    from . import ai_openrouter as orr
    orr.write_private(jdir / "journal.json", data)


def apply(grant: "ai_folder.Grant", raw_ops: list, selected=None, ack_identity: bool = False, progress=None, cancel=None) -> dict:
    """Run the operations of a plan the person has reviewed. The plan is validated AGAIN here (the page's copy is never trusted). `selected` is the list of operation indexes the
    person left ticked. On a failure or a cancel the operations already done are rolled back, in reverse order. Returns {"ok", "journal", "done", "rolled_back", "error", "results"}."""
    pl = plan(grant, raw_ops)
    sel = sorted(set(selected)) if selected is not None else list(range(len(raw_ops)))
    chosen = [o for o in pl["ops"] if o["i"] in sel]
    if not chosen:
        raise FolderError("no operation is ticked")
    bad = [o for o in chosen if not o["can_apply"]]
    if bad:
        raise FolderError("operation %d cannot be applied: %s" % (bad[0]["i"] + 1, bad[0]["error"]))
    if any(o["identity"] for o in chosen) and not ack_identity:
        raise FolderError("this plan changes sample identities: confirm that first")
    need = sum(o["bytes"] for o in chosen if o["op"] == "copy")
    if need and _free_space(grant.root) < need + SPACE_MARGIN:
        raise FolderError("not enough free space for the copies")
    jid = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
    jdir = journal_dir() / jid
    (jdir / "backups").mkdir(parents=True, exist_ok=True)
    journal = {"id": jid, "root": grant.root, "t": int(time.time()), "state": "running", "steps": []}
    _save_journal(jdir, journal)
    results, tot = [], max(1, need)
    done_bytes = [0]

    def prog(n):
        done_bytes[0] += n
        if progress:
            progress({"bytes": done_bytes[0], "total": tot})

    def rollback():
        undone, _sk = _undo_steps(grant, journal["steps"], jdir)
        journal["state"] = "rolled_back"
        _save_journal(jdir, journal)
        return undone
    try:
        for o in chosen:
            if cancel is not None and cancel.is_set():
                raise InterruptedError("cancelled")
            op = raw_ops[o["i"]]
            kind = o["op"]
            if kind == "mkdir":
                p = grant.resolve(op["path"])
                if p.exists():
                    results.append({"i": o["i"], "ok": True, "note": "already there"})
                    continue
                created = _mkdirs(grant, p)
                journal["steps"].append({"op": "mkdir", "paths": [_rel(grant, c) for c in created]})
            elif kind == "copy":
                src, dst = grant.resolve(op["from"], must_exist=True), grant.resolve(op["to"])
                created = _mkdirs(grant, dst.parent) if not dst.parent.exists() else []
                if created:
                    journal["steps"].append({"op": "mkdir", "paths": [_rel(grant, c) for c in created]})
                n = _copy_stream(src, dst, prog, cancel)
                journal["steps"].append({"op": "copy", "to": _rel(grant, dst), "size": n, "sha": _sha(dst)})
            elif kind == "move":
                src, dst = grant.resolve(op["from"], must_exist=True), grant.resolve(op["to"])
                created = _mkdirs(grant, dst.parent) if not dst.parent.exists() else []
                if created:
                    journal["steps"].append({"op": "mkdir", "paths": [_rel(grant, c) for c in created]})
                os.rename(src, dst)
                journal["steps"].append({"op": "move", "from": _rel(grant, src), "to": _rel(grant, dst)})
            else:
                dst = grant.resolve(op["path"] if kind == "write_sheet" else op["path"], must_exist=(kind == "patch_sheet"))
                created = _mkdirs(grant, dst.parent) if not dst.parent.exists() else []
                if created:
                    journal["steps"].append({"op": "mkdir", "paths": [_rel(grant, c) for c in created]})
                backup = ""
                if dst.exists():
                    backup = "%d_%s_%s" % (o["i"], time.strftime("%Y%m%d-%H%M%S"), re.sub(r"[^A-Za-z0-9._-]", "_", dst.name))
                    shutil.copy2(dst, jdir / "backups" / backup)
                data = (b"\xef\xbb\xbf" if o.get("bom") else b"") + o["new_text"].encode("utf-8")
                tmp = dst.with_name(dst.name + ".plasbench-part")
                with open(tmp, "wb") as fh:
                    fh.write(data)
                os.replace(tmp, dst)
                journal["steps"].append({"op": "write", "path": _rel(grant, dst), "backup": backup, "sha": _sha(dst)})
            _save_journal(jdir, journal)
            results.append({"i": o["i"], "ok": True})
    except InterruptedError:
        undone = rollback()
        audit("files.apply", "cancelled", ops=len(chosen), undone=undone)
        return {"ok": False, "journal": jid, "done": 0, "rolled_back": undone, "error": "cancelled: what was done has been undone", "results": results}
    except (OSError, FolderError) as exc:
        undone = rollback()
        audit("files.apply", "failed", ops=len(chosen), undone=undone)
        return {"ok": False, "journal": jid, "done": len(results), "rolled_back": undone, "error": "stopped at operation %d (%s); %d step(s) were undone" % (len(results) + 1, clean(getattr(exc, "strerror", None) or exc, 80), undone),
                "results": results}
    journal["state"] = "applied"
    _save_journal(jdir, journal)
    audit("files.apply", "ok", ops=len(chosen), steps=len(journal["steps"]))
    return {"ok": True, "journal": jid, "done": len(results), "rolled_back": 0, "error": "", "results": results}


def _rel(grant, p) -> str:
    return os.path.relpath(str(p), grant.root).replace(os.sep, "/")


def _mkdirs(grant, p: Path) -> list:
    """Create the missing folders down to p, one by one (each checked inside the grant); returns those created, outermost first."""
    missing = []
    cur = p
    while not cur.exists():
        missing.append(cur)
        cur = cur.parent
    created = []
    for d in reversed(missing):
        grant.resolve(_rel(grant, d))
        os.mkdir(d)
        created.append(d)
    return created


def _undo_steps(grant, steps: list, jdir: Path):
    """Reverse the steps, last first. A step whose file changed since (its hash differs) is left alone. Returns (restored, skipped)."""
    restored = skipped = 0
    for st in reversed(steps):
        try:
            if st["op"] == "copy":
                p = grant.resolve(st["to"], must_exist=True)
                if _sha(p) == st["sha"]:
                    os.unlink(p)
                    restored += 1
                else:
                    skipped += 1
            elif st["op"] == "move":
                src, dst = grant.resolve(st["from"]), grant.resolve(st["to"], must_exist=True)
                if not os.path.lexists(src):
                    os.rename(dst, src)
                    restored += 1
                else:
                    skipped += 1
            elif st["op"] == "mkdir":
                for rel in reversed(st["paths"]):
                    p = grant.resolve(rel, must_exist=True)
                    if p.is_dir() and not os.listdir(p):
                        os.rmdir(p)
                        restored += 1
                    else:
                        skipped += 1
            elif st["op"] == "write":
                p = grant.resolve(st["path"], must_exist=True)
                if _sha(p) != st["sha"]:
                    skipped += 1
                elif st.get("backup"):
                    shutil.copy2(jdir / "backups" / st["backup"], p)
                    restored += 1
                else:
                    os.unlink(p)
                    restored += 1
        except (OSError, FolderError):
            skipped += 1
    return restored, skipped


def undo(grant: "ai_folder.Grant", journal_id: str) -> dict:
    """Restore the state before an applied plan. A step whose file changed since is left alone and reported. Returns {"ok", "restored", "skipped"}."""
    if not re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{6}", str(journal_id or "")):
        raise FolderError("not a valid undo id")
    jdir = journal_dir() / journal_id
    try:
        with open(jdir / "journal.json", encoding="utf-8") as fh:
            j = json.load(fh)
    except (OSError, ValueError):
        raise FolderError("that undo record was not found")
    if os.path.normcase(os.path.realpath(j.get("root", ""))) != os.path.normcase(grant.root):
        raise FolderError("that change was made in a different folder")
    if j.get("state") in ("undone", "rolled_back"):
        raise FolderError("this change was already undone")
    restored, skipped = _undo_steps(grant, j.get("steps") or [], jdir)
    j["state"] = "undone"
    _save_journal(jdir, j)
    audit("files.undo", "ok", restored=restored, skipped=skipped)
    return {"ok": skipped == 0, "restored": restored, "skipped": skipped}


# -------------------------------------------------------------------------------------------------- background apply (progress, cancel)
JOBS = {}
_JLOCK = threading.Lock()


def start_apply(grant, raw_ops, selected, ack_identity) -> str:
    """Validate and start a plan in a background thread; poll with job_status(). The validation errors are raised here, before any thread starts."""
    pl = plan(grant, raw_ops)
    if not all(o["can_apply"] for o in pl["ops"] if selected is None or o["i"] in selected):
        bad = next(o for o in pl["ops"] if not o["can_apply"] and (selected is None or o["i"] in selected))
        raise FolderError("operation %d cannot be applied: %s" % (bad["i"] + 1, bad["error"]))
    jid = secrets.token_hex(6)
    cancel = threading.Event()
    job = {"state": "running", "bytes": 0, "total": 0, "result": None, "cancel": cancel, "t": time.time()}
    with _JLOCK:
        for k in [k for k, v in JOBS.items() if v["state"] != "running" and time.time() - v["t"] > 3600]:
            JOBS.pop(k, None)
        if sum(1 for v in JOBS.values() if v["state"] == "running") >= 2:
            raise FolderError("two plans are already being applied: wait for one to finish")
        JOBS[jid] = job

    def run():
        try:
            job["result"] = apply(grant, raw_ops, selected, ack_identity, progress=lambda d: job.update(bytes=d["bytes"], total=d["total"]), cancel=cancel)
        except FolderError as exc:
            job["result"] = {"ok": False, "error": str(exc), "journal": "", "done": 0, "rolled_back": 0, "results": []}
        except Exception as exc:  # noqa: BLE001
            job["result"] = {"ok": False, "error": "unexpected error: %s" % type(exc).__name__, "journal": "", "done": 0, "rolled_back": 0, "results": []}
        job["state"] = "done"
    threading.Thread(target=run, daemon=True).start()
    return jid


def job_status(jid: str) -> dict:
    j = JOBS.get(str(jid))
    if not j:
        raise FolderError("unknown job")
    return {"state": j["state"], "bytes": j["bytes"], "total": j["total"], "result": j["result"]}


def job_cancel(jid: str) -> bool:
    j = JOBS.get(str(jid))
    if j:
        j["cancel"].set()
    return bool(j)
