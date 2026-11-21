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
"""
from __future__ import annotations

import time

from . import ai_files, ai_flows, ai_folder, ai_ui
from .ai_folder import FolderError, GRANTS

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
                s = ai_flows.suggest_setup(ai_folder.scan(g))
            elif what == "sheet_fix":
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
    except FolderError as exc:
        ai_files.audit(route.replace("/", "."), "refused")
        return 400, {"error": str(exc), "kind": "folder"}
    except (TypeError, ValueError, AttributeError, KeyError) as exc:
        ai_files.audit(route.replace("/", "."), "badrequest")
        return 400, {"error": "the request was not understood (%s)" % type(exc).__name__, "kind": "bad_request"}
    return 404, {"error": "no such API: " + route}
