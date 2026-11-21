#!/usr/bin/env python3
"""The Docker engine pre-flight (plasbench/docker_health.py), the pull and build decisions (docker_runtime.ensure_image / execute), `plasbench runtime doctor`, and the window's
Docker health block, all against a scripted FAKE docker: an in-process fake everywhere, and a real `docker` executable on PATH (a script that records every call and returns the
scripted output and exit code) where the system can run one (Linux, macOS; the Windows computer of the developer cannot run an extensionless script, CI does).

NOTE ON THE FIXTURES: the exact messages of the failure seen on a production server (the corrupted layer, the read-only metadata database) are used as they were printed; every other
engine message is a SAMPLE WRITTEN FROM KNOWLEDGE of docker's formats, not a captured log. Nothing here needs a real engine: test_docker_runtime_e2e.py runs `runtime doctor` against
the real Docker of the CI runner.
"""
import inspect
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import threading
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from plasbench import __version__, docker_health as dh, docker_runtime as dr, loadcache  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


PROD_PULL = ('failed to extract layer (application/vnd.oci.image.layer.v1.tar+gzip sha256:2ed1956c) to overlayfs as "extract-349721246-tNeu sha256:3f5380d7": exit status 1: '
             'unpigz: skipping: <stdin>: corrupted -- incomplete deflate data')
PROD_RO = 'ERROR: failed to build: failed to solve: write /var/lib/desktop-containerd/daemon/io.containerd.metadata.v1.bolt/meta.db: read-only file system'
RO_VOLUME = 'Error response from daemon: write /var/lib/docker/volumes/metadata.db: read-only file system'
INFO = {"DockerRootDir": "/var/lib/docker", "Driver": "overlay2", "OperatingSystem": "Ubuntu 22.04.4 LTS", "ServerVersion": "26.1.0", "MemTotal": 8 * 2 ** 30,
        "HttpProxy": "", "HttpsProxy": "", "NoProxy": "", "SecurityOptions": ["name=seccomp,profile=builtin"], "Warnings": []}


def respond(args, scenario, counts):
    """The fake docker: (exit code, output) of one command line. `scenario` maps a command ("pull", "volume create", "info", ...) to a list of {code, out}; each call takes the next one and
    the last repeats. Unlisted commands answer like a healthy engine. This function is also the body of the fake `docker` executable (its source is copied into the script)."""
    two = " ".join(args[:2])
    key = two if two in scenario else (args[0] if args and args[0] in scenario else None)
    if key is None:
        defaults = {"version": (0, "26.1.0|amd64|26.1.0"), "info": (0, json.dumps({"DockerRootDir": "/var/lib/docker", "Driver": "overlay2", "OperatingSystem": "Ubuntu 22.04.4 LTS",
                                                                                       "ServerVersion": "26.1.0", "MemTotal": 8 * 2 ** 30, "SecurityOptions": []})),
                    "volume create": (0, args[-1] if args else ""), "volume rm": (0, args[-1] if args else ""), "image inspect": (1, "Error response from daemon: No such image: " + (args[2] if len(args) > 2 else "")),
                    "pull": (0, "Status: Downloaded newer image"), "build": (0, "naming to docker.io/library/x"), "buildx version": (0, "github.com/docker/buildx v0.1"), "run": (0, "ok"), "stop": (0, "x")}
        return defaults.get(two) or defaults.get(args[0] if args else "") or (0, "")
    seq = scenario[key]
    n = counts.get(key, 0)
    counts[key] = n + 1
    step = seq[min(n, len(seq) - 1)]
    return step["code"], step.get("out", "")


FAKE_SCRIPT = ("#!/usr/bin/env python3\nimport json, os, sys\n" + inspect.getsource(respond) + '''

def main():
    args = sys.argv[1:]
    scenario = json.load(open(os.environ["FAKE_DOCKER_SCENARIO"]))
    cfile = os.environ["FAKE_DOCKER_LOG"] + ".count"
    try:
        counts = json.load(open(cfile))
    except (OSError, ValueError):
        counts = {}
    with open(os.environ["FAKE_DOCKER_LOG"], "a") as handle:
        handle.write(json.dumps(args) + "\\n")
    code, out = respond(args, scenario, counts)
    json.dump(counts, open(cfile, "w"))
    sys.stdout.write(out + "\\n")
    sys.exit(code)


main()
''')


class Fake:
    """The in-process fake: the same `respond` as the executable, with the calls recorded."""

    def __init__(self, scenario=None, images=()):
        self.scenario, self.counts, self.calls, self.images = scenario or {}, {}, [], set(images)

    def run(self, argv, timeout=20, env=None):
        self.calls.append(list(argv))
        a = argv[1:]
        if a[:2] == ["image", "inspect"] and "image inspect" not in self.scenario:
            return (0, "sha256:abc|1073741824|2026-01-01T00:00:00Z|1") if a[2] in self.images else (1, "Error response from daemon: No such image")
        if a[:1] == ["run"] and a[-2:] == ["plasbench", "--version"]:
            return 0, f"plasbench {__version__}"
        return respond(a, self.scenario, self.counts)

    def stream(self, argv, env=None, out=None, heartbeat=30.0, what=""):
        self.calls.append(list(argv))
        code, text = respond(argv[1:], self.scenario, self.counts)
        if code == 0 and argv[1] == "pull":
            self.images.add(argv[2])
        if code == 0 and argv[1] == "build":
            self.images.add(argv[argv.index("-t") + 1])
        return code, text.splitlines()

    def kinds(self):
        return [" ".join(c[1:3]) if c[1] in ("volume", "image", "buildx") else c[1] for c in self.calls]


def seq(*steps):
    return [{"code": c, "out": o} for c, o in steps]


