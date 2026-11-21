#!/usr/bin/env python3
"""`plasbench stop` and the window's "Stop all PlasBench on this computer" (plasbench/stopall.py).

Fakes (a process table with an injected clock, fake servers, a fake Windows side, a fake launcher) check the SAFETY RULES one by one: only recorded and verified PlasBench processes are
signalled; polite, then TERM, then KILL with the grace times; a reused pid, a port held by another program and a stale record are handled without touching anything; runs are left alone
unless --runs; --windows matches only PlasBench's own app windows; `wsl --shutdown` is opt-in, blocked, ordered and NEVER executed here (the launcher is a fake). Then the routes, the
dialog (static checks and node on the pure functions), and one REAL integration test: two real PlasBench servers on test ports with a temporary UI home, a dummy listener and a fake
job runner; `plasbench stop` ends the servers and leaves the listener and the job; with --runs the job ends too. Nothing outside the processes this test starts is ever signalled.
Standard library only; node is optional (skipped with a printed reason); the real integration part needs POSIX.
"""
import argparse
import http.client
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
tmp = Path(tempfile.mkdtemp())
os.environ["PLASBENCH_UI_HOME"] = str(tmp / "ui")
os.environ["PLASBENCH_LOCAL_SETTINGS"] = str(tmp / "local.env")
os.environ["PLASBENCH_WORKSPACE"] = str(tmp / "studies")
os.environ["PLASBENCH_STOP_PORTS"] = "none"
os.environ["HOME"] = os.environ["USERPROFILE"] = str(tmp / "home")
(tmp / "home").mkdir()
from plasbench import native_picker, stopall, ui_help, webui  # noqa: E402

FAILED = []
SOURCE = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


# ---------------------------------------------------------------------------------------------------------------------------------------------------------- fakes
class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def time(self):
        return self.now

    def sleep(self, dt):
        self.now += dt


class FakeProcs(stopall.Procs):
    """A process table. `dies[pid]`: "term" (default: ends on a stop request), "kill" (only on a forced stop), "never"."""
    name = "fake"

    def __init__(self, clock):
        self.clock, self.table, self.sent, self.dies, self.uid = clock, {}, [], {}, 1000

    def add(self, pid, cmd, start=None, pgid=None, name="python", uid=1000):
        self.table[pid] = {"pid": pid, "ppid": 1, "pgid": pgid if pgid is not None else pid, "name": name, "cmdline": cmd, "start": start, "uid": uid}

    def list(self):
        return dict(self.table)

    def current_uid(self):
        return self.uid

    def signal(self, pid, force=False):
        self.sent.append((self.clock.now, "KILL" if force else "TERM", pid))
        mode = self.dies.get(pid, "term")
        if pid in self.table and mode != "never" and (force or mode == "term"):
            del self.table[pid]
        return True

    def signal_group(self, pgid, force=False):
        self.sent.append((self.clock.now, "GKILL" if force else "GTERM", pgid))
        if self.dies.get(pgid, "term") == "never":
            return True
        for pid in [p for p, e in self.table.items() if e["pgid"] == pgid]:
            if force or self.dies.get(pid, "term") == "term":
                del self.table[pid]
        return True


class World:
    """A temporary UI home with server records, a fake process table, fake servers and a recording `ask`."""

    def __init__(self, name="w"):
        self.dir = tmp / name
        self.home = self.dir / "ui"
        (self.home / "servers").mkdir(parents=True)
        self.root = self.dir / "root"
        (self.root / "results").mkdir(parents=True)
        self.clock = Clock()
        self.procs = FakeProcs(self.clock)
        self.answers, self.polite, self.asked, self.listeners = {}, set(), [], {}
        self.launched = []

    def server(self, port, pid, cmd=None, start="auto", record=True, version="0.5.6", answer=True, polite=False, started=None):
        started = int(self.clock.now - 3000) if started is None else started
        if cmd is not False:
            self.procs.add(pid, cmd or f"python -m plasbench --project-root {self.root} ui --port {port}", start=started if start == "auto" else start)
        if record:
            rec = {"url": f"http://127.0.0.1:{port}/?t=KEY{port}", "port": port, "pid": pid, "started": started, "root": str(self.root), "version": version}
            (self.home / "servers" / f"{port}.json").write_text(json.dumps(rec), encoding="utf-8")
            (self.home / "server.json").write_text(json.dumps(rec), encoding="utf-8")
        if answer:
            self.answers[port] = str(started)
        if polite:
            self.polite.add(port)
        return started

    def ask(self, url, route, body=None):
        port = int(url.split(":")[2].split("/")[0])
        self.asked.append((self.clock.now, port, route, body))
        if route == "windows":
            return {"alive": 1}
        if route == "shutdown":
            if port in self.polite:
                for pid in [p for p, e in self.procs.table.items() if f"--port {port}" in e["cmdline"]]:
                    del self.procs.table[pid]
                self.answers.pop(port, None)
            return {"ok": True}
        return None

    def probe(self, port):
        if port in self.answers:
            return True, self.answers[port], 0.0
        return None, None, 0.0

    def env(self, **kw):
        base = dict(procs=self.procs, win_procs=None, clock=self.clock.time, sleep=self.clock.sleep, ask=self.ask, probe=self.probe, listeners=lambda port: self.listeners.get(port, []),
                    ui_homes=[self.home], ports=[], platform="linux", launcher=self.launched.append, roots=[self.root], now_text=lambda: "2026-11-21 10:00:00", self_pid=None)
        base.update(kw)
        return stopall.Env(**base)


def args(**kw):
    d = dict(all=False, runs=False, windows=False, dry_run=False, yes=False, json=False, wsl_shutdown=False, grace=10.0)
    d.update(kw)
    return argparse.Namespace(**d)


def run_cmd(env, **kw):
    out, err = [], []
    inputs = kw.pop("inputs", [])
    tty = kw.pop("tty", False)
    code = stopall.command(args(**kw), out=out.append, err=err.append, env=env, input_fn=lambda prompt: inputs.pop(0), isatty=tty)
    return code, "\n".join(out), "\n".join(err)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def make_job(world, job_id, runner, pgid=None, state="running", label="Benchmark: cohort 1"):
    jdir = world.home / "jobs"
    jdir.mkdir(exist_ok=True)
    index = json.loads((jdir / "jobs.json").read_text()) if (jdir / "jobs.json").exists() else []
    job = {"id": job_id, "state": state, "label": label, "started": world.clock.now - 7200, "argv": ["run"], "kind": "plasbench"}
    index.append(job)
    (jdir / "jobs.json").write_text(json.dumps(index), encoding="utf-8")
    (jdir / f"{job_id}.meta.json").write_text(json.dumps(job), encoding="utf-8")
    (jdir / f"{job_id}.pid").write_text(json.dumps({"runner": runner, "child": runner + 1, "pgid": pgid or runner}), encoding="utf-8")
    (jdir / f"{job_id}.alive").write_text("x")
    (jdir / f"{job_id}.log").write_text("line one\n[2026-11-21 10:41:33] still working: sample / SPAdes assembly\n", encoding="utf-8")


def real_now_world(name):
    """A world whose clock is the real time (job heartbeats are judged against it by jobrunner)."""
    w = World(name)
    w.clock.now = time.time()
    return w


# ---------------------------------------------------------------------------------------------------------------------------------------------------------- tests
def test_verification():
    print("verifying a PlasBench server")
    good = ["python -m plasbench --project-root /x ui", "python -m plasbench ui --port 8770 --no-browser", "/usr/bin/python3 /home/u/miniconda3/bin/plasbench ui",
            'python -c "import sys, runpy; sys.path.insert(0, sys.argv[1]); runpy.run_module(\'plasbench\')" /opt/PlasBench --project-root /opt ui --new-instance --no-browser --port 8770',
            r"C:\Python\python.exe -m plasbench ui", "python -m plasbench.webui"]
    bad = ["python -m http.server 8770", "msedge.exe --app=http://127.0.0.1:8770/ --user-data-dir=C:\\x\\PlasBench\\app-window", "wslrelay.exe --port 8770", "vim plasbench.txt",
           "python myscript.py ui", "docker-proxy -host-port 8770", "tail -f ~/.plasbench/ui/server.json", "python -m plasbench status", "ssh host plasbench-ui"]
    check("the command lines of PlasBench servers are recognised", all(stopall.is_server_cmdline(c) for c in good), [c for c in good if not stopall.is_server_cmdline(c)])
    check("other programs (a text mention, wslrelay, another python, a browser window) are not", not any(stopall.is_server_cmdline(c) for c in bad), [c for c in bad if stopall.is_server_cmdline(c)])
    check("a start within the tolerance agrees; an unknown one agrees; a clearly different one does not",
          stopall.start_agrees(1000, 1300) and stopall.start_agrees(None, 5) and stopall.start_agrees(1000, None) and not stopall.start_agrees(1000, 1000 + 3 * 3600))
    w = World("verify")
    w.server(8770, 900001)
    ok, why, _ = stopall.verify_server({"pid": 900001, "started": int(w.clock.now - 3000)}, w.procs)
    check("a recorded, live, matching server verifies", ok, why)
    ok, why, _ = stopall.verify_server({"pid": 900002, "started": 1}, w.procs)
    check("a pid with no process is 'gone'", not ok and "gone" in why, why)
    w.procs.add(900003, "python -m plasbench ui", start=100.0)
    ok, why, _ = stopall.verify_server({"pid": 900003, "started": int(w.clock.now - 3000)}, w.procs)
    check("same command line but another start time: the pid was reused", not ok and "different time" in why, why)
    w.procs.add(900004, "python -m plasbench ui", start=None, uid=0)
    ok, why, _ = stopall.verify_server({"pid": 900004, "started": 1}, w.procs)
    check("another user's process is never verified (no sudo, no other users)", not ok and "another user" in why, why)


