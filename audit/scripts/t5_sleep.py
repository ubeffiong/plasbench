import json, sys, time, urllib.request, uuid, psutil, os
SP = sys.argv[1]
info = json.load(open(f"{SP}/ui/uihome/server.json"))
BASE = f"http://127.0.0.1:{info['port']}"; TOKEN = info["url"].split("t=")[1]
def call(method, route, body=None):
    req = urllib.request.Request(f"{BASE}/api/{route}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"X-PlasBench-Token": TOKEN, "Content-Type": "application/json", "X-PlasBench-Req": uuid.uuid4().hex})
    try:
        with urllib.request.urlopen(req, timeout=60) as r: return json.loads(r.read())
    except urllib.error.HTTPError as e: return {"_http": e.code, "_body": e.read().decode()[:300]}
def state(jid):
    j = call("GET", f"jobs/{jid}?offset=0"); return (j.get("job") or j).get("state")
def runners(jid):
    out = []
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            c = " ".join(p.info["cmdline"] or [])
            if "plasbench.jobrunner" in c and jid in c: out.append(p)
        except Exception: pass
    return out

job = call("POST", "jobs", {"argv": ["demo"], "label": "audit sleep test"}); jid = job["id"]
print("started", jid, job["state"]); time.sleep(6)
rs = runners(jid); print("runner processes:", [p.pid for p in rs])
t0 = time.time()
for p in rs:
    for ch in p.children(recursive=True) + [p]:
        try: ch.suspend()
        except Exception as e: print("suspend err", e)
print("suspended runner + children (simulates laptop sleep)")
seen = []
while time.time() - t0 < 34:
    s = state(jid)
    if not seen or seen[-1][1] != s: seen.append((round(time.time() - t0, 1), s)); print(f"   t+{seen[-1][0]}s state={s}")
    time.sleep(2)
for p in rs:
    for ch in p.children(recursive=True) + [p]:
        try: ch.resume()
        except Exception as e: print("resume err", e)
print("resumed processes; runner alive:", all(p.is_running() for p in rs))
t1 = time.time()
while time.time() - t1 < 14:
    s = state(jid)
    if seen[-1][1] != s: seen.append((round(time.time() - t0, 1), s)); print(f"   t+{seen[-1][0]}s state={s}")
    time.sleep(2)
print("state 14 s after the runner resumed:", state(jid), "| runner still running:", any(p.is_running() for p in rs))
r = call("POST", f"jobs/{jid}/resume", {})
print("POST resume while the ORIGINAL runner is alive ->", json.dumps(r)[:200])
time.sleep(4)
alive = [p for p in psutil.process_iter(["pid", "cmdline"]) if "plasbench.jobrunner" in " ".join(p.info["cmdline"] or [])]
print("jobrunner processes now:", len(alive), [p.pid for p in alive])
# cleanup: cancel everything we started
for j in (call("GET", "jobs").get("jobs") or []):
    if j.get("state") in ("running", "interrupted"): call("POST", f"jobs/{j['id']}/cancel", {})
time.sleep(25)
print("after cleanup, jobrunner processes:", len([p for p in psutil.process_iter(["cmdline"]) if "plasbench.jobrunner" in " ".join(p.info["cmdline"] or [])]))