def main():
    tmp = Path(tempfile.mkdtemp(prefix="pbhealth"))
    root = tmp / "proj"
    (root / "config").mkdir(parents=True)
    (root / "Dockerfile").write_text("FROM x\nRUN micromamba create -n a\nRUN micromamba create -n b\nRUN micromamba create -n c\n", encoding="utf-8")
    (root / "config" / "config.sh").write_text('export THREADS\nexport DATA_DIR="${DATA_DIR:-x}"\n', encoding="utf-8")
    env0 = {"HOME": str(tmp / "home"), "PLASBENCH_UI_HOME": str(tmp / "ui"), "PLASBENCH_DOCKER_PULL_BACKOFF": "0"}
    os.makedirs(env0["HOME"], exist_ok=True)
    LINUX = {"kind": "linux", "systemd": True}

    print("health pre-flight: the healthy path")
    f = Fake()
    r = dh.check(root, purpose="pull", run=f.run, exe="docker", environ=env0, environment=LINUX)
    check("healthy: every check passes, in order", r["healthy"] and [c["name"] for c in r["checks"]][:3] == ["Docker command", "Engine answers", "Engine details (docker info)"], [c["name"] for c in r["checks"]])
    check("it asked docker version, docker info, then created and removed ONE test volume", f.kinds().count("version") == 1 and f.kinds().count("info") == 1 and f.kinds().count("volume create") == 1 and f.kinds().count("volume rm") == 1, f.kinds())
    made = [c for c in f.calls if c[1:3] == ["volume", "create"]][0][-1]
    gone = [c for c in f.calls if c[1:3] == ["volume", "rm"]][0][-1]
    check("the test volume has a unique pb-health- name and the same one is removed", re.fullmatch(r"pb-health-[0-9a-f]{8}", made) and made == gone, (made, gone))
    check("no pull, build or container run: nothing uses the network and nothing is started", not set(f.kinds()) & {"pull", "build", "run"}, f.kinds())
    check("facts are read from docker info", r["info"]["root_dir"] == "/var/lib/docker" and r["info"]["driver"] == "overlay2" and r["info"]["server_version"] == "26.1.0" and r["info"]["mem_gb"] == 8.0)
    check("result shape: healthy, checks, diagnosis, info, environment, warnings, plan, seconds", set(r) >= {"healthy", "purpose", "checks", "diagnosis", "info", "environment", "warnings", "plan", "seconds"} and r["diagnosis"] is None)
    check("a healthy engine's plan says there is nothing to fix", r["plan"] and "Nothing to fix" in r["plan"][0])
    check("each check carries name, ok, warn, detail, advice, commands", all({"name", "ok", "warn", "detail", "advice", "commands"} <= set(c) for c in r["checks"]))

    print("health pre-flight: the production failure (read-only metadata)")
    f = Fake({"volume create": seq((1, PROD_RO))})
    r = dh.check(root, purpose="pull", run=f.run, exe="docker", environ=env0, environment={"kind": "wsl2", "desktop_installed": True})
    bad = [c for c in r["checks"] if not c["ok"]]
    check("unhealthy: the write test failed with a classified diagnosis", not r["healthy"] and len(bad) == 1 and bad[0]["name"].startswith("Engine can write") and r["diagnosis"]["cause"] == "read_only_filesystem", r["diagnosis"] and r["diagnosis"]["cause"])
    check("engine_unhealthy, Desktop advice (wsl --shutdown), environment recognised", r["diagnosis"]["engine_unhealthy"] and "wsl --shutdown" in r["diagnosis"]["commands"] and r["environment"] == "desktop_windows")
    check("a failed create leaves nothing to remove: no `volume rm`", "volume rm" not in f.kinds())
    out = []
    dh.explain(r, out.append)
    text = "\n".join(out)
    check("explain(): says what is wrong, the evidence, steps, commands, and that nothing was pulled or built", "Docker is not healthy" in text and "meta.db" in text and "wsl --shutdown" in text and "Nothing was pulled or built" in text)
    check("explain(): last resorts carry their consent text", "Last resort only" in text and "WARNING:" in text)
    rendered = dh.render(r)
    check("render(): FAIL line with evidence, the result, numbered next steps", "FAIL  Engine can write" in rendered and "PROBLEMS FOUND" in rendered and "Next steps" in rendered and "  1. " in rendered)

    print("health pre-flight: an engine that does not answer, and a missing docker")
    f = Fake({"version": seq((1, "Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?"))})
    r = dh.check(root, purpose="run", run=f.run, exe="docker", environ=env0, environment=LINUX)
    check("daemon stopped: classified, later steps are not attempted", not r["healthy"] and r["diagnosis"]["cause"] == "daemon_stopped" and f.kinds() == ["version"], f.kinds())
    f = Fake({"version": seq((124, "docker did not answer in time"))})
    r = dh.check(root, purpose="run", run=f.run, exe="docker", environ=env0, environment=LINUX)
    check("a timeout is a hung engine (exit 124 text), not a guess", not r["healthy"] and r["diagnosis"]["cause"] == "engine_timeout")
    r = dh.check(root, purpose="run", run=Fake().run, exe="", environ=env0, environment=LINUX)
    check("docker missing: the first check fails with install advice and no process is started", not r["healthy"] and r["checks"][0]["name"] == "Docker command" and any("install" in a.lower() for a in r["checks"][0]["advice"]) and len(r["checks"]) == 1)
    f = Fake({"info": seq((1, "Error response from daemon: " + RO_VOLUME))})
    r = dh.check(root, purpose="run", run=f.run, exe="docker", environ=env0, environment=LINUX)
    check("docker info failing is classified too", not r["healthy"] and r["diagnosis"]["cause"] == "read_only_filesystem" and "volume create" not in f.kinds())
    f = Fake({"volume create": seq((1, "something docker never said before"))})
    r = dh.check(root, purpose="run", run=f.run, exe="docker", environ=env0, environment=LINUX)
    check("an UNKNOWN write failure still blocks (unhealthy) and is said to be unknown", not r["healthy"] and r["diagnosis"]["cause"] == "unknown" and "unexpected answer" in [c for c in r["checks"] if not c["ok"]][0]["detail"])
    f = Fake({"volume rm": seq((1, "Error: volume is in use"))})
    r = dh.check(root, purpose="run", run=f.run, exe="docker", environ=env0, environment=LINUX)
    check("a test volume that cannot be removed is a NOTE with the command, not a failure", r["healthy"] and any(c["warn"] and "docker volume rm pb-health-" in c["detail"] for c in r["checks"]))

    print("health pre-flight: time budget")
    ticks = iter(range(0, 1000, 20))
    r = dh.check(root, purpose="pull", run=Fake().run, exe="docker", environ=env0, environment=LINUX, budget=15.0, clock=lambda: next(ticks))
    check("when the budget is used up the remaining steps are skipped with a note, never hang", any("skipped" in c["detail"] for c in r["checks"]), [c["detail"] for c in r["checks"]])
    seen = []

    def slow(argv, timeout=20, env=None):
        seen.append(timeout)
        return Fake().run(argv, timeout, env)
    dh.check(root, purpose="pull", run=slow, exe="docker", environ=env0, environment=LINUX)
    check("every docker command has its own timeout (never more than 10 s in the pre-flight)", seen and max(seen) <= 10.0, seen)

    print("free disk space")
    GB = 2 ** 30

    class VFS:
        def __init__(self, gb):
            self.f_bavail, self.f_frsize = int(gb * GB), 1

    def vfs(gb, deny=()):
        def f(path):
            if path in deny:
                raise PermissionError(path)
            return VFS(gb)
        return f
    for gb, ok, warn in ((50, True, False), (5, True, True), (1.0, False, False)):
        r = dh.check(root, purpose="pull", run=Fake().run, exe="docker", environ=env0, environment=LINUX, statvfs=vfs(gb), local=True)
        row = [c for c in r["checks"] if c["name"] == "Free disk space for Docker"][0]
        check(f"{gb} GB free for a pull: ok={ok} warn={warn} healthy={ok}", (row["ok"], row["warn"]) == (ok, warn) and r["healthy"] == ok, row)
    r = dh.check(root, purpose="pull", run=Fake().run, exe="docker", environ=env0, environment=LINUX, statvfs=vfs(1.0), local=True)
    check("below 2 GB: blocked with the no_space diagnosis, the number, and the commands", r["diagnosis"]["cause"] == "no_space" and "1.0 GB" in r["diagnosis"]["title"] and "df -h /var/lib/docker" in r["diagnosis"]["commands"])
    r = dh.check(root, purpose="build", run=Fake().run, exe="docker", environ=env0, environment=LINUX, statvfs=vfs(8), local=True)
    row = [c for c in r["checks"] if c["name"] == "Free disk space for Docker"][0]
    check("a build below its estimate warns and says 'estimated' from the Dockerfile's 3 conda environments (3 + 3 x 3 = 12 GB)", row["ok"] and row["warn"] and "about 12 GB" in row["detail"] and "estimated from the 3 conda environments" in row["detail"], row["detail"])
    r = dh.check(root, purpose="run", run=Fake().run, exe="docker", environ=env0, environment=LINUX, statvfs=vfs(0.1), local=True)
    check("a plain run does not block on free space (only pull and build do)", r["healthy"] and not [c for c in r["checks"] if c["name"].startswith("Free disk")])
    r = dh.check(root, purpose="pull", run=Fake().run, exe="docker", environ=env0, environment=LINUX, statvfs=vfs(30, deny=("/var/lib/docker",)), local=True)
    row = [c for c in r["checks"] if c["name"] == "Free disk space for Docker"][0]
    check("Docker's own folder is root-only: the parent on the same disk is measured and said so", row["ok"] and "/var/lib" in row["detail"] and "same disk" in row["detail"], row["detail"])
    desktop = Fake({"info": seq((0, json.dumps(dict(INFO, OperatingSystem="Docker Desktop", DockerRootDir="/var/lib/desktop-containerd/daemon"))))})
    r = dh.check(root, purpose="pull", run=desktop.run, exe="docker", environ=env0, environment={"kind": "windows"}, statvfs=vfs(0.5))
    row = [c for c in r["checks"] if c["name"] == "Free disk space for Docker"][0]
    check("Docker Desktop's disk is inside its VM: not measured from here (no false number), pointed to Settings", r["healthy"] and "not measured" in row["detail"] and "Settings" in row["detail"] and r["environment"] == "desktop_windows")

    print("proxies are printed, secrets are not")
    pinfo = dict(INFO, HttpProxy="http://user:hunter2@proxy.example:3128", HttpsProxy="http://proxy.example:3128", NoProxy="localhost")
    r = dh.check(root, purpose="run", run=Fake({"info": seq((0, json.dumps(pinfo)))}).run, exe="docker", environ=dict(env0, HTTPS_PROXY="http://u:pw@corp:8080"), environment=LINUX)
    blob = json.dumps(r)
    check("a proxy is a NOTE that warns proxies corrupt layers", any(c["name"] == "Proxy" and c["warn"] and "corrupt" in c["detail"] for c in r["checks"]) and "proxy.example:3128" in blob)
    check("passwords in proxy addresses are masked everywhere (docker's and the shell's)", "hunter2" not in blob and "pw@" not in blob and "***" in blob and "hunter2" not in dh.render(r))
    check("the shell's proxy variables are listed too", r["info"]["proxies"]["client"] == {"HTTPS_PROXY": "http://u:***@corp:8080"})
    check("plain-text `docker info` is parsed as well", dh.parse_info("Server Version: 24.0.7\n Storage Driver: overlay2\n Docker Root Dir: /var/lib/docker\n HTTP Proxy: http://p:1\n")["root_dir"] == "/var/lib/docker")

    print("doctor: a container start only with a local image, and never a pull")
    f = Fake(images={"img:1"})
    r = dh.check(root, purpose="doctor", run=f.run, exe="docker", environ=env0, environment=LINUX, image="img:1", statvfs=vfs(100), local=True)
    started = [c for c in f.calls if c[1] == "run"]
    check("with the image local: `docker run --rm --pull=never IMAGE true`", len(started) == 1 and started[0][1:] == ["run", "--rm", "--pull=never", "img:1", "true"], started)
    f = Fake()
    r = dh.check(root, purpose="doctor", run=f.run, exe="docker", environ=env0, environment=LINUX, image="img:1", statvfs=vfs(100), local=True)
    check("without the image: skipped with a note, no run, no pull", "run" not in f.kinds() and "pull" not in f.kinds() and any("skipped" in c["detail"] for c in r["checks"] if c["name"].startswith("A container starts")))
    f = Fake({"run": seq((125, "docker: Error response from daemon: failed to mount overlay: invalid argument"))}, images={"img:1"})
    r = dh.check(root, purpose="doctor", run=f.run, exe="docker", environ=env0, environment=LINUX, image="img:1", statvfs=vfs(100), local=True)
    check("a container that cannot start is classified (storage driver)", not r["healthy"] and r["diagnosis"]["cause"] == "storage_driver")

    print("cache (30 s), switch, record")
    loadcache.reset_all()
    dh.forget()
    calls = []
    real_check, real_exe = dh.check, dr.docker_exe
    dh.check = lambda *a, **k: calls.append(1) or {"healthy": True, "checks": [], "diagnosis": None}
    dr.docker_exe = lambda which=None: "docker"
    try:
        dh.cached(root, purpose="run")
        dh.cached(root, purpose="run")
        check("the same real-docker check within 30 s is answered from memory", len(calls) == 1)
        dh.cached(root, purpose="pull")
        check("another purpose is its own entry", len(calls) == 2)
        dh.forget()
        dh.cached(root, purpose="run")
        check("forget() empties it", len(calls) == 3)
        dh.cached(root, purpose="run", run=Fake().run, exe="docker", environ=env0)
        dh.cached(root, purpose="run", run=Fake().run, exe="docker", environ=env0)
        check("a fake docker is never cached (tests see every call)", len(calls) == 5)
    finally:
        dh.check, dr.docker_exe = real_check, real_exe
    check("PLASBENCH_DOCKER_HEALTH=off switches the pre-flight off, anything else leaves it on", not dh.enabled({"PLASBENCH_DOCKER_HEALTH": "off"}) and dh.enabled({}) and dh.enabled({"PLASBENCH_DOCKER_HEALTH": "on"}))
    check("PLASBENCH_DOCKER_PULL_RETRIES: default 2, 0 to 5, garbage -> 2", (dh.retries({}), dh.retries({"PLASBENCH_DOCKER_PULL_RETRIES": "0"}), dh.retries({"PLASBENCH_DOCKER_PULL_RETRIES": "9"}), dh.retries({"PLASBENCH_DOCKER_PULL_RETRIES": "x"})) == (2, 0, 5, 2))
    check("backoff doubles from the base and is capped", (dh.backoff(0, {}), dh.backoff(1, {}), dh.backoff(9, {}), dh.backoff(1, {"PLASBENCH_DOCKER_PULL_BACKOFF": "0"})) == (5.0, 10.0, 60.0, 0.0))
    results = tmp / "res"
    jobs = tmp / "jobs"
    results.mkdir()
    jobs.mkdir()
    diag = dh.diagnose(PROD_PULL, {})
    dh.record(root, diag, "pull", dict(env0, RESULTS_DIR=str(results), PLASBENCH_JOB_DIR=str(jobs), PLASBENCH_JOB_ID="J1", NCBI_API_KEY="SECRETKEY"))
    line = json.loads((results / "run_events.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    check("the diagnosis is a run_events.jsonl line (same fields as scripts/lib.sh run_event)", line["event"] == "docker_diagnosis" and line["cause"] == "corrupt_layer" and line["stage"] == "pull" and {"ts", "epoch", "pid"} <= set(line), line)
    job = json.loads((jobs / "J1.diagnosis.json").read_text(encoding="utf-8"))
    check("and the job's result file; no secret in either", job["cause"] == "corrupt_layer" and "SECRETKEY" not in json.dumps(line) + json.dumps(job))
    dh.record(root, diag, "pull", dict(env0, RESULTS_DIR=str(tmp / "nowhere")))
    check("a results folder that does not exist is not created", not (tmp / "nowhere").exists())

    print("pull: a corrupted layer (the production failure) is retried, then stops, and NEVER builds")
    slept = []
    out = []
    f = Fake({"pull": seq((1, PROD_PULL))})
    got = dr.ensure_image(root, assume_yes=True, run=f.run, streamer=f.stream, exe="docker", environ=env0, out=out.append, sleep=slept.append)
    check("three pulls (1 + the default 2 retries) with backoff between them", f.kinds().count("pull") == 3 and len(slept) == 2, (f.kinds(), slept))
    check("no build even with --yes (consent does not turn an engine problem into a build)", "build" not in f.kinds() and not got["ok"] and got["code"] == 1, (got["code"], f.kinds()))
    check("the diagnosis is returned and shown: cause, proxies, 'did not build'", got["diagnosis"]["cause"] == "corrupt_layer" and "did not build" in got["message"] and any("corrupt_layer" in l for l in out) and any("docker info | grep -i -E 'proxy" in l for l in out))
    text = "\n".join(out)
    check("the cleanup commands are only SHOWN, as last resorts with their consequence, and never run", "docker image rm" in text and "WARNING: deletes this image" in text and not any(c[1] in ("image", "builder", "system") and c[2] in ("rm", "prune") for c in f.calls))
    check("the console's last useful line names the failure in one line", got["message"].count("\n") == 0 and len(got["message"]) < 160, got["message"])
    f = Fake({"pull": seq((1, PROD_PULL), (0, "ok"))})
    got = dr.ensure_image(root, run=f.run, streamer=f.stream, exe="docker", environ=env0, out=lambda t: None, sleep=lambda s: None)
    check("a corrupted layer that comes right on the retry is simply pulled", got["ok"] and got["source"] == "pulled" and f.kinds().count("pull") == 2)
    for retries, pulls in (("0", 1), ("1", 2), ("4", 5)):
        f = Fake({"pull": seq((1, PROD_PULL))})
        dr.ensure_image(root, run=f.run, streamer=f.stream, exe="docker", environ=dict(env0, PLASBENCH_DOCKER_PULL_RETRIES=retries), out=lambda t: None, sleep=lambda s: None)
        check(f"PLASBENCH_DOCKER_PULL_RETRIES={retries}: {pulls} pull(s)", f.kinds().count("pull") == pulls, f.kinds())

    print("pull: the other failures and what each does")
    cases = [
        ("a network failure is retried, then stops (a build needs the internet too)", 'Get "https://ghcr.io/v2/": dial tcp: lookup ghcr.io: no such host', 3, False, 1),
        ("an unknown error stops at once: no retry, no build", "some error docker never printed before", 1, False, 1),
        ("a read-only engine stops with exit 20 (only the person can fix it)", "mkdir /var/lib/docker/tmp: read-only file system", 1, False, 20),
        ("no space stops with exit 20", "write /var/lib/docker/tmp/x: no space left on device", 1, False, 20),
        ("an engine that fell over mid-pull stops with exit 20", "Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?", 1, False, 20),
        ("a rate limit stops (it clears by itself)", "toomanyrequests: You have reached your pull rate limit", 1, False, 1),
        ("a certificate problem stops with the CA advice", "x509: certificate signed by unknown authority", 1, False, 1),
    ]
    for label, text, pulls, builds, code in cases:
        f = Fake({"pull": seq((1, text))})
        out = []
        got = dr.ensure_image(root, assume_yes=True, run=f.run, streamer=f.stream, exe="docker", environ=env0, out=out.append, sleep=lambda s: None)
        check(label, f.kinds().count("pull") == pulls and ("build" in f.kinds()) == builds and not got["ok"] and got["code"] == code, (f.kinds(), got["code"]))
    f = Fake({"pull": seq((1, "some error docker never printed before"))})
    out = []
    got = dr.ensure_image(root, assume_yes=True, run=f.run, streamer=f.stream, exe="docker", environ=env0, out=out.append, sleep=lambda s: None)
    check("unknown: says so, shows the last lines, builds nothing", got["diagnosis"]["cause"] == "unknown" and got["diagnosis"]["confidence"] == "low" and any("some error docker never printed" in l for l in out) and any("will not guess" in l for l in out))
    check("the stop records a diagnosis whose exit convention is documented (1 = failed)", got["code"] == 1)

    print("pull: the image is genuinely unavailable -> a build is offered, and done only with consent")
    for label, text in (("manifest unknown", "Error response from daemon: manifest for x not found: manifest unknown: manifest unknown"),
                        ("repository does not exist", "pull access denied for x, repository does not exist or may require 'docker login'"),
                        ("platform mismatch", "no matching manifest for linux/arm64/v8 in the manifest list entries"),
                        ("denied (not yet public)", "Error response from daemon: Head \"https://ghcr.io/v2/ubeffiong/plasbench/manifests/v0.5.5\": unauthorized")):
        f = Fake({"pull": seq((1, text))})
        out = []
        got = dr.ensure_image(root, run=f.run, streamer=f.stream, exe="docker", environ=env0, out=out.append, sleep=lambda s: None)
        check(f"{label}: no consent -> exit 21, nothing built, one pull only", got["code"] == 21 and "build" not in f.kinds() and f.kinds().count("pull") == 1 and "plasbench runtime build --yes" in got["message"], (got["code"], f.kinds()))
        f = Fake({"pull": seq((1, text))})
        got = dr.ensure_image(root, assume_yes=True, run=f.run, streamer=f.stream, exe="docker", environ=env0, out=lambda t: None, sleep=lambda s: None)
        check(f"{label}: with consent it builds locally", got["ok"] and got["source"] == "built-locally" and "build" in f.kinds())
        f = Fake({"pull": seq((1, text))})
        got = dr.ensure_image(root, run=f.run, streamer=f.stream, exe="docker", environ=env0, out=lambda t: None, ask=lambda q: True, sleep=lambda s: None)
        check(f"{label}: answering yes builds", got["ok"] and got["source"] == "built-locally")
    f = Fake({"pull": seq((1, "Error response from daemon: Head \"https://ghcr.io/v2/x\": unauthorized"))})
    out = []
    dr.ensure_image(root, run=f.run, streamer=f.stream, exe="docker", environ=env0, out=out.append, sleep=lambda s: None)
    check("denied: the message carries the login hint (a GitHub token with read:packages) and the stale-login hint", "docker login ghcr.io" in "\n".join(out) and "read:packages" in "\n".join(out) and "docker logout ghcr.io" in "\n".join(out))
    f = Fake({"pull": seq((1, "no matching manifest for linux/arm64/v8 in the manifest list entries"))})
    out = []
    dr.ensure_image(root, assume_yes=True, run=f.run, streamer=f.stream, exe="docker", environ=env0, out=out.append, sleep=lambda s: None)
    check("platform mismatch: says building natively IS the fix", "Building natively here IS the fix" in "\n".join(out))
    f = Fake({"pull": seq((1, "Error response from daemon: manifest unknown")), "build": seq((1, "#5 ERROR: write /var/lib/docker/x: read-only file system"))})
    out = []
    got = dr.ensure_image(root, assume_yes=True, run=f.run, streamer=f.stream, exe="docker", environ=env0, out=out.append, sleep=lambda s: None)
    check("a build that fails on a read-only engine: diagnosed, exit 20, run once, 'Diagnosis:' printed", not got["ok"] and got["code"] == 20 and f.kinds().count("build") == 1 and got["diagnosis"]["cause"] == "read_only_filesystem" and any(l.startswith("[plasbench] Diagnosis:") for l in out))
    f = Fake({"pull": seq((1, "Error response from daemon: manifest unknown")), "build": seq((1, "ERROR: failed to solve: process \"/bin/sh -c micromamba create -n a\" did not complete successfully: exit code: 137"))})
    got = dr.ensure_image(root, assume_yes=True, run=f.run, streamer=f.stream, exe="docker", environ=env0, out=lambda t: None, sleep=lambda s: None)
    check("a build killed for memory: diagnosed (build_out_of_memory), failed with exit 1", got["code"] == 1 and got["diagnosis"]["cause"] == "build_out_of_memory" and got["failure"]["step"].startswith("/bin/sh -c micromamba"))

    print("pre-flight before the pull and the build")
    f = Fake({"volume create": seq((1, PROD_RO))})
    out = []
    got = dr.ensure_image(root, assume_yes=True, run=f.run, streamer=f.stream, exe="docker", environ=env0, out=out.append, sleep=lambda s: None)
    check("an engine that cannot write: no pull, no build, exit 20, the diagnosis printed", not got["ok"] and got["code"] == 20 and not set(f.kinds()) & {"pull", "build"} and got["diagnosis"]["cause"] == "read_only_filesystem" and any("Docker is not healthy" in l for l in out), (got["code"], f.kinds()))
    check("the message is one line that names the cause", got["message"].startswith("Docker cannot pull or build right now:") and "read-only" in got["message"] and "\n" not in got["message"])
    f = Fake({"volume create": seq((1, PROD_RO))})
    got = dr.ensure_image(root, assume_yes=True, run=f.run, streamer=f.stream, exe="docker", environ=env0, out=lambda t: None, rebuild=True, sleep=lambda s: None)
    check("--rebuild: the same pre-flight, no multi-hour build on an engine that cannot write", got["code"] == 20 and "build" not in f.kinds())
    f = Fake({"volume create": seq((1, PROD_RO))})
    got = dr.ensure_image(root, assume_yes=True, run=f.run, streamer=f.stream, exe="docker", environ=env0, out=lambda t: None, policy="never", sleep=lambda s: None)
    check("PLASBENCH_DOCKER_PULL=never (build only): pre-flight first too", got["code"] == 20 and "build" not in f.kinds())
    f = Fake({"volume create": seq((1, PROD_RO))})
    got = dr.ensure_image(root, assume_yes=True, run=f.run, streamer=f.stream, exe="docker", environ=dict(env0, PLASBENCH_DOCKER_HEALTH="off"), out=lambda t: None, sleep=lambda s: None)
    check("PLASBENCH_DOCKER_HEALTH=off skips it (the escape hatch)", got["ok"] and "volume create" not in f.kinds())
    f = Fake(images={dr.published_image()})
    got = dr.ensure_image(root, run=f.run, streamer=f.stream, exe="docker", environ=env0, out=lambda t: None)
    check("the image is already here: no pre-flight, no docker call beyond the inspect (a run is not slowed down by a pull check)", got["source"] == "present" and "volume create" not in f.kinds() and "pull" not in f.kinds())
    real_local = dh._local_engine
    dh._local_engine = lambda info, environ: True
    dh.STATVFS = vfs(1.0)
    try:
        f = Fake()
        got = dr.ensure_image(root, assume_yes=True, run=f.run, streamer=f.stream, exe="docker", environ=env0, out=lambda t: None, sleep=lambda s: None)
        check("under 2 GB free: blocked before the pull (the disk pre-check), exit 20, no pull, no build", got["code"] == 20 and got["diagnosis"]["cause"] == "no_space" and not set(f.kinds()) & {"pull", "build"}, (got["code"], f.kinds()))
        dh.STATVFS = vfs(5.0)
        f = Fake()
        out = []
        got = dr.ensure_image(root, run=f.run, streamer=f.stream, exe="docker", environ=env0, out=out.append, sleep=lambda s: None)
        check("under 10 GB: a warning is printed and the pull goes ahead", got["ok"] and any("note:" in l and "less than 10 GB" in l for l in out), out[:3])
    finally:
        dh._local_engine = real_local
        dh.STATVFS = getattr(os, "statvfs", None)

    class Offline(Exception):
        message = "docker needs the internet (offline)"

    def need(services):
        raise Offline()
    f = Fake({"pull": seq((1, PROD_PULL))})
    got = dr.ensure_image(root, assume_yes=True, run=f.run, streamer=f.stream, exe="docker", environ=env0, out=lambda t: None, net_require=need, sleep=lambda s: None)
    check("netcheck gating: offline means no pull and no build (exit 3), as before", got["code"] == 3 and not set(f.kinds()) & {"pull", "build"} and "internet" in got["message"])

    print("execute: a run on an unhealthy engine")
    ran = []
    f = Fake({"volume create": seq((1, PROD_RO))}, images={dr.published_image()})
    out = []
    rc = dr.execute(root, ["bash", "x"], {"DATA_DIR": str(tmp / "d"), "RESULTS_DIR": str(tmp / "r"), "LOG_DIR": str(tmp / "l"), "TMP_DIR": str(tmp / "t"), "PLASBENCH_DB_DIR": str(tmp / "db")},
                    run=f.run, streamer=f.stream, exe="docker", environ=env0, out=out.append, runner=lambda a, e: ran.append(a) or 0)
    check("exit 20 (waiting for you), the container is never started, the steps are printed", rc == 20 and not ran and any("wsl --shutdown" in l for l in out) and any(l.startswith("[plasbench] Docker cannot start a container") for l in out), (rc, out[-3:]))
    ran.clear()
    f = Fake(images={dr.published_image()})
    rc = dr.execute(root, ["bash", "x"], {"DATA_DIR": str(tmp / "d"), "RESULTS_DIR": str(tmp / "r"), "LOG_DIR": str(tmp / "l"), "TMP_DIR": str(tmp / "t"), "PLASBENCH_DB_DIR": str(tmp / "db")},
                    run=f.run, streamer=f.stream, exe="docker", environ=env0, out=lambda t: None, runner=lambda a, e: ran.append(a) or 0)
    check("a healthy engine runs the container as before", rc == 0 and len(ran) == 1 and "volume create" in f.kinds())

    print("`plasbench runtime check` and `use docker` carry the same pre-flight")
    rows = dr.check_steps(root, run=Fake({"volume create": seq((1, PROD_RO))}).run, exe="docker", environ=env0)
    check("check: a health row FAILS after 'Docker answers' and nothing else is attempted", [r["step"] for r in rows] == ["Docker answers", "Engine health (answers, can write)"] and not rows[1]["ok"] and "read-only" in rows[1]["detail"], rows)
    import plasbench.cli as cli
    ns = cli.build_parser().parse_args(["runtime", "doctor", "--json"])
    check("`plasbench runtime doctor --json` parses", ns.command == "runtime" and ns.action == "doctor" and ns.json)
    real_run, real_exe, real_probe = dr._run, dr.docker_exe, dr.probe
    scenario = Fake({"volume create": seq((1, PROD_RO))})
    dr._run, dr.docker_exe = scenario.run, (lambda which=None: "docker")
    dr.probe = lambda root_, **k: {"state": "ready", "hint": "", "version": "26.1.0", "image": {"present": True, "name": "img"}}
    local = tmp / "local.env"
    saved_env = dict(os.environ)
    os.environ.update(PLASBENCH_LOCAL_SETTINGS=str(local), PLASBENCH_DOCKER_HEALTH="on")
    dh.forget()
    try:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.runtime_command(cli.build_parser().parse_args(["runtime", "use", "docker"]), root)
        check("use docker: the choice is saved, a health note is printed, exit 0 (a setting is never blocked by a probe)", rc == 0 and "PLASBENCH_RUNTIME" in local.read_text(encoding="utf-8") and "Docker is not healthy" in buf.getvalue(), buf.getvalue()[-300:])
    finally:
        dr._run, dr.docker_exe, dr.probe = real_run, real_exe, real_probe
        os.environ.clear()
        os.environ.update(saved_env)
        dh.forget()

    print("`plasbench runtime doctor`: shapes and exit codes")

    def doctor(scn, argv=("runtime", "doctor"), images=()):
        fake = Fake(scn, images)
        real = (dr._run, dr.docker_exe)
        dr._run, dr.docker_exe = fake.run, (lambda which=None: "docker")
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                rc = cli.runtime_command(cli.build_parser().parse_args(list(argv)), root)
        finally:
            dr._run, dr.docker_exe = real
        return rc, buf.getvalue(), fake
    rc, text, fk = doctor({})
    check("healthy: exit 0, PASS lines, a result, a plan, Environment/Docker/Proxies lines", rc == 0 and "PASS  Engine answers" in text and "Result: healthy" in text and "Next steps" in text and "Environment:" in text and "Proxies:" in text and "Root directory: /var/lib/docker" in text and "Storage driver: overlay2" in text, text)
    rc, text, fk = doctor({"volume create": seq((1, PROD_RO))})
    check("problems: exit 3, FAIL with evidence, the numbered plan, copyable commands, the last resort with WARNING", rc == 3 and "FAIL  Engine can write" in text and "evidence: " in text and "  1. " in text and "Commands to copy" in text and "WARNING:" in text, text)
    rc, text, fk = doctor({"volume create": seq((1, PROD_RO))}, ("runtime", "doctor", "--json"))
    data = json.loads(text)
    check("--json: healthy, checks[], diagnosis{cause, advice, commands, last_resort}, info, environment, plan", rc == 3 and data["healthy"] is False and data["diagnosis"]["cause"] == "read_only_filesystem" and {"advice", "commands", "last_resort", "evidence_lines"} <= set(data["diagnosis"])
          and {"healthy", "checks", "info", "environment", "plan", "warnings", "in_container"} <= set(data), sorted(data))
    rc, text, fk = doctor({}, ("runtime", "doctor", "docker"))
    check("a stray argument is a usage error: exit 2, nothing run", rc == 2 and not fk.calls)
    rc, text, fk = doctor({}, images={dr.published_image()})
    check("doctor runs the container test only with a local image, with --pull=never", ["--pull=never"] == [c[3] for c in fk.calls if c[1] == "run"] and "pull" not in fk.kinds())
    rc, text, fk = doctor({"info": seq((0, json.dumps(dict(INFO, HttpProxy="http://p.example:3128"))))})
    check("proxies are printed (flagged as a cause of corrupted layers)", "HTTP http://p.example:3128" in text and "NOTE  Proxy" in text and "corrupt" in text)

    print("the window: Docker health block")
    html = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
    js = html[html.index("DOCKER-HEALTH-UI-BEGIN"):html.index("DOCKER-HEALTH-UI-END")]
    from plasbench import ui_help, ui_schema, webui
    for needle in ('id="rt_health_btn"', 'id="rt_health"', 'api("runtime/health"', "data-hcopy"):
        check(f"the Environment card has {needle}", needle in html)
    check("no browser dialogs; keyed rendering (setIfChanged); copy buttons; the run is a button click only", not re.search(r"\b(confirm|prompt|alert)\(", js) and "setIfChanged" in js and "copyText" in js and "loadRuntime" not in js and "DOMContentLoaded" not in js)
    check("every tooltip key the block uses exists in ui_help.ENVIRONMENT, with a summary", all(k in ui_help.ENVIRONMENT and ui_help.ENVIRONMENT[k]["summary"] for k in set(re.findall(r'rtTip\("(\w+)"\)', html[html.index("RUNTIME-UI-BEGIN"):html.index("DOCKER-HEALTH-UI-END")]))))
    check("the schema's runtime command lists doctor with a tooltip", any(c["name"] == "runtime" and "doctor" in json.dumps(c["args"]) for c in ui_schema.schema()["commands"]))
    src = (ROOT / "plasbench" / "webui.py").read_text(encoding="utf-8")
    post = src[src.index("def do_POST"):] if "def do_POST" in src else src
    check("the POST route sits behind the session token (after token_ok), the GET only reads memory", src.index('route == "runtime/health"') > 0 and post.index('route == "runtime/health"') > post.index("self.token_ok()") and "def docker_health_state" in src)
    check("runtime_state (the page-load path) never touches the health checks", "docker_health" not in src[src.index("def runtime_state"):src.index("def setting_value")])
    loadcache.reset_all()
    counts = []
    real_check = dh.check
    dh.check = lambda *a, **k: counts.append(k.get("budget")) or {"healthy": True, "checks": [], "diagnosis": None, "info": {}, "plan": [], "environment": "linux", "warnings": [], "seconds": 0}

    class P:
        root = ROOT
    webui._health_last.clear()
    try:
        check("before the first click GET answers {checked: False} and starts nothing", webui.docker_health_state() == {"checked": False} and not counts)
        a = webui.docker_health_run(P())
        b = webui.docker_health_run(P())
        check("the checks run once for two clicks within 30 s (loadcache), bounded by a 20 s budget", len(counts) == 1 and counts[0] == 20.0 and a["checked"] and b["checked"])
        webui.docker_health_run(P(), True)
        check("Run health check again (refresh) really runs them again", len(counts) == 2)
        check("GET afterwards returns the last result with no new run", webui.docker_health_state()["checked"] and len(counts) == 2)
        gate = threading.Event()
        dh.check = lambda *a, **k: (gate.wait(5), {"healthy": True, "checks": [], "diagnosis": None})[1]
        first = []
        t = threading.Thread(target=lambda: first.append(webui.docker_health_run(P(), True)))
        t.start()
        import time
        time.sleep(0.2)
        again = webui.docker_health_run(P(), True)
        gate.set()
        t.join(10)
        check("a second request while one runs is refused with busy, never a second docker process", again.get("busy") is True and first and first[0]["checked"])
    finally:
        dh.check = real_check
        loadcache.reset_all()
        webui._health_last.clear()
    check("a finished job keeps the diagnosis file in its result (webui reads JOB_ID.diagnosis.json)", ".diagnosis.json" in src and 'job["diagnosis"]' in src)

    print("a real `docker` executable on PATH (Linux and macOS)")
    if os.name == "nt":
        print("  n/a   Windows cannot run an extensionless script as `docker`; the same scenarios ran above with the in-process fake, and CI runs this part on Linux")
    else:
        fake_dir = tmp / "bin"
        fake_dir.mkdir()
        exe = fake_dir / "docker"
        exe.write_text(f"#!{sys.executable}\n" + FAKE_SCRIPT.split("\n", 1)[1], encoding="utf-8")
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

        def cli_run(scn, *argv, retries="2"):
            log = tmp / f"log{len(list(tmp.glob('log*')))}"
            sfile = tmp / (log.name + ".scn")
            sfile.write_text(json.dumps(scn), encoding="utf-8")
            env = dict(os.environ, PATH=str(fake_dir) + os.pathsep + os.environ["PATH"], HOME=env0["HOME"], PLASBENCH_UI_HOME=env0["PLASBENCH_UI_HOME"], FAKE_DOCKER_SCENARIO=str(sfile), FAKE_DOCKER_LOG=str(log),
                       PLASBENCH_ASSUME_ONLINE="1", PLASBENCH_DOCKER_PULL_BACKOFF="0", PLASBENCH_DOCKER_PULL_RETRIES=retries, PYTHONPATH=str(ROOT), PYTHONIOENCODING="utf-8")
            env.pop("PLASBENCH_RUNTIME", None)
            done = subprocess.run([sys.executable, "-m", "plasbench", "--project-root", str(ROOT), *argv], capture_output=True, text=True, env=env, timeout=240, cwd=str(tmp))
            calls = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
            return done, calls
        done, calls = cli_run({}, "runtime", "doctor", "--json")
        data = json.loads(done.stdout) if done.stdout.strip().startswith("{") else {}
        check("exe: `runtime doctor --json` on a healthy fake engine: exit 0, healthy, the volume was created and removed", done.returncode == 0 and data.get("healthy") is True and [c[:2] for c in calls].count(["volume", "create"]) == 1 and [c[:2] for c in calls].count(["volume", "rm"]) == 1, (done.returncode, done.stderr[-300:], done.stdout[-300:]))
        done, calls = cli_run({"volume create": seq((1, PROD_RO))}, "runtime", "doctor")
        check("exe: read-only engine: exit 3 with FAIL, evidence and the plan", done.returncode == 3 and "FAIL  Engine can write" in done.stdout and "meta.db" in done.stdout and "Next steps" in done.stdout, (done.returncode, done.stdout[-400:], done.stderr[-300:]))
        done, calls = cli_run({"pull": seq((1, PROD_PULL))}, "runtime", "pull", "--yes")
        check("exe: `runtime pull --yes` with the production corrupted layer: 3 pulls, NO build, exit 1, diagnosis printed", done.returncode == 1 and [c[0] for c in calls].count("pull") == 3 and "build" not in [c[0] for c in calls] and "corrupt_layer" in done.stdout and "did not build" in done.stdout,
              (done.returncode, [c[0] for c in calls], done.stdout[-500:], done.stderr[-300:]))
        done, calls = cli_run({"pull": seq((1, PROD_PULL))}, "runtime", "pull", "--yes", retries="0")
        check("exe: PLASBENCH_DOCKER_PULL_RETRIES=0 -> one pull", [c[0] for c in calls].count("pull") == 1)
        done, calls = cli_run({"pull": seq((1, "Error response from daemon: manifest unknown"))}, "runtime", "pull", "--yes")
        check("exe: manifest unknown + --yes: the build runs (the image is genuinely unavailable)", "build" in [c[0] for c in calls] and [c[0] for c in calls].count("pull") == 1 and "plasbench:" in done.stdout, (done.returncode, done.stdout[-400:], done.stderr[-200:]))
        done, calls = cli_run({"volume create": seq((1, PROD_RO))}, "runtime", "pull", "--yes")
        check("exe: unhealthy engine: exit 20, neither pull nor build", done.returncode == 20 and not {"pull", "build"} & {c[0] for c in calls}, (done.returncode, [c[0] for c in calls]))
        done, calls = cli_run({"pull": seq((1, "an error nobody has seen"))}, "runtime", "pull", "--yes")
        check("exe: an unknown pull error: stop, exit 1, no build", done.returncode == 1 and "build" not in [c[0] for c in calls] and "does not recognise" in done.stdout, (done.returncode, done.stdout[-300:]))

    print("Python 3.9 and line endings")
    for rel in ("plasbench/docker_health.py", "python/docker_diagnosis.py"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        check(f"{rel}: from __future__ import annotations, no Path.write_text/read_text(newline=)", "from __future__ import annotations" in text and not re.search(r"\.(write|read)_text\([^)]*newline=", text) and b"\r" not in (ROOT / rel).read_bytes())
    return not FAILED


if __name__ == "__main__":
    good = main()
    print("ALL DOCKER HEALTH TESTS PASSED" if good else "FAILED: " + "; ".join(FAILED))
    sys.exit(0 if good else 1)