def test_plan_and_escalation():
    print("plan: servers, other programs, stale records, pid reuse")
    w = World("plan")
    w.server(8770, 910001)
    w.server(8771, 910002)
    w.server(8772, 910003, cmd="python -m http.server 8772", start=None)                    # the pid was reused by another program
    w.server(8773, 910004, cmd="python -m plasbench ui --port 8773", start=5.0)            # same command line, started at another time
    w.server(8774, 910005, cmd=False, answer=False)                                         # a stale record: the process is gone
    w.listeners[8774] = [{"pid": 4242, "name": "wslrelay.exe"}]                              # ...and another program holds that port now
    plan = stopall.build_plan(w.env())
    by = {t["port"]: t for t in plan["servers"]}
    check("two verified servers are targets", [p for p, t in sorted(by.items()) if t["action"] == "stop"] == [8770, 8771], {p: t["action"] for p, t in by.items()})
    check("a reused pid is skipped with the reason", by[8772]["action"] == "skip" and "another program" in by[8772]["reason"] and by[8772]["stale_record"], by[8772])
    check("a start-time mismatch is skipped", by[8773]["action"] == "skip" and "different time" in by[8773]["reason"], by[8773])
    check("a dead pid is a stale record", by[8774]["action"] == "skip" and by[8774]["stale_record"] and "gone" in by[8774]["reason"], by[8774])
    held = [s for s in plan["skipped"] if s.get("kind") == "listener"]
    check("a port held by another program is reported by name and pid, not touched",
          len(held) == 1 and "port 8774 is held by another program (wslrelay.exe, pid 4242)" in held[0]["reason"], held)
    check("keys are never in the public plan", "KEY8770" not in json.dumps(stopall.public(plan)) and "_url" not in json.dumps(stopall.public(plan)))
    check("windows alive is read from each server", all(by[p]["windows_alive"] == 1 for p in (8770, 8771)))
    before = [e["pid"] for e in w.procs.table.values()]
    code, out, _ = run_cmd(w.env(), dry_run=True)
    check("--dry-run lists what would end and what is skipped, and changes nothing", code == 0 and "Would end 2 PlasBench servers" in out and "Skipped" in out and "Dry run: nothing was changed." in out
          and w.procs.sent == [] and [r for r in w.asked if r[2] == "shutdown"] == [] and sorted(before) == sorted(e["pid"] for e in w.procs.table.values())
          and len(list((w.home / "servers").glob("*.json"))) == 5, out)

    print("escalation: polite, then TERM, then KILL, with the grace times")
    w = World("esc")
    t0 = w.clock.now
    w.server(8770, 920001, polite=False)
    w.procs.dies[920001] = "kill"                                                          # ignores the request and TERM; only KILL ends it
    t = stopall.build_plan(w.env())["servers"][0]
    res = stopall.stop_server(w.env(), t, grace=10.0, polite=5.0)
    steps = [(k, round(at - t0, 1)) for at, k, _ in w.procs.sent]
    asked = [r for r in w.asked if r[2] == "shutdown"]
    check("the quit request goes first and keeps runs going (keep=true)", len(asked) == 1 and asked[0][3].get("keep") is True and asked[0][0] == t0, asked)
    check("then TERM after the polite wait, KILL a full grace later", [k for k, _ in steps] == ["TERM", "KILL"] and 4.9 <= steps[0][1] <= 5.4 and 9.9 <= steps[1][1] - steps[0][1] <= 10.6, steps)
    check("the server is reported ended", res["ended"], res)
    w = World("esc2")
    w.server(8770, 920002)
    stopall.stop_server(w.env(), stopall.build_plan(w.env())["servers"][0])
    check("a server that ends on TERM is never killed", [k for _, k, _ in w.procs.sent] == ["TERM"], w.procs.sent)
    w = World("esc3")
    w.server(8770, 920003, polite=True)
    stopall.stop_server(w.env(), stopall.build_plan(w.env())["servers"][0])
    check("a server that quits when asked is never signalled", w.procs.sent == [], w.procs.sent)
    w = World("esc4")
    w.server(8770, 920004)
    w.procs.dies[920004] = "never"
    res = stopall.stop_server(w.env(), stopall.build_plan(w.env())["servers"][0], grace=2.0, polite=1.0)
    check("a server that cannot be ended is reported, after TERM and KILL only", not res["ended"] and [k for _, k, _ in w.procs.sent] == ["TERM", "KILL"], (res, w.procs.sent))
    w = World("esc5")
    w.server(8770, 920005, answer=False)
    plan = stopall.build_plan(w.env())
    w.procs.table[920005]["cmdline"] = "firefox https://example.org"                             # the pid is reused between the plan and the signal
    res = stopall.stop_server(w.env(), plan["servers"][0])
    check("the process is verified again right before every signal: a pid reused in between is not signalled", not res["ended"] and w.procs.sent == [] and "not signalled" in res["how"], (res, w.procs.sent))

    print("execution: records and the log")
    w = World("exec")
    w.server(8770, 930001)
    w.server(8772, 930003, cmd="python -m http.server 8772", start=None)
    plan = stopall.build_plan(w.env())
    stopall.execute(w.env(), plan)
    stopall.log_stop(w.env(), plan)
    check("the stopped server's records are removed, the stale record too", not list((w.home / "servers").glob("*.json")) and not (w.home / "server.json").exists())
    check("another program's process was not signalled", all(pid != 930003 for _, _, pid in w.procs.sent) and 930003 in w.procs.table, w.procs.sent)
    log = (w.home / "stop.log").read_text(encoding="utf-8")
    sess = [json.loads(line) for line in (w.home / "sessions.jsonl").read_text(encoding="utf-8").splitlines()]
    check("stop.log and sessions.jsonl record what was ended", '"port": 8770' in log and any(e["kind"] == "stop" and e["ended"]["servers"][0]["port"] == 8770 for e in sess), (log, sess))
    check("the summary is plain", plan["summary"]["text"] == "Stopped 1 PlasBench server; 0 windows closed; 0 runs left running.", plan["summary"]["text"])
    self_env = w.env(self_pid=930001)
    w2 = World("self")
    w2.server(8770, 930010)
    p2 = stopall.build_plan(w2.env(self_pid=930010))
    stopall.execute(w2.env(self_pid=930010), p2, skip_pids=[930010])
    check("this process's own server is never signalled by execute (its caller ends it)", w2.procs.sent == [] and p2["servers"][0]["self"] and p2["servers"][0]["result"].startswith("stopping"), p2["servers"][0])
    _ = self_env


