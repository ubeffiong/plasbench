"""The routes of the AI help that deal with the person's folder, file plans, window actions and guided flows (ai/folder/*, ai/files/*, ai/ui/*, ai/flow/*).

They are called by plasbench/ai_help.py serve() AFTER the window's token, Host and same-origin checks, like every /api/ai/ route. Each one validates its input again (the page's
copy of a plan or action is never trusted), is rate limited, and leaves one line in the audit log (action id, outcome, counts; never contents or paths).

    POST ai/folder/grant     {path, remember}       choose a folder (the native Browse picker gives the path)         -> the grant chip
    POST ai/folder/revoke    {id}
    GET  ai/folder/list                              the folders granted now
    POST ai/folder/scan      {id}                    read-only look inside; the card and the exact text that Share would send
    POST ai/folder/share     {id}                    mark the last scan's summary as the one the next question may carry
    POST ai/folder/resolve   {id, rel}               the real path of a file in the folder (to fill a form field with)
    POST ai/folder/suggest   {id, what, rel?}        deterministic proposals: setup (lay out reads and write a sheet) or sheet_fix
    POST ai/files/plan       {id, ops}               the dry run of a plan
    POST ai/files/apply      {id, ops, selected, ack_identity}   start applying (returns a job id)
    GET  ai/files/progress   ?job=                   progress and result
    POST ai/files/cancel     {job}
    POST ai/files/undo       {id, journal}
    POST ai/ui/validate      {ui}                    a window action, checked
    POST ai/flow/tool        {...answers}            the manifest `plasbench tools new` would write, validated
    POST ai/intake/options   {}                      where the isolates can go (PlasBench's data folder, a study's data folder) and the sheets of your own isolates
    POST ai/intake/plan      {id, dest, choices}     `plasbench intake scan` + `stage --dry-run` on the chosen folder (python/intake.py): the review card and its fingerprint
    POST ai/intake/apply     {id, dest, choices, fingerprint}   re-plan, refuse a changed plan, stage, then `intake check` (a job)
    GET  ai/intake/progress  ?job=
    POST ai/intake/undo      {journal}               remove what a set-up created (unchanged files only) and put the sheet back
    POST ai/intake/check     {dest, only?, deep?}    `plasbench intake check` on a sheet of your own isolates
    POST ai/intake/fix       {dest, only?}           `plasbench intake check --fix` (the sheet and truth tables are backed up first)
    POST ai/intake/labels    {dest, sample}          the sequences of a reference with their labels (REVIEW rows are the person's decision)
    POST ai/intake/labels/save {dest, sample, labels}
    POST ai/intake/share     {id, dest, choices}     mark a summary of the plan as the one the next question may carry
    POST ai/run/where        {study?}                "Where is my run?": plasbench status as a card (no model)
    POST ai/run/digest       {diagnose, failed}      "Why did my run fail?": the redacted, capped digest and the safe next steps
"""
from __future__ import annotations

import time

from . import ai_diagnose, ai_files, ai_flows, ai_folder, ai_intake, ai_ui
from .ai_folder import FolderError, GRANTS, clean

SHARES = {}            # grant id -> (time, summary text made by this server)
SHARE_TTL = 1800


def _limit(kind: str) -> None:
    if not ai_files.LIMITS[kind].allow():
        raise FolderError("too many requests (%s): wait a moment" % kind)


def share_text(grant_id: str) -> str:
    """The summary the person agreed to share with the last question: only what THIS server produced from its own scan, and only for a fresh share."""
    got = SHARES.get(str(grant_id or ""))
    if not got or time.time() - got[0] > SHARE_TTL:
        return ""
    return got[1]


def strip_plan(pl: dict) -> dict:
    """The plan preview for the page: no file contents beyond the diff."""
    out = dict(pl)
    out["ops"] = []
    for o in pl["ops"]:
        o = dict(o)
        o.pop("new_text", None)
        out["ops"].append(o)
    return out


