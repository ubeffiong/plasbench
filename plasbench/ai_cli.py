"""`plasbench ask "question"` and `plasbench ai status|signout`: the AI help from the command line, thin over plasbench/ai_help.py.

`ask` prints the answer, the documentation it was based on and any commands the assistant proposes. It NEVER runs a proposed command: copy it into your terminal (or press its button in
the window). It uses the same stored sign-in, the same free-model rules and the same daily limit as the window. Exit codes: 0 answered; 1 the service refused or failed; 2 not ready
(not signed in, notice not accepted, AI help off, bad question); 3 no internet. Standard library only.
"""
from __future__ import annotations

import json
import sys


def add_parsers(sub) -> None:
    ask = sub.add_parser("ask", help="Ask the AI help a question about PlasBench; prints the answer, its sources and any proposed commands (it never runs them). Uses a free model; sign in once in the window (AI help tab).")
    ask.add_argument("question", nargs="+", help="Your question, in words.")
    ask.add_argument("--provider", choices=["openrouter", "huggingface", "local"], help="Which provider to use (default: the AI_PROVIDER setting).")
    ask.add_argument("--model", help="A model of that provider (default: the AI_MODEL setting, else the best-suited free model in the provider's list).")
    ask.add_argument("--brief", action="store_true", help="Ask for a short answer (fewer tokens).")
    ask.add_argument("--accept-notice", action="store_true", help="Say that you have read what is sent and to whom (needed once per provider; the notice is printed first).")
    ask.add_argument("--json", action="store_true", help="Print the final answer as JSON.")
    ai = sub.add_parser("ai", help="AI help housekeeping: show where you are signed in, or sign out (deletes the stored key).")
    aisub = ai.add_subparsers(dest="ai_command", required=True)
    st = aisub.add_parser("status", help="Show the providers, whether you are signed in, and today's use (never prints a key).")
    st.add_argument("--json", action="store_true", help="Print as JSON.")
    out = aisub.add_parser("signout", help="Delete the stored key or token of a provider.")
    out.add_argument("--provider", choices=["openrouter", "huggingface"], default="openrouter", help="Which provider to sign out of (default: openrouter).")


def _project(root):
    if root is None:
        return None
    try:
        from . import webui
        return webui.Project(root)
    except Exception:  # noqa: BLE001 - settings are optional here
        return None


def command(args, root) -> int:
    from . import ai_help, netgate, ai_openrouter as orr
    project = _project(root)
    if args.command == "ai":
        svc = ai_help.Service(project, getattr(args, "provider", "") or "")
        if args.ai_command == "signout":
            svc.signout()
            print(f"Signed out of {svc.p.name}: the stored key was deleted.")
            return 0
        st = svc.status(detect=True)
        if args.json:
            print(json.dumps({k: st[k] for k in ("enabled", "provider", "providers", "used_today", "cap")}, indent=2))
            return 0
        print(f"AI help is {'on' if st['enabled'] else 'off (AI_HELP_ENABLED=0)'}.")
        for r in st["providers"]:
            extra = " (detected)" if r.get("detected") else ""
            print(f"  {r['id']:<12} {('no sign-in needed' if not r['needs_key'] else 'signed in') if r['signed_in'] else 'not signed in'}{extra}" + ("" if r["configured"] else f"  [{r['reason']}]"))
        u = st["used_today"]
        print(f"Today: {u['requests']} requests, {u['tokens']} tokens (limit {st['cap'] or 'none'}).")
        return 0
    svc = ai_help.Service(project, args.provider or "")
    if not ai_help.consent_given(svc.p.id):
        d = ai_help.disclosure(svc.p)
        print(d["declaration"] + "\n" + d["headline"] + "\nSent: " + "; ".join(d["sent"]) + "\nNot sent: " + "; ".join(d["not_sent"]) + "\n" + d["free"] + "\n" + d["stored"] + " " + d["delete"], file=sys.stderr)
        if not args.accept_notice:
            print("[plasbench] Read the notice above, then run again with --accept-notice.", file=sys.stderr)
            return 2
        ai_help.give_consent(svc.p.id)
    payload = {"question": " ".join(args.question), "brief": bool(args.brief), "model": args.model or ""}
    text, done, sources = [], None, []
    try:
        for ev in svc.ask(payload):
            if ev["type"] == "delta":
                text.append(ev["text"])
                if not args.json:
                    sys.stdout.write(ev["text"])
                    sys.stdout.flush()
            elif ev["type"] == "meta":
                sources = ev["sources"]
            elif ev["type"] == "notice":
                print("\n[plasbench] " + ev["text"], file=sys.stderr)
            elif ev["type"] == "error":
                print("\n[plasbench] ERROR: " + ev["error"], file=sys.stderr)
                return 1
            elif ev["type"] == "done":
                done = ev
    except netgate.Offline as exc:
        print("[plasbench] ERROR: " + exc.message, file=sys.stderr)
        return 3
    except orr.AiError as exc:
        print("[plasbench] ERROR: " + exc.message, file=sys.stderr)
        return 1 if exc.kind in ("no_credits", "rate_limit", "model_down", "server", "timeout", "offline", "cap") else 2
    if done is None:
        return 1
    if args.json:
        print(json.dumps({k: done[k] for k in ("text", "actions", "model", "provider", "usage")}, indent=2))
        return 0
    print()
    if sources:
        print("\nSources:")
        for x in sources:
            print(f"  [{x['n']}] {x['src']}" + (f"#{x['anchor']}" if x["anchor"] else "") + f"  {x['title'].split(' > ')[-1]}")
    if done["actions"]:
        print("\nProposed commands (not run; copy one into the place named):")
        for a in done["actions"]:
            where = {"window": "PlasBench's Terminal tab", "terminal": "PlasBench's Terminal tab", "powershell": "Windows PowerShell (not inside Ubuntu)", "wsl": "your Ubuntu (WSL) terminal", "host": "a terminal on this computer"}.get(a["where"], a["where"])
            note = "" if a["runnable"] else f"  [not runnable from the window: {a['reason']}]"
            print(f"  {a['cmd']}   <- run in {where}; {a['risk'].replace('_', ' ')}{note}\n      {a.get('why', '')}")
    u = done["usage"]
    print(f"\n[{done['model']}] {u['total']} tokens ({u['prompt']} in, {u['completion']} out){' (estimated)' if u['estimated'] else ''}; free: {'yes' if done['free'] else 'no'}", file=sys.stderr)
    return 0