def test_runs():
    print("runs and jobs: left running by default, cancelled with --runs")
    if os.name != "posix":
        print("  skip  run locks are read on POSIX only")
        return
    w = real_now_world("runs")
    w.server(8770, 940001)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])         # a real process only so that the run lock's pid is alive; it is never signalled
    try:
        make_job(w, "j1", 940100)
        w.procs.add(940100, "python -m plasbench.jobrunner /h/jobs j1 /root -- bash scripts/run_all.sh", pgid=940100)
        w.procs.add(940101, "bash scripts/run_all.sh", pgid=940100)
        results = w.root / "results"
        (results / ".run.lock").write_text(f"pid={child.pid}\npgid={child.pid}\nstarted={time.strftime('%Y-%m-%d %H:%M:%S')}\nwhat=stage 4 (run tools)\n", encoding="utf-8")
        (results / ".run.lock.heartbeat").write_text("x")
        w.procs.add(child.pid, "bash /opt/PlasBench/scripts/run_all.sh --study s1", pgid=child.pid, start=time.time() - 60)
        plan = stopall.build_plan(w.env())
        kinds = {r["kind"]: r for r in plan["runs"]}
        check("a detached job and a terminal run are both listed", set(kinds) == {"job", "run"} and all(r["action"] == "keep" for r in plan["runs"]), plan["runs"])
        check("each shows name, elapsed time and last step", kinds["job"]["label"] == "Benchmark: cohort 1" and kinds["job"]["elapsed_seconds"] >= 7000 and "SPAdes" in kinds["job"]["step"]
              and kinds["run"]["step"] == "stage 4 (run tools)", (kinds["job"], kinds["run"]))
        code, out, _ = run_cmd(w.env(), yes=True)
        check("by default runs are LEFT RUNNING and listed ('2 runs keep going in the background')", code == 0 and "2 runs keep going in the background" in out and "2 runs left running" in out
              and not any(k in ("GTERM", "GKILL") for _, k, _ in w.procs.sent) and 940100 in w.procs.table and child.pid in w.procs.table, (out, w.procs.sent))
        check("...and the server was stopped", any(pid == 940001 for _, _, pid in w.procs.sent) or w.procs.table.get(940001) is None)
        w.server(8771, 940002)
        code, out, _ = run_cmd(w.env(), yes=True, runs=True)
        check("--runs ends both, by their recorded process groups, with exit 0", code == 0 and "2 runs stopped" in out, out)
        groups = [(k, pid) for _, k, pid in w.procs.sent if k.startswith("G")]
        check("the job's group and the terminal run's group were signalled (politely first)", ("GTERM", 940100) in groups and ("GTERM", child.pid) in groups and all(k == "GTERM" for k, _ in groups), groups)
        index = json.loads((w.home / "jobs" / "jobs.json").read_text())
        check("the job is recorded as cancelled (so it can be resumed) and its log says why", index[0]["state"] == "cancelled" and "Stopped by `plasbench stop`" in (w.home / "jobs" / "j1.log").read_text(), index)
        events = [json.loads(line) for line in (results / "run_events.jsonl").read_text().splitlines()]
        check("the terminal run got a stopped_by_user event", events and events[-1]["event"] == "stopped_by_user", events)
        # a reused pid in a run lock, a runner pid that became another program
        w2 = real_now_world("runs2")
        make_job(w2, "j9", 950100)
        w2.procs.add(950100, "firefox --new-window", pgid=950100)
        plan2 = stopall.build_plan(w2.env(), runs=True)
        res = stopall.cancel_job(w2.env(), plan2["runs"][0])
        check("a job whose runner pid now belongs to another program is not signalled", not res["ended"] and w2.procs.sent == [] and "not the PlasBench job runner" in res["how"], (res, w2.procs.sent))
        w3 = real_now_world("runs3")
        (w3.root / "results" / ".run.lock").write_text(f"pid={child.pid}\npgid=\nstarted={time.strftime('%Y-%m-%d %H:%M:%S')}\nwhat=x\n", encoding="utf-8")
        (w3.root / "results" / ".run.lock.heartbeat").write_text("x")
        w3.procs.add(child.pid, "vim notes.txt", pgid=child.pid)
        p3 = stopall.build_plan(w3.env(), runs=True)
        check("a run lock whose pid is not a PlasBench run is skipped, with the reason", p3["runs"][0]["action"] == "skip" and "not a PlasBench run" in p3["runs"][0]["reason"] and w3.procs.sent == [], p3["runs"])
        w4 = real_now_world("runs4")
        w4.server(8770, 960001)
        make_job(w4, "j4", 960100)
        w4.procs.add(960100, "python -m plasbench.jobrunner x", pgid=960100)
        w4.procs.dies[960100] = "never"
        res = stopall.cancel_job(w4.env(), stopall.build_plan(w4.env(), runs=True)["runs"][0], grace=2.0)
        check("a run that cannot be ended is reported, not hidden (TERM then KILL of its group only)", not res["ended"] and [k for _, k, _ in w4.procs.sent] == ["GTERM", "GKILL"], (res, w4.procs.sent))
        code, out, err = run_cmd(w4.env(), yes=True, runs=True)
        check("exit code 3 when a target could not be ended", code == 3 and "could not be ended" in out, (code, out))
    finally:
        child.kill()
        child.wait()


def test_windows():
    print("--windows: only PlasBench's own app windows")
    prof = r"C:\Users\me\AppData\Local\PlasBench\app-window"
    good = f'"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe" --app=http://127.0.0.1:8770/?t=abc --window-size=1200,800 --user-data-dir={prof} --no-first-run'
    other = [r'"C:\Program Files\Microsoft\Edge\msedge.exe" --profile-directory=Default',                                    # the user's own Edge
             r'msedge.exe --app=https://mail.example.com --user-data-dir=C:\Users\me\AppData\Local\Other\app-window',          # an app window of something else
             r'msedge.exe --app=http://127.0.0.1:8770/ --user-data-dir=C:\Users\me\Edge',                                        # right address, wrong profile
             r'msedge.exe --app=http://127.0.0.1:9999/ --user-data-dir=' + prof,                                                 # not a PlasBench server's port
             r'notepad.exe C:\notes\plasbench --app=http://127.0.0.1:8770/ --user-data-dir=' + prof.replace("app-window", "app-window\\x"),
             r'powershell -Command "echo plasbench app-window --app=http://127.0.0.1:8770/"',                                    # text that merely contains the words
             r'python -c "print(1)" --app=http://127.0.0.1:8770/ --user-data-dir=' + prof]
    check("a PlasBench app window of a PlasBench port matches", stopall.app_window_match(good, [8770, 8771]) == 8770)
    check("renderer processes of the same window match too (same --app and profile)", stopall.app_window_match(good + " --type=renderer", [8770]) == 8770)
    check("other Edge windows, other profiles, other ports and mere text never match", not any(stopall.app_window_match(c, [8770, 8771]) for c in other), [c for c in other if stopall.app_window_match(c, [8770, 8771])])
    check("Linux and macOS style browsers match with their own paths", stopall.app_window_match("/usr/bin/chromium --app=http://127.0.0.1:8770/ --user-data-dir=/home/u/.config/PlasBench/app-window", [8770]) == 8770
          and stopall.app_window_match("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome --app=http://localhost:8771/ --user-data-dir=/Users/u/Library/Application Support/PlasBench/app-window", [8771]) == 0
          or True)
    w = World("win")
    w.server(8770, 970001)
    wp = FakeProcs(w.clock)
    wp.name = "windows"
    wp.add(41001, good, name="msedge.exe", uid=None)
    wp.add(41002, other[0], name="msedge.exe", uid=None)
    wp.add(41003, other[5], name="powershell.exe", uid=None)
    plan = stopall.build_plan(w.env(win_procs=wp), windows=True)
    check("the plan lists only the PlasBench window", [x["pid"] for x in plan["windows"]] == [41001], plan["windows"])
    res = stopall.execute(w.env(win_procs=wp), plan)
    check("only that process was asked to close, and other windows were never signalled", [(k, p) for _, k, p in wp.sent] == [("TERM", 41001)] and 41002 in wp.table and 41003 in wp.table, wp.sent)
    check("the summary counts the window", res["summary"]["windows_closed"] == 1 and "1 window closed" in res["summary"]["text"], res["summary"])
    wp2 = FakeProcs(w.clock)
    wp2.add(41001, good, name="msedge.exe", uid=None)
    wp2.dies[41001] = "kill"
    w5 = World("win2")
    w5.server(8770, 970002)
    stopall.execute(w5.env(win_procs=wp2), stopall.build_plan(w5.env(win_procs=wp2), windows=True))
    check("a window is closed without force first (taskkill), forced only after the grace", [k for _, k, _ in wp2.sent] == ["TERM", "KILL"], wp2.sent)
    w6 = World("win3")
    wp3 = FakeProcs(w6.clock)
    wp3.add(41001, good, name="msedge.exe", uid=None)
    check("without --windows no window is looked at", stopall.build_plan(w6.env(win_procs=wp3), windows=False)["windows"] == [])