def serve(route: str, data: dict, q: dict, project):
    """(status, payload). Raises nothing for a refusal: a refusal is (400, {"error": ...})."""
    try:
        if route == "ai/folder/list":
            return 200, {"folders": GRANTS.list()}
        if route == "ai/folder/grant":
            g = GRANTS.grant(str(data.get("path") or ""), bool(data.get("remember")))
            ai_files.audit("folder.grant", "ok", remember=1 if g.remember else 0)
            return 200, g.public()
        if route == "ai/folder/revoke":
            ok = GRANTS.revoke(str(data.get("id") or ""))
            SHARES.pop(str(data.get("id") or ""), None)
            ai_files.audit("folder.revoke", "ok" if ok else "none")
            return 200, {"ok": ok}
        if route == "ai/folder/scan":
            _limit("scan")
            g = GRANTS.get(data.get("id"))
            r = ai_folder.scan(g)
            text = ai_folder.summary_text(r)
            SHARES.pop(g.id, None)
            ai_files.audit("folder.scan", "ok", files=r["counts"]["files"], problems=len(r["problems"]))
            return 200, {"scan": r, "summary": text, "tokens": int(len(text) / 3.6) + 1}
        if route == "ai/folder/share":
            _limit("scan")
            g = GRANTS.get(data.get("id"))
            text = ai_folder.summary_text(ai_folder.scan(g))        # always made again, here: what the page displayed is not trusted
            SHARES[g.id] = (time.time(), text)
            ai_files.audit("folder.share", "ok", chars=len(text))
            return 200, {"summary": text, "tokens": int(len(text) / 3.6) + 1}
        if route == "ai/folder/resolve":
            g = GRANTS.get(data.get("id"))
            return 200, {"path": str(g.resolve(str(data.get("rel") or ""), must_exist=True))}
        if route == "ai/folder/suggest":
            _limit("plan")
            g = GRANTS.get(data.get("id"))
            what = data.get("what")
            if what == "setup":
                raise FolderError("isolate set-up now goes through PlasBench's intake: use ai/intake/plan")
            if what == "sheet_fix":
                s = ai_flows.suggest_sheet_fix(g, str(data.get("rel") or ""))
            else:
                raise FolderError("unknown suggestion")
            return 200, s
        if route == "ai/files/plan":
            _limit("plan")
            g = GRANTS.get(data.get("id"))
            pl = ai_files.plan(g, data.get("ops"))
            ai_files.audit("files.plan", "ok" if pl["ok"] else "refused", ops=pl["n"], bytes=pl["bytes"])
            return 200, strip_plan(pl)
        if route == "ai/files/apply":
            _limit("apply")
            g = GRANTS.get(data.get("id"))
            sel = data.get("selected")
            sel = [int(i) for i in sel] if isinstance(sel, list) and all(isinstance(i, int) and not isinstance(i, bool) for i in sel) else None
            job = ai_files.start_apply(g, data.get("ops"), sel, bool(data.get("ack_identity")))
            return 200, {"job": job}
        if route == "ai/files/progress":
            return 200, ai_files.job_status(str(q.get("job") or ""))
        if route == "ai/files/cancel":
            return 200, {"ok": ai_files.job_cancel(str(data.get("job") or ""))}
        if route == "ai/files/undo":
            _limit("undo")
            g = GRANTS.get(data.get("id"))
            return 200, ai_files.undo(g, str(data.get("journal") or ""))
        if route == "ai/ui/validate":
            _limit("ui")
            v = ai_ui.validate(data.get("ui"), project)
            ai_files.audit("ui." + (v.get("ui") or "none"), "ok" if v["ok"] else "refused")
            return 200, v
        if route == "ai/flow/tool":
            _limit("plan")
            return 200, ai_flows.tool_manifest(project, data if isinstance(data, dict) else {})
        if route == "ai/intake/options":
            return 200, ai_intake.destinations(project)
        if route == "ai/intake/plan":
            _limit("plan")
            g = GRANTS.get(data.get("id"))
            v = ai_intake.make_plan(project, g, data.get("dest"), data.get("choices"))[0]
            ai_files.audit("intake.plan", "ok" if v["can_apply"] else "refused", isolates=len(v["isolates"]), staged=v["staged"])
            return 200, v
        if route == "ai/intake/share":
            _limit("scan")
            g = GRANTS.get(data.get("id"))
            text = ai_intake.summary_text(ai_intake.make_plan(project, g, data.get("dest"), data.get("choices"))[0])     # made again here: the page's copy is not trusted
            SHARES[g.id] = (time.time(), text)
            ai_files.audit("intake.share", "ok", chars=len(text))
            return 200, {"summary": text, "tokens": int(len(text) / 3.6) + 1}
        if route == "ai/intake/apply":
            _limit("apply")
            g = GRANTS.get(data.get("id"))
            return 200, {"job": ai_intake.start_apply(project, g, data.get("dest"), data.get("choices"), str(data.get("fingerprint") or ""))}
        if route == "ai/intake/progress":
            return 200, ai_intake.job_status(str(q.get("job") or ""))
        if route == "ai/intake/undo":
            _limit("undo")
            return 200, ai_intake.undo(str(data.get("journal") or ""))
        if route in ("ai/intake/check", "ai/intake/fix", "ai/intake/labels", "ai/intake/labels/save"):
            _limit("plan" if route != "ai/intake/fix" else "apply")
            d = ai_intake.resolve_dest(project, data.get("dest"))
            only = [str(x) for x in data.get("only")][:200] if isinstance(data.get("only"), list) else None
            if route == "ai/intake/check":
                return 200, ai_intake.check_dest(project, d, only, deep=bool(data.get("deep", False)))
            if route == "ai/intake/fix":
                return 200, ai_intake.fix_dest(project, d, only)
            if route == "ai/intake/labels":
                return 200, ai_intake.labels(project, d, str(data.get("sample") or ""))
            return 200, ai_intake.save_labels(project, d, str(data.get("sample") or ""), data.get("labels"))
        if route == "ai/run/where":
            _limit("ui")
            return 200, ai_diagnose.where(project, str(data.get("study") or ""))
        if route == "ai/run/digest":
            _limit("ui")
            out = ai_diagnose.digest(project, str(data.get("diagnose") or "")[:400000], data.get("failed") if isinstance(data.get("failed"), dict) else None)
            ai_files.audit("run.digest", "ok", chars=len(out["text"]), causes=len(out["causes"]))
            return 200, out
    except FolderError as exc:
        ai_files.audit(route.replace("/", "."), "refused")
        return 400, {"error": str(exc), "kind": "folder"}
    except OSError as exc:
        ai_files.audit(route.replace("/", "."), "oserror")
        return 400, {"error": "a file could not be read or written (%s)" % clean(getattr(exc, "strerror", None) or type(exc).__name__, 80), "kind": "folder"}
    except (TypeError, ValueError, AttributeError, KeyError) as exc:
        ai_files.audit(route.replace("/", "."), "badrequest")
        return 400, {"error": "the request was not understood (%s)" % type(exc).__name__, "kind": "bad_request"}
    return 404, {"error": "no such API: " + route}
