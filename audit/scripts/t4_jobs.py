import json, sys, time, urllib.request, uuid, psutil, os
SP = sys.argv[1]
info = json.load(open(f"{SP}/ui/uihome/server.json"))
BASE = f"http://127.0.0.1:{info['port']}"
TOKEN = info["url"].split("t=")[1]
def call(method, route, body=None):
    req = urllib.request.Request(f"{BASE}/api/{route}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"X-PlasBench-Token": TOKEN, "Content-Type": "application/json", "X-PlasBench-Req": uuid.uuid4().hex})
    try:
        with urllib.request.urlopen(req, timeout=60) as r: return json.loads(r.read())
    except urllib.error.HTTPError as e: return {"_http": e.code, "_body": e.read().decode()[:300]}
def procs(needle):
    out = []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            c = " ".join(p.info["cmdline"] or [])
            if needle in c and p.pid != os.getpid(): out.append((p.pid, p.info["name"], c[:110]))
        except Exception: pass
    return out

print("== T4a terminal route with token only (no browser):")
r = call("POST", "terminal/run", {"command": "echo AUDIT_PROBE"})
print("   ", {k: (str(v)[:80]) for k, v in r.items()})

print("== T4b start 'demo' job, poll state/progress")
job = call("POST", "jobs", {"argv": ["demo"], "label": "audit demo"})
jid = job.get("id") or job.get("job", {}).get("id")
print("   start ->", {k: job.get(k) for k in ("id", "state", "label")}, "jid", jid)
t0 = time.time(); last = None
while time.time() - t0 < 22:
    j = call("GET", f"jobs/{jid}?offset=0")
    rs = call("GET", "run-sessions")
    sess = [s for s in (rs.get("sessions") or rs if isinstance(rs, list) else rs.get("sessions", [])) if s.get("id") == jid]
    prog = sess[0].get("progress") if sess else None
    st = (j.get("job") or j).get("state")
    line = (st, json.dumps(prog)[:110] if prog else None)
    if line != last: print(f"   t+{time.time()-t0:4.1f}s state={st} progress={line[1]}"); last = line
    time.sleep(2)

print("== T4c cancel")
t1 = time.time(); c = call("POST", f"jobs/{jid}/cancel", {})
print("   cancel response state:", (c.get("job") or c).get("state"))
for _ in range(40):
    j = call("GET", f"jobs/{jid}?offset=0"); st = (j.get("job") or j).get("state")
    if st not in ("cancelling", "running"): break
    time.sleep(1)
print(f"   final state={st} after {time.time()-t1:.1f}s")
time.sleep(3)
left = procs("run_demo") + procs("demo_dataset") + procs("score_plasmids") + procs("jobrunner")
print("   leftover processes after cancel:", len(left))
for p in left[:8]: print("     ", p)