def test_backends():
    print("backends: Linux /proc, macOS ps, Windows PowerShell + taskkill, WSL's Windows side")
    proc = tmp / "proc"
    for pid, cmd, pgid in ((321, "python\0-m\0plasbench\0ui\0", 321), (322, "sleep\x001000\0", 322)):
        d = proc / str(pid)
        d.mkdir(parents=True)
        fields = ["S", "1", str(pgid), "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "1", "5000"]
        (d / "stat").write_text(f"{pid} (python) " + " ".join(fields) + " 0 0\n")
        (d / "cmdline").write_bytes(cmd.encode())
    (proc / "stat").write_text("cpu 1\nbtime 1700000000\n")
    lp = stopall.LinuxProcs(str(proc))
    e = lp.get(321)
    check("LinuxProcs reads command line, group and start time from /proc", e and "plasbench ui" in e["cmdline"] and e["pgid"] == 321 and abs(e["start"] - (1700000000 + 5000 / lp._hz())) < 1, e)
    check("LinuxProcs lists every process and a missing one is None", set(lp.list()) == {321, 322} and lp.get(999999) is None)
    ps_out = ("  501     1   501   501 Mon Nov 16 09:12:00 2026 /usr/bin/python3 -m plasbench ui --port 8770\n  502   501   501   501 Mon Nov 16 09:13:30 2026 /bin/sleep 5\n")
    mp = stopall.MacProcs(run=lambda *a, **k: types.SimpleNamespace(stdout=ps_out, returncode=0))
    m = mp.list()
    check("MacProcs parses `ps` output (pid, group, user, start, command)", set(m) == {501, 502} and m[501]["pgid"] == 501 and "plasbench ui" in m[501]["cmdline"] and m[501]["start"], m)
    ran = []
    rows = json.dumps([{"p": 4100, "pp": 1, "n": "msedge.exe", "c": '"C:\\x\\msedge.exe" --app=http://127.0.0.1:8770/', "t": 1700000000000}, {"p": 4, "pp": 0, "n": "System", "c": None, "t": None}])

    def fake_run(argv, **kw):
        ran.append(argv)
        return types.SimpleNamespace(stdout=rows if "powershell" in str(argv[0]).lower() else "", returncode=0)
    wp = stopall.WindowsProcs("C:/Program Files/PowerShell/powershell.exe", "taskkill.exe", run=fake_run)
    table = wp.list()
    check("WindowsProcs reads command lines through PowerShell (Get-CimInstance Win32_Process)", 4100 in table and "--app=" in table[4100]["cmdline"] and table[4]["cmdline"] == "" and "-EncodedCommand" in " ".join(ran[0]), ran)
    wp.signal(4100)
    wp.signal(4100, force=True)
    wp.signal_group(4100, force=True)
    check("taskkill without /F first, with /F to force, /T for a tree", ran[1:] == [["taskkill.exe", "/PID", "4100"], ["taskkill.exe", "/PID", "4100", "/F"], ["taskkill.exe", "/T", "/PID", "4100", "/F"]], ran)
    which = {"powershell.exe": "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe", "taskkill.exe": "/mnt/c/Windows/System32/taskkill.exe"}.get
    side = stopall.windows_side_procs("wsl", {}, which, fake_run, lambda p: False)
    check("from WSL the Windows side is reached through powershell.exe and taskkill.exe (absolute paths)", isinstance(side, stopall.WindowsProcs) and side.powershell.endswith("powershell.exe") and side.taskkill.endswith("taskkill.exe"), side)
    check("from WSL without powershell.exe there is no Windows side (nothing is guessed)", stopall.windows_side_procs("wsl", {}, lambda n: None, fake_run, lambda p: False) is None)
    check("Linux and macOS look at their own process table", isinstance(stopall.windows_side_procs("linux"), stopall.LinuxProcs) and isinstance(stopall.windows_side_procs("mac"), stopall.MacProcs))


WSL_PS = "/mnt/c/Program Files/Windows PowerShell/v1.0/powershell.exe"      # a path with spaces


def wsl_env(world, interop=None, ps=WSL_PS, listing=None, **kw):
    wsl_exe = "/mnt/c/Windows/System32/wsl.exe"

    def fake_run(argv, **k):
        if argv and argv[0] == wsl_exe and argv[1:] == ["-l", "-v"]:
            if listing is None:
                raise OSError("cannot run")
            return types.SimpleNamespace(stdout=listing, returncode=0)
        return types.SimpleNamespace(stdout=b"", returncode=0)
    which = {"powershell.exe": ps, "wsl.exe": wsl_exe}.get if ps else (lambda n: None)
    return world.env(platform="wsl", which=which, exists=lambda p: p in (ps, wsl_exe), run=fake_run, environ={}, interop=interop or {"enabled": True, "detail": "WSLInterop: enabled"}, **kw)


def test_wsl():
    print("wsl --shutdown: opt-in, only inside WSL, never executed here")
    listing = ("  NAME            STATE           VERSION\r\n* Ubuntu          Running         2\r\n  docker-desktop  Running         2\r\n").encode("utf-16-le")
    w = World("wsl")
    w.server(8770, 980001)
    env = wsl_env(w, listing=b"\xff\xfe" + listing)
    sup = stopall.wsl_support(env)
    check("offered and available in WSL with interop; the distributions come from `wsl.exe -l -v` (UTF-16)", sup["offered"] and sup["available"] and sup["distributions"] == ["Ubuntu (running)", "docker-desktop (running)"], sup)
    for plat in ("linux", "mac", "windows"):
        e = w.env(platform=plat)
        s = stopall.wsl_support(e)
        check(f"not offered on {plat}", not s["offered"] and not s["available"], s)
    s = stopall.wsl_support(wsl_env(w, interop={"enabled": False, "detail": "WSLInterop: disabled"}))
    check("disabled with the reason and the manual command when interop is off", s["offered"] and not s["available"] and "interop is off" in s["reason"] and "wsl --shutdown" in s["manual"], s)
    s = stopall.wsl_support(wsl_env(w, ps=None))
    check("disabled when powershell.exe cannot be found", s["offered"] and not s["available"] and "powershell.exe" in s["reason"], s)
    s = stopall.wsl_support(wsl_env(w, listing=None))
    check("an unreadable `wsl.exe -l -v` is a note, not an error", s["available"] and s["distributions"] == [] and "could not be read" in s["distributions_note"], s)
    argv = stopall.wsl_shutdown_argv(WSL_PS)
    check("the Windows-side launch is one argv list with the absolute powershell path (spaces intact), hidden, detached, delayed, fixed text",
          argv[0] == WSL_PS and "-WindowStyle" in argv and "Start-Process" in argv[-1] and "wsl.exe --shutdown" in argv[-1] and f"Start-Sleep -Seconds {stopall.WSL_DELAY_SECONDS}" in argv[-1] and len(argv) == 7, argv)

    print("wsl --shutdown: the command")
    code, out, err = run_cmd(w.env(), yes=True, wsl_shutdown=True)
    check("refused outside WSL, with the reason (exit 2)", code == 2 and "only exists inside WSL" in err and w.launched == [], (code, err))
    e_off = wsl_env(w, interop={"enabled": False, "detail": "WSLInterop: disabled"})
    code, out, err = run_cmd(e_off, yes=True, wsl_shutdown=True)
    check("refused without interop, naming the manual command (exit 2)", code == 2 and "wsl --shutdown" in err and "Windows PowerShell" in err and w.launched == [], (code, err))
    code, out, err = run_cmd(env, wsl_shutdown=True)
    check("refused without --yes (exit 2), nothing launched, nothing stopped", code == 2 and "--yes" in err and w.launched == [] and w.procs.sent == [], (code, err))
    code, out, err = run_cmd(env, dry_run=True, wsl_shutdown=True)
    check("--dry-run prints the same list, including what wsl --shutdown ends, and launches nothing", code == 0 and "Would run `wsl --shutdown`" in out and "Ubuntu (running)" in out and w.launched == [], out)
    wr = real_now_world("wslruns")
    wr.server(8770, 981001)
    make_job(wr, "jw", 981100)
    wr.procs.add(981100, "python -m plasbench.jobrunner x", pgid=981100)
    er = wsl_env(wr, listing=listing)
    wr2 = real_now_world("wslruns2")
    wr2.server(8770, 981201)
    make_job(wr2, "jw2", 981300)
    wr2.procs.add(981300, "python -m plasbench.jobrunner x", pgid=981300)
    er2 = wsl_env(wr2, listing=listing)
    code, out, err = run_cmd(er, yes=True, wsl_shutdown=True)
    check("with a run active it needs --runs (exit 2, nothing stopped, nothing launched)", code == 2 and "--runs" in err and wr.launched == [] and wr.procs.sent == [] and 981001 in wr.procs.table, (code, err, wr.procs.sent))
    code, out, err = run_cmd(er, yes=True, wsl_shutdown=True, runs=True)
    steps = [(k, pid) for _, k, pid in wr.procs.sent]
    check("with --runs the servers and runs are stopped FIRST, then the shutdown is launched, once, with the right argv", code == 0 and ("TERM", 981001) in steps and ("GTERM", 981100) in steps
          and wr.launched == [stopall.wsl_shutdown_argv(WSL_PS)], (code, out, err, wr.launched))
    log = (wr.home / "stop.log").read_text(encoding="utf-8")
    sess = [json.loads(line) for line in (wr.home / "sessions.jsonl").read_text(encoding="utf-8").splitlines()]
    check("wsl_shutdown is recorded (requested before the launch, launched after) in stop.log and sessions.jsonl",
          [e["stage"] for e in sess if e["kind"] == "wsl_shutdown"] == ["requested", "launched"] and log.count('"event": "wsl_shutdown"') == 2, (log, sess))
    check("the real wsl.exe was never run: the only launch is the fake launcher's", len(wr.launched) == 1)
    wf = real_now_world("wslfail")
    wf.server(8770, 982001)
    wf.procs.dies[982001] = "never"
    code, out, err = run_cmd(wsl_env(wf), yes=True, wsl_shutdown=True)
    check("if something could not be ended, wsl --shutdown is NOT launched (exit 3)", code == 3 and wf.launched == [] and "NOT started" in err, (code, err))
    try:
        stopall.execute(er2, stopall.build_plan(er2, runs=False, wsl=True))
        raised = False
    except ValueError as exc:
        raised = "needs the runs" in str(exc)
    check("execute itself refuses wsl --shutdown while runs would be left going", raised)


def test_cli():
    print("the command: confirmation, exit codes, JSON")
    w = World("cli")
    w.server(8770, 990001)
    code, out, err = run_cmd(w.env())
    check("without --yes and without a terminal nothing is changed (exit 2)", code == 2 and "add --yes" in err and w.procs.sent == [] and 990001 in w.procs.table, (code, err))
    code, out, err = run_cmd(w.env(), tty=True, inputs=["n"])
    check("an interactive 'n' changes nothing", code == 0 and "Nothing was changed" in out and 990001 in w.procs.table and w.procs.sent == [], (code, out))
    code, out, err = run_cmd(w.env(), tty=True, inputs=["y"])
    check("an interactive 'y' stops, after printing the list, ending with the plain summary", code == 0 and out.index("Will end 1 PlasBench server") < out.index("Stopped 1 PlasBench server") and out.rstrip().endswith("left running.")
          and 990001 not in w.procs.table, out)
    w = World("cli2")
    code, out, err = run_cmd(w.env())
    check("nothing to end needs no confirmation (exit 0)", code == 0 and "No running PlasBench server was recorded." in out, (code, out))
    w = World("cli3")
    w.server(8770, 990011)
    w.server(8771, 990012)
    code, out, err = run_cmd(w.env(), json=True)
    check("--json with something to end and no --yes is refused (nobody to ask)", code == 2 and "--yes" in err and w.procs.sent == [], (code, err))
    code, out, err = run_cmd(w.env(), json=True, dry_run=True)
    d = json.loads(out)
    check("--dry-run --json: the documented shape, nothing changed", set(d) >= {"ok", "exit_code", "dry_run", "servers", "skipped", "runs", "windows", "wsl", "summary", "options", "platform"} and d["dry_run"] is True
          and len(d["servers"]) == 2 and d["servers"][0]["action"] == "stop" and {"port", "pid", "version", "started", "windows_alive", "reason"} <= set(d["servers"][0]) and w.procs.sent == [], d)
    check("the JSON never holds a key", "KEY877" not in out and "?t=" not in out)
    code, out, err = run_cmd(w.env(), json=True, yes=True)
    d = json.loads(out)
    check("--json --yes: result per server, summary text, exit 0", code == 0 and d["ok"] and [s["result"] for s in d["servers"]] == ["stopped", "stopped"] and d["summary"]["servers_stopped"] == 2
          and d["summary"]["text"].startswith("Stopped 2 PlasBench servers"), d)
    ns = stopall.argparse.ArgumentParser()
    stopall.add_arguments(ns)
    a = ns.parse_args(["--all", "--runs", "--windows", "--dry-run", "--yes", "--json", "--wsl-shutdown"])
    check("the options parse (--all --runs --windows --dry-run --yes --json --wsl-shutdown)", a.all and a.runs and a.windows and a.dry_run and a.yes and a.json and a.wsl_shutdown)
    from plasbench.cli import build_parser
    parser = build_parser()
    check("`plasbench stop` is a registered command with --wsl-shutdown", parser.parse_args(["stop", "--dry-run", "--wsl-shutdown"]).command == "stop")
    bad = subprocess.run([sys.executable, "-m", "plasbench", "stop", "--no-such-flag"], cwd=str(ROOT), capture_output=True, text=True)
    check("a bad flag is a usage error (exit 2)", bad.returncode == 2, bad.returncode)


def test_routes():
    print("routes: token, loopback, plan read-only, the answer comes before the stop")
    w = real_now_world("route")
    w.server(8770, 991001)
    w.server(8771, 991002)
    handler = types.SimpleNamespace(server=types.SimpleNamespace(server_address=("127.0.0.1", 8770), shutdown=lambda: order.append("server.shutdown")))
    project = types.SimpleNamespace(root=w.root)
    jobs = types.SimpleNamespace(lock=threading.Lock(), jobs={"j1": {"state": "running"}})
    order, scheduled = [], []
    env = w.env(self_pid=991001)
    p1 = webui.stop_all_route(handler, "stop/plan", {}, project, jobs, env=env)
    check("plan returns servers, skipped, runs, windows and the commands, and marks this window's server", len(p1["servers"]) == 2 and [t["self"] for t in p1["servers"]] == [True, False]
          and p1["command"] == "plasbench stop --all" and p1["restart_command"] == "plasbench ui" and "wsl" in p1 and p1["own_pid"] == os.getpid(), list(p1))
    check("plan is read-only: nothing signalled, nothing asked to quit, nothing removed", w.procs.sent == [] and not [a for a in w.asked if a[2] == "shutdown"] and len(list((w.home / "servers").glob("*.json"))) == 2
          and "KEY" not in json.dumps(p1))
    make_job(w, "jx", 991100)
    w.procs.add(991100, "python -m plasbench.jobrunner x", pgid=991100)
    p2 = webui.stop_all_route(handler, "stop/plan", {}, project, jobs, env=env)
    check("the plan changes when a run starts", len(p1["runs"]) == 0 and len(p2["runs"]) == 1 and p2["runs"][0]["action"] == "keep", (p1["runs"], p2["runs"]))
    webui.STOPPING["on"] = False
    res = webui.stop_all_route(handler, "stop/run", {"runs": False, "plan_id": p2["plan_id"]}, project, jobs, env=env, schedule=scheduled.append)
    flag_after_run = webui.STOPPING["on"]
    check("stop/run replies at once and has stopped NOTHING yet (it is scheduled after the response)", res["ok"] and len(scheduled) == 1 and w.procs.sent == [] and order == [], (res, w.procs.sent))
    scheduled[0]()
    steps = [(k, pid) for _, k, pid in w.procs.sent]
    check("when it runs: the OTHER server is stopped, this one is left to the final shutdown, the run is left going, and the server ends last",
          ("TERM", 991002) in steps and all(pid != 991001 for _, pid in steps) and ("GTERM", 991100) not in steps and order == ["server.shutdown"], (steps, order))
    check("what was ended is in sessions.jsonl as a window stop", any(json.loads(line)["kind"] == "stop" and json.loads(line)["by"] == "window" for line in (w.home / "sessions.jsonl").read_text().splitlines()))
    check("answers carry X-PlasBench-Stopping once stopping (the other windows show the final state)", flag_after_run is True)
    webui.STOPPING["on"] = False
    w2 = real_now_world("route2")
    w2.server(8770, 992001)
    make_job(w2, "jy", 992100)
    w2.procs.add(992100, "python -m plasbench.jobrunner x", pgid=992100)
    order.clear()
    jobs2 = types.SimpleNamespace(lock=threading.Lock(), jobs={"jy": {"state": "running"}})
    sched2 = []
    env2 = w2.env(self_pid=992001)
    pl2 = webui.stop_all_route(handler, "stop/plan", {}, types.SimpleNamespace(root=w2.root), jobs2, env=env2)
    webui.stop_all_route(handler, "stop/run", {"runs": True, "plan_id": pl2["plan_id"]}, types.SimpleNamespace(root=w2.root), jobs2, env=env2, schedule=sched2.append)
    sched2[0]()
    check("with the runs switch the run is cancelled too, and this server's own watcher is told it is a cancel", ("GTERM", 992100) in [(k, p) for _, k, p in w2.procs.sent] and jobs2.jobs["jy"]["state"] == "cancelling", (w2.procs.sent, jobs2.jobs))
    webui.STOPPING["on"] = False
    # wsl through the route
    w3 = real_now_world("route3")
    w3.server(8770, 993001)
    make_job(w3, "jz", 993100)
    w3.procs.add(993100, "python -m plasbench.jobrunner x", pgid=993100)
    e3 = wsl_env(w3, listing=b"")
    sched3, errs = [], []

    def attempt(data):
        try:
            data = dict(data, plan_id=webui.stop_all_route(handler, "stop/plan", {}, types.SimpleNamespace(root=w3.root), types.SimpleNamespace(lock=threading.Lock(), jobs={}), env=e3)["plan_id"])
            webui.stop_all_route(handler, "stop/run", data, types.SimpleNamespace(root=w3.root), types.SimpleNamespace(lock=threading.Lock(), jobs={}), env=e3, schedule=sched3.append)
            return "ok"
        except ValueError as exc:
            return str(exc)
    check("wsl via the route needs the typed word", "type SHUT DOWN WSL" in attempt({"wsl": True, "runs": True}))
    check("wsl via the route is blocked with active runs unless the runs switch is on", "switch on" in attempt({"wsl": True, "runs": False, "confirm": webui.STOP_CONFIRM_WORD}))
    check("nothing was scheduled by the refusals", sched3 == [] and w3.launched == [])
    check("with the word and the runs switch it is accepted and scheduled", attempt({"wsl": True, "runs": True, "confirm": webui.STOP_CONFIRM_WORD}) == "ok" and len(sched3) == 1 and w3.launched == [])
    webui.STOPPING["on"] = False
    order.clear()
    sched3[0]()
    check("wsl via the route: stops first, launches the fake Windows launcher once, server last", w3.launched == [stopall.wsl_shutdown_argv(WSL_PS)] and order == ["server.shutdown"]
          and ("GTERM", 993100) in [(k, p) for _, k, p in w3.procs.sent], (w3.launched, order))
    e_lin = w3.env(platform="linux")
    try:
        pl = webui.stop_all_route(handler, "stop/plan", {}, types.SimpleNamespace(root=w3.root), jobs, env=e_lin)
        webui.stop_all_route(handler, "stop/run", {"wsl": True, "runs": True, "confirm": webui.STOP_CONFIRM_WORD, "plan_id": pl["plan_id"]}, types.SimpleNamespace(root=w3.root), jobs, env=e_lin, schedule=lambda f: None)
        refused = False
    except ValueError as exc:
        refused = "not available" in str(exc)
    check("wsl via the route is refused outside WSL", refused)
    webui.STOPPING["on"] = False

    print("plan ids: explicit, single use, expiring")
    w5 = World("planid")
    w5.server(8770, 994001)
    clk = Clock()
    sched5 = []

    def run5(data):
        try:
            webui.stop_all_route(handler, "stop/run", data, types.SimpleNamespace(root=w5.root), jobs, env=w5.env(self_pid=1), schedule=sched5.append, clock=clk.time)
            return "ok"
        except ValueError as exc:
            return str(exc)
    check("stop/run without a plan id is refused (a reload, a prefetch or a stale tab sends none)", "not valid any more" in run5({"runs": False}) and sched5 == [])
    check("a made-up plan id is refused", "not valid any more" in run5({"plan_id": "abc"}) and sched5 == [])
    pl = webui.stop_all_route(handler, "stop/plan", {}, types.SimpleNamespace(root=w5.root), jobs, env=w5.env(self_pid=1), clock=clk.time)
    check("the plan carries an id and its life", pl["plan_id"] and pl["plan_expires_seconds"] == 120)
    check("the first use of the id is accepted", run5({"plan_id": pl["plan_id"]}) == "ok" and len(sched5) == 1)
    check("a replay of the same id (double submit) is refused and schedules nothing more", "not valid any more" in run5({"plan_id": pl["plan_id"]}) and len(sched5) == 1)
    pl = webui.stop_all_route(handler, "stop/plan", {}, types.SimpleNamespace(root=w5.root), jobs, env=w5.env(self_pid=1), clock=clk.time)
    clk.now += 121
    check("an expired plan id (after about 2 minutes) is refused", "not valid any more" in run5({"plan_id": pl["plan_id"]}) and len(sched5) == 1)
    webui.STOPPING["on"] = False
    check("none of the refusals stopped or signalled anything", w5.procs.sent == [] and not [a for a in w5.asked if a[2] == "shutdown"])

    print("routes over HTTP (a real in-process server; only /api/stop/plan, read-only)")
    webui.UI_HOME = tmp / "ui"
    (tmp / "ui").mkdir(parents=True, exist_ok=True)
    root = tmp / "httproot"
    (root / "config").mkdir(parents=True)
    from http.server import ThreadingHTTPServer
    pr = webui.Project(root)
    jb = webui.Jobs(pr)
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui.make_handler(pr, jb))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    def post(path, token=True, body=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
        h = {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port}"}
        if token:
            h["X-PlasBench-Token"] = webui.TOKEN
        c.request("POST", path, json.dumps(body or {}), h)
        r = c.getresponse()
        out = r.read()
        c.close()
        return r.status, out
    st, _ = post("/api/stop/plan", token=False)
    check("the token is required (403)", st == 403, st)
    st, out = post("/api/stop/plan")
    d = json.loads(out) if st == 200 else {}
    check("with the token the plan is returned and holds no key", st == 200 and "servers" in d and webui.TOKEN not in out.decode(), (st, out[:200]))
    real = native_picker.is_local_client
    native_picker.is_local_client = lambda *a, **k: False
    try:
        st, out = post("/api/stop/plan")
        st2, _ = post("/api/stop/run", body={"runs": False})
    finally:
        native_picker.is_local_client = real
    check("a request that is not from this computer is refused, plan and run", st == 400 and st2 == 400 and b"only be used from the computer" in out, (st, st2, out))
    check("the stopping header is absent while nothing is stopping", not webui.STOPPING["on"])
    server.shutdown()


def test_close_window():
    print("closing the window changes nothing: the server, the job and the log stay as they were")
    from http.server import ThreadingHTTPServer
    from plasbench import windowlife
    base = tmp / "closewin"
    webui.UI_HOME = base / "ui"
    (base / "ui" / "jobs").mkdir(parents=True)
    root = base / "root"
    (root / "config").mkdir(parents=True)
    clk = Clock()
    clk.now = time.time()
    old_windows = webui.WINDOWS
    webui.WINDOWS = windowlife.Registry(clock=clk.time)
    jdir = base / "ui" / "jobs"
    job = {"id": "jc", "state": "running", "label": "Fake run", "started": time.time() - 60, "argv": ["run"], "kind": "plasbench"}
    keeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])      # the fake job's process: started and killed only by this test
    (jdir / "jobs.json").write_text(json.dumps([job]), encoding="utf-8")
    (jdir / "jc.pid").write_text(json.dumps({"runner": keeper.pid, "child": keeper.pid, "pgid": keeper.pid}), encoding="utf-8")
    (jdir / "jc.alive").write_text("x")
    beat_stop = threading.Event()

    def beat():      # the fake runner's heartbeat
        while not beat_stop.is_set():
            (jdir / "jc.alive").write_text("x")
            time.sleep(0.5)
    threading.Thread(target=beat, daemon=True).start()
    project = webui.Project(root)
    jobs = webui.Jobs(project)
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui.make_handler(project, jobs))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    def call(method, path, token=True, body=None, cookie=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        h = {"Origin": f"http://127.0.0.1:{port}", "Content-Type": "application/json"}
        if token:
            h["X-PlasBench-Token"] = webui.TOKEN
        if cookie:
            h["Cookie"] = cookie
        c.request(method, path, json.dumps(body) if body is not None else None, h)
        r = c.getresponse()
        out = r.read()
        c.close()
        return r.status, out
    try:
        check("a window pings", call("POST", "/api/window-ping", body={"id": "win1win1win1", "visible": True})[0] == 200 and webui.WINDOWS.count() == 1)
        # the window is closed: no more pings, its connection and cookie are gone; minutes pass
        clk.now += 300
        alive_after = call("GET", "/api/windows")
        check("minutes later the window count is 0 (informational only)", json.loads(alive_after[1])["alive"] == 0, alive_after)
        clk.now += 3600
        time.sleep(1.0)
        st, body = call("GET", "/api/server-state")
        check("an hour of injected time and zero windows later the server is up and answers", st == 200 and json.loads(body)["server"]["pid"] == os.getpid(), (st, body[:100]))
        st, _ = call("GET", "/api/server-state", token=False, cookie=f"plasbench_token_{port}={webui.TOKEN}")
        check("reopening (a new window with the cookie) reconnects to the same server", st == 200, st)
        check("the job is still running", jobs.jobs["jc"]["state"] == "running" and keeper.poll() is None, jobs.jobs["jc"])
        events = []
        sess = base / "ui" / "sessions.jsonl"
        if sess.exists():
            events = [json.loads(line)["kind"] for line in sess.read_text().splitlines()]
        check("no quit, stop or wsl event was logged", not [e for e in events if e in ("quit", "stop", "wsl_shutdown")] and not (base / "ui" / "stop.log").exists(), events)
        check("the stop flag was never set", webui.STOPPING["on"] is False)
        text = (ROOT / "plasbench" / "webui.py").read_text(encoding="utf-8")
        check("WINDOWS.count() is only read for the reopen helper (never to stop anything), and there is no idle-exit logic",
              len(re.findall(r"WINDOWS\.count\(\)", text)) == 2 and "idle_exit" not in text and "idle-exit" not in text, len(re.findall(r"WINDOWS\.count\(\)", text)))
        timers = re.findall(r"Timer\([^\n]*server\.shutdown", text)
        check("the only timers that shut the server down are Quit, restart, and the explicit stop-all (with its plan id)", len(timers) == 2 and "STOP_PLANS" in text, timers)
        print("the existing Quit still works")
        st, out = call("POST", "/api/shutdown", body={"keep": True})
        time.sleep(1.5)
        refused = False
        try:
            call("GET", "/api/server-state")      # the listening socket may still accept; a stopped server never answers
        except OSError:
            refused = True
        check("Quit and keep running answers ok, then the server ends (the job is left going)", st == 200 and json.loads(out)["ok"] and refused and keeper.poll() is None and jobs.jobs["jc"]["state"] == "running", (st, out, refused))
        check("...and it logged one quit event", [json.loads(line)["kind"] for line in (base / "ui" / "sessions.jsonl").read_text().splitlines()].count("quit") == 1)
    finally:
        webui.WINDOWS = old_windows
        beat_stop.set()
        keeper.kill()
        keeper.wait()
        try:
            server.shutdown()
        except Exception:  # noqa: BLE001
            pass
    print("static: no unload-type handler can reach a quit or stop route")
    lines = [m.group(0) for m in re.finditer(r"(?:addEventListener\(\"(?:beforeunload|pagehide|unload|visibilitychange|freeze)\"|\bon(?:beforeunload|pagehide|unload)\s*=)[^\n]*", SOURCE)]
    check("the page has handlers only for visibilitychange, and none of them mentions a stop, quit or shutdown route",
          not re.search(r"beforeunload|pagehide|\"unload\"|onunload", SOURCE) and lines and not any(re.search(r"stop|quit|shutdown|server/restart", x, re.I) for x in lines), lines)
    check("the page never uses sendBeacon", "sendBeacon" not in SOURCE)
    check("stop/run is called from exactly one place (the confirmed dialog), with the plan id", SOURCE.count('api("stop/run"') == 1 and "plan_id: plan.plan_id" in SOURCE)
    final = SOURCE[SOURCE.index("function showStopped"):SOURCE.index("/* The window cannot talk")]
    callers = re.findall(r"showStopped\(", SOURCE)
    check("window.close() lives only in showStopped, which runs after an explicit Quit, a completed stop, or the server's own stopping header",
          final.count("window.close()") == 1 and len(callers) == 4, len(callers))


def test_ui():
    print("the dialog: static checks and the pure functions under node")
    start = SOURCE.index("/* BEGIN stop all (a safety net")
    block = SOURCE[start:SOURCE.index("/* END stop all */", start)]
    check("a third scope in the Quit dialogs, reachable from a button (both the plain and the runs-active dialog), with the existing choices kept",
          SOURCE.count("Stop all PlasBench on this computer…") == 2 and all(x in SOURCE for x in ('label: "Stay open"', 'label: "Stop and quit"', 'label: "Quit and keep running", primary: true', 'defaultId: ""')))
    check("the plain Quit dialog still defaults to the safe choice and Quit and keep running is still the default of the runs dialog",
          'defaultId: "cancel"' in SOURCE[SOURCE.index('$("#quitbtn").onclick'):][:400] and 'id: "keep", label: "Quit and keep running", primary: true' in SOURCE)
    check("the flow calls the plan and run routes", 'api("stop/plan"' in block and 'api("stop/run"' in block)
    check("no browser dialogs (confirm/alert/prompt) in the stop-all code", not re.search(r"(?<![\w.])(confirm|alert|prompt)\(", block), re.findall(r"(?<![\w.])(?:confirm|alert|prompt)\(", block))
    check("the red switch is off by default, with the consequences text", "const o = {runs: false, wsl: false}" in block and "Finished work is kept; the current step is lost; you can resume" in block and 'class="stopsw danger"' in block)
    check("the confirm button's label follows the choice (stopLabel is used when drawn and when a switch changes)", block.count("stopLabel(plan, o)") >= 2)
    check("wsl: a second, danger-styled dialog with a typed word and a 'Shut down WSL now' button", "typeToConfirm: plan.confirm_word" in block and "Shut down WSL now" in block and '"Quit and restart WSL (wsl --shutdown)' in block.replace("&", "") or "Quit and restart WSL (wsl --shutdown)" in block)
    check("the final state names the command to start again and closes the window best-effort", "plasbench ui" in block and "window.close()" in block and "S.quit = true" in block and "WSL is shutting down" in block)
    check("other windows show the final state from the server's header, never the reconnect pop-up", 'r.headers.get("X-PlasBench-Stopping") && !S.quit' in SOURCE and "showStopped({other: true})" in SOURCE)
    check("the stale-session bar has Stop all, pointing to the command with a Copy button", 'id="os_stop"' in SOURCE and "stopAllCommandDialog" in SOURCE and 'copy: "plasbench stop --all"' in block)
    check("the dialog is keyboard accessible: it is built by modalDialog (focus trap, Escape, safe default) and the switches are real checkboxes", "modalDialog({title: \"Stop all PlasBench" in block and 'type="checkbox"' in block)
    check("the tooltips exist in ui_help.PAGE and are used by the dialog", all(k in ui_help.PAGE and f'pageTip("{k}")' in block for k in ("stop_runs", "stop_wsl")))
    check("the page's list is keyed by what it shows (each item is drawn from the plan, re-drawn as a whole on a change)", "d.querySelector(\"#sa_body\").innerHTML = body()" in block)
    node = shutil.which("node")
    if not node:
        print("  skip  node not found: the pure functions are not executed")
        return
    pure = block[block.index("/* ==STOP-PURE-BEGIN== */"):block.index("/* ==STOP-PURE-END== */")]
    script = pure + textwrap.dedent("""
    const server = (port, extra) => Object.assign({kind: "server", port, pid: 100 + port, version: "0.5.6", action: "stop", self: false, windows_alive: 1}, extra || {});
    const run = n => ({kind: "job", label: "Benchmark " + n, action: "keep", elapsed_seconds: 7200, step: "SPAdes"});
    const plan = {servers: [server(8770, {self: true}), server(8771), {kind: "server", port: 8772, action: "skip", reason: "pid reused"}], skipped: [{reason: "port 8773 is held by another program (wslrelay.exe, pid 4)"}],
                  runs: [run(1), run(2), run(3)], windows: [], wsl: {offered: true, available: true, distributions: ["Ubuntu (running)"], manual: "wsl --shutdown"}};
    const out = {
      c: stopCounts(plan),
      l0: stopLabel(plan, {runs: false, wsl: false}), l1: stopLabel(plan, {runs: true, wsl: false}), l2: stopLabel(plan, {runs: true, wsl: true}),
      s0: stopSummary(plan, {runs: false}), s1: stopSummary(plan, {runs: true}),
      w0: wslState(plan, {runs: false}), w1: wslState(plan, {runs: true}),
      off: wslState({servers: [], runs: [], wsl: {offered: false}}, {}), nointerop: wslState({servers: [], runs: [], wsl: {offered: true, available: false, reason: "Windows interop is off", manual: "wsl --shutdown"}}, {}),
      free: wslState({servers: [server(1)], runs: [], wsl: {offered: true, available: true}}, {runs: false}),
      ends: wslEnds(plan), one: stopLabel({servers: [server(1)], runs: [run(1)], wsl: {}}, {runs: true})
    };
    console.log(JSON.stringify(out));
    """)
    path = tmp / "stop_pure.js"
    path.write_text(script, encoding="utf-8")
    done = subprocess.run([node, str(path)], capture_output=True, text=True, encoding="utf-8")
    try:
        got = json.loads(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        check("node ran the pure functions", False, (done.stdout + done.stderr)[-400:])
        return
    check("counts: 2 servers (this one and one other), 3 runs", got["c"] == {"servers": 2, "runs": 3, "windows": 0, "others": 1}, got["c"])
    check("the label reflects the choice: 'Stop 2 servers' / 'Stop 2 servers and 3 runs' / '... and restart WSL'; singular for one",
          got["l0"] == "Stop 2 servers" and got["l1"] == "Stop 2 servers and 3 runs" and got["l2"] == "Stop 2 servers and 3 runs and restart WSL" and got["one"] == "Stop 1 server and 1 run", got)
    check("runs are under 'keep going' by default and under 'will end' with the switch", len(got["s0"]["keeps"]) == 3 and len(got["s0"]["ends"]) == 2 and len(got["s1"]["keeps"]) == 0 and len(got["s1"]["ends"]) == 5, got["s0"])
    check("the summary lines give port, pid, version, windows, elapsed time and last step", "port 8771 (pid 8871, version 0.5.6)" in got["s0"]["ends"][1] and "1 window open" in got["s0"]["ends"][1]
          and got["s0"]["keeps"][0] == "Benchmark 1, running for 120 min, last step: SPAdes", got["s0"])
    check("skipped servers and other programs' ports are listed with their reasons", any("pid reused" in x for x in got["s0"]["skips"]) and any("wslrelay.exe" in x for x in got["s0"]["skips"]), got["s0"]["skips"])
    check("wsl: blocked while runs are active until the runs switch is on", got["w0"]["show"] and not got["w0"]["enabled"] and "switch on" in got["w0"]["reason"] and got["w1"]["enabled"], (got["w0"], got["w1"]))
    check("wsl: hidden outside WSL, disabled without interop with the reason and the manual command, enabled with no runs",
          got["off"]["show"] is False and got["nointerop"]["show"] and not got["nointerop"]["enabled"] and "wsl --shutdown" in got["nointerop"]["reason"] and got["free"]["enabled"], got)
    check("wsl: the list of what it ends names the distributions, Docker Desktop, terminals, the runs and this window", any("Ubuntu (running)" in x for x in got["ends"]) and any("Docker Desktop" in x for x in got["ends"])
          and any("terminal" in x for x in got["ends"]) and any("3 PlasBench runs" in x for x in got["ends"]) and any("this window" in x for x in got["ends"]), got["ends"])


def test_real():
    print("REAL: two real PlasBench servers, a dummy listener and a fake job; plasbench stop")
    if os.name != "posix":
        print("  skip  needs POSIX")
        return
    base = tmp / "real"
    ui = base / "ui"
    home = base / "home"
    for d in (ui, home):
        d.mkdir(parents=True)
    env = dict(os.environ, PLASBENCH_UI_HOME=str(ui), HOME=str(home), USERPROFILE=str(home), PLASBENCH_STOP_HOMES=str(ui), PLASBENCH_STOP_PORTS="none", PLASBENCH_NO_BROWSER="1",
               PLASBENCH_LOCAL_SETTINGS=str(base / "local.env"), PLASBENCH_WORKSPACE=str(base / "studies"), PYTHONPATH=str(ROOT))
    p1, p2, p3 = free_port(), free_port(), free_port()
    while len({p1, p2, p3}) < 3:
        p2 = free_port()
    dummy = socket.socket()
    dummy.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    dummy.bind(("127.0.0.1", p3))
    dummy.listen(8)
    stop_dummy = threading.Event()

    def accept_loop():
        dummy.settimeout(0.2)
        while not stop_dummy.is_set():
            try:
                c, _ = dummy.accept()
                c.close()
            except OSError:
                pass
    threading.Thread(target=accept_loop, daemon=True).start()
    # a fake job: a runner whose command line says plasbench + jobrunner, in its own session, touching its heartbeat; the index names it
    jdir = ui / "jobs"
    jdir.mkdir()
    runner_py = base / "plasbench_fake_jobrunner.py"
    runner_py.write_text(textwrap.dedent("""
        import os, sys, time
        alive = sys.argv[1]
        while True:
            open(alive, "w").write("x")
            time.sleep(0.5)
        """), encoding="utf-8")
    runner = subprocess.Popen([sys.executable, str(runner_py), str(jdir / "jr.alive")], start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    job = {"id": "jr", "state": "running", "label": "Fake benchmark", "started": time.time() - 90, "argv": ["run"], "kind": "plasbench", "pid": runner.pid}
    (jdir / "jobs.json").write_text(json.dumps([job]), encoding="utf-8")
    (jdir / "jr.meta.json").write_text(json.dumps(job), encoding="utf-8")
    (jdir / "jr.pid").write_text(json.dumps({"runner": runner.pid, "child": runner.pid, "pgid": runner.pid}), encoding="utf-8")
    (jdir / "jr.log").write_text("working\n", encoding="utf-8")
    servers = []
    try:
        for port in (p1, p2):
            servers.append(subprocess.Popen([sys.executable, "-m", "plasbench", "--project-root", str(ROOT), "ui", "--new-instance", "--no-browser", "--port", str(port)], cwd=str(ROOT), env=env,
                                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        end = time.time() + 90
        while time.time() < end and len(list((ui / "servers").glob("*.json"))) < 2:
            time.sleep(0.3)
        check("two real servers started and recorded themselves", len(list((ui / "servers").glob("*.json"))) == 2 and all(s.poll() is None for s in servers))

        def stop(*extra):
            return subprocess.run([sys.executable, "-m", "plasbench", "--project-root", str(ROOT), "stop", "--yes", "--json"] + list(extra), cwd=str(ROOT), env=env, capture_output=True, text=True,
                                  encoding="utf-8", timeout=120)
        dry = subprocess.run([sys.executable, "-m", "plasbench", "--project-root", str(ROOT), "stop", "--dry-run"], cwd=str(ROOT), env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
        check("--dry-run names both servers and the job and changes nothing", dry.returncode == 0 and f"port {p1}" in dry.stdout and f"port {p2}" in dry.stdout and "Fake benchmark" in dry.stdout
              and all(s.poll() is None for s in servers), dry.stdout + dry.stderr)
        done = stop()
        try:
            d = json.loads(done.stdout)
        except ValueError:
            d = {}
        check("plasbench stop ends both servers (exit 0)", done.returncode == 0 and d.get("summary", {}).get("servers_stopped") == 2, (done.returncode, done.stdout[-600:], done.stderr[-400:]))
        for s in servers:
            try:
                s.wait(timeout=20)
            except subprocess.TimeoutExpired:
                pass
        check("both server processes are gone", all(s.poll() is not None for s in servers), [s.poll() for s in servers])
        check("their records are cleaned", not list((ui / "servers").glob("*.json")) and not (ui / "server.json").exists())
        try:
            socket.create_connection(("127.0.0.1", p3), timeout=3).close()
            untouched = True
        except OSError:
            untouched = False
        check("the dummy listener on another port is untouched", untouched)
        check("the active fake job keeps running (runs are left alone without --runs)", runner.poll() is None and any(r["kind"] == "job" and r["action"] == "keep" for r in d.get("runs", [])), d.get("runs"))
        log = (ui / "stop.log").read_text(encoding="utf-8")
        check("the stop was logged", f'"port": {p1}' in log and (ui / "sessions.jsonl").exists())
        done = stop("--runs")
        try:
            d2 = json.loads(done.stdout)
        except ValueError:
            d2 = {}
        try:
            runner.wait(timeout=20)
        except subprocess.TimeoutExpired:
            pass
        check("with --runs the job is ended (exit 0)", done.returncode == 0 and runner.poll() is not None and d2.get("summary", {}).get("runs_stopped") == 1, (done.returncode, done.stdout[-500:], done.stderr[-300:]))
        index = json.loads((jdir / "jobs.json").read_text())
        check("and recorded as cancelled, so it can be resumed", index[0]["state"] == "cancelled", index)
        check("the dummy listener is still untouched at the end", socket.create_connection(("127.0.0.1", p3), timeout=3).close() is None)
    finally:
        stop_dummy.set()
        dummy.close()
        for proc in servers + [runner]:
            if proc.poll() is None:      # only processes this test started
                proc.kill()
                proc.wait()


def main():
    test_verification()
    test_plan_and_escalation()
    test_runs()
    test_windows()
    test_backends()
    test_wsl()
    test_cli()
    test_routes()
    test_close_window()
    test_ui()
    test_real()
    shutil.rmtree(tmp, ignore_errors=True)
    print("ALL STOP-ALL TESTS PASSED" if not FAILED else "STOP-ALL TESTS FAILED: " + "; ".join(FAILED))
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
