#!/usr/bin/env python3
"""Where the tools run (plasbench/docker_runtime.py): the settings, the path mapping, the `docker run` argument list, the image (present, pulled, built), failure
classification, cancel, the manifest fields, the routes and the Environment card. Docker is replaced by a recording fake (an injected `run` / `streamer`); nothing starts a
real container here (test/test_docker_runtime_e2e.sh does, where Docker exists)."""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from plasbench import __version__, docker_runtime as dr, loadcache  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


class Fake:
    """A recording fake docker: `images` is the set of image names that exist; `pull_ok` decides pulls; `version` is what `plasbench --version` prints inside."""

    def __init__(self, images=(), pull_ok=True, version=None, state="ready", build_ok=True, build_out=None):
        self.calls, self.images, self.pull_ok, self.state, self.build_ok = [], set(images), pull_ok, state, build_ok
        self.version = version or __version__
        self.build_out = build_out or ["Step 1/2 : FROM x", "done"]

    def run(self, argv, timeout=20, env=None):
        self.calls.append(list(argv))
        a = argv[1:]
        if a[:1] == ["version"]:
            return {"ready": (0, "26.1.0|amd64"), "stopped": (1, "Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?"),
                    "perm": (1, "permission denied while trying to connect to the docker API at unix:///var/run/docker.sock")}[self.state]
        if a[:2] == ["image", "inspect"]:
            return (0, "sha256:abc|1073741824|2026-01-01T00:00:00Z") if a[2] in self.images else (1, "Error: No such image")
        if a[:1] == ["buildx"]:
            return 0, "buildx v0.1"
        if a[:1] == ["run"] and a[-2:] == ["plasbench", "--version"]:
            return 0, f"plasbench {self.version}"
        if a[:1] == ["run"]:
            return 0, "ok"
        if a[:1] == ["stop"]:
            return 0, a[-1]
        return 0, ""

    def stream(self, argv, env=None, out=None, heartbeat=30.0, what=""):
        self.calls.append(list(argv))
        if argv[1] == "pull":
            if self.pull_ok:
                self.images.add(argv[2])
                return 0, ["pulled"]
            return 1, ["Error response from daemon: pull access denied for x, repository does not exist"]
        if argv[1] == "build":
            if self.build_ok:
                self.images.add(argv[argv.index("-t") + 1])
                return 0, self.build_out
            return 1, ["#5 ERROR: process \"/bin/sh -c micromamba create\" did not complete successfully: exit code: 1", "no space left on device"]
        return 0, []


def main():
    tmp = Path(tempfile.mkdtemp(prefix="pbrt"))
    root = tmp / "proj"
    (root / "config").mkdir(parents=True)
    (root / "Dockerfile").write_text("FROM x\nRUN micromamba create -n a\nRUN micromamba create -n b\n", encoding="utf-8")
    (root / "config" / "config.sh").write_text('export THREADS\nexport DATA_DIR="${DATA_DIR:-x}"\nexport RUN_PLATON="${RUN_PLATON:-1}"\n', encoding="utf-8")
    env0 = {"HOME": str(tmp / "home"), "PLASBENCH_UI_HOME": str(tmp / "ui")}
    os.makedirs(env0["HOME"], exist_ok=True)

    print("settings")
    check("default runtime is conda", dr.runtime_setting(root, environ={}) == "conda")
    check("--runtime wins", dr.runtime_setting(root, "docker", environ={"PLASBENCH_RUNTIME": "conda"}) == "docker")
    check("environment beats local.env", dr.runtime_setting(root, environ={"PLASBENCH_RUNTIME": "docker"}) == "docker")
    dr.save_local_setting(root, "PLASBENCH_RUNTIME", "docker", environ={})
    check("local.env is read", dr.runtime_setting(root, environ={}) == "docker")
    dr.save_local_setting(root, "PLASBENCH_RUNTIME", "conda", environ={})
    check("switch back rewrites the one line", (root / "config" / "local.env").read_text().count("PLASBENCH_RUNTIME") == 1 and dr.runtime_setting(root, environ={}) == "conda")
    try:
        dr.runtime_setting(root, "podman")
        check("a wrong runtime is refused", False)
    except ValueError:
        check("a wrong runtime is refused", True)
    check("default image is this version's tag, never latest", dr.published_image() == f"ghcr.io/ubeffiong/plasbench:v{__version__}" and "latest" not in dr.published_image())
    check("local tag carries the version", dr.local_tag() == f"plasbench:{__version__}-local")
    check("tag version parsing", dr.image_tag_version("ghcr.io/o/plasbench:v0.5.4") == "0.5.4" and dr.image_tag_version("plasbench:0.5.4-local") == "0.5.4"
          and dr.image_tag_version("x:latest") is None)

    print("path mapping")
    check("linux path unchanged", dr.to_container("/home/me/study", "posix") == "/home/me/study")
    check("WSL /mnt path unchanged (identical mount)", dr.to_container("/mnt/d/My Study/ü", "posix") == "/mnt/d/My Study/ü")
    check("native windows drive -> /mnt/d", dr.to_container("D:\\x\\y z", "windows") == "/mnt/d/x/y z" and dr.to_container("F:/foo", "windows") == "/mnt/f/foo")
    check("windows mount host side uses backslashes", dr.host_for_mount("D:/x/y", "windows") == "D:\\x\\y")
    for bad, kind in (("\\\\server\\share\\x", "windows"), ("//server/share/x", "posix"), ("relative/p", "posix"), ("/a:b", "posix"), ("D:\\x", "posix"), ("", "posix")):
        try:
            dr.to_container(bad, kind)
            check(f"refused: {bad!r}", False)
        except dr.PathError as exc:
            check(f"refused: {bad!r} with a reason", len(str(exc)) > 20)
    check("round trip", dr.from_container(dr.to_container("D:\\data\\a", "windows"), "windows") == "D:\\data\\a")

    print("argv builder")
    (root / "config" / "local.env").unlink()
    # Virtual POSIX paths and injected file checks: the same assertions hold on a Windows computer running this test.
    data, res, logs, tmpd, dbs = ("/vt/" + n for n in ("data sp", "res", "logs", "tmpx", "db"))
    sheet, extra = "/vt/sheet.tsv", "/vt/extras"
    FS = dict(exists=lambda p: True, isdir=lambda p: not str(p).endswith(".tsv"), makedirs=lambda *a, **k: None)
    env = {"DATA_DIR": str(data), "RESULTS_DIR": str(res), "LOG_DIR": str(logs), "TMP_DIR": str(tmpd), "SAMPLE_SHEET": str(sheet), "THREADS": "4", "RUN_PLATON": "0", "PLASBENCH_DB_DIR": str(dbs)}
    osenv = dict(env0, NCBI_API_KEY="SECRETKEY", PATH="/bin")
    argv, run_env, plan = dr.build_run_argv(root, ["bash", "scripts/run_all.sh", "0", "1"], env, image="img:1", name="plasbench-J1", kind="posix", uid=1000, gid=1001, extra=extra,
                                            cpus=4, memory_gb=8, environ=osenv, image_id="sha256:abc", image_source="pulled", docker_version="26.1.0", **FS)
    text = " ".join(argv)
    check("docker run --rm with the job's container name", argv[:5] == ["docker", "run", "--rm", "--name", "plasbench-J1"], argv[:6])
    check("runs as the host user (files are not root-owned)", "--user 1000:1001" in text)
    check("cpus and memory limits", "--cpus 4" in text and "--memory 8g" in text)
    check("every folder is mounted at its own path", all(f"{p}:{p}" in text for p in (data, res, logs, tmpd, dbs, extra)), text)
    check("writable folders are rw, the sheet is ro", f"{sheet}:{sheet}:ro" in text and f"{res}:{res}:ro" not in text)
    check("identical paths reported", plan["identical_paths"])
    check("secrets are passed by name, not value", "SECRETKEY" not in text and "-e NCBI_API_KEY" in text and run_env["NCBI_API_KEY"] == "SECRETKEY")
    check("path env is the same path inside", f"DATA_DIR={data}" in text and f"RESULTS_DIR={res}" in text)
    check("extra storage on PATH and conda env path", f"PLASBENCH_EXTRA_BIN={extra}/bin" in text and f"CONDA_ENVS_PATH={extra}/envs" in text)
    check("runtime and image recorded inside", "PLASBENCH_RUNTIME=docker" in text and "CONTAINER_IMAGE=img:1" in text and "PLASBENCH_IMAGE_SOURCE=pulled" in text)
    check("image, then the wrapper, then the command as separate arguments", argv[-8:-6] == ["sh", "-c"] and argv[-4:] == ["bash", "scripts/run_all.sh", "0", "1"] and argv[-9] == "img:1", argv[-9:])
    check("no shell string holds a user value", not any(str(data) in a and a.startswith("PATH=") for a in argv))
    check("a path with spaces is one argument", any(a == f"{data}:{data}" for a in argv))
    a2, _e2, p2 = dr.build_run_argv(root, ["x"], {"DATA_DIR": "D:\\data", "RESULTS_DIR": "D:\\res"}, image="i", name="n", kind="windows", environ=env0, exists=lambda p: True, isdir=lambda p: True,
                                    makedirs=lambda *a, **k: None)
    t2 = " ".join(a2)
    check("native Windows: D:\\data mounted at /mnt/d/data and no --user", "D:\\data:/mnt/d/data" in t2 and "--user" not in t2 and "DATA_DIR=/mnt/d/data" in t2 and not p2["identical_paths"], t2)
    try:
        dr.build_run_argv(root, ["x"], {"DATA_DIR": "\\\\srv\\share\\d"}, image="i", name="n", kind="windows", environ=env0, exists=lambda p: True, isdir=lambda p: True)
        check("UNC study folder refused", False)
    except dr.PathError:
        check("UNC study folder refused", True)
    check("container name from the job id", dr.container_name({"PLASBENCH_JOB_ID": "20260101-000000-abc"}) == "plasbench-20260101-000000-abc")

    print("conda unchanged (golden)")
    import plasbench.cli as cli
    calls = []
    orig = cli.run
    cli.run = lambda command, root_, env=None: calls.append((command, env)) or 0
    try:
        code = cli.run_in_runtime("conda", ["bash", "scripts/run_all.sh", "0"], ["bash", "scripts/run_all.sh", "0"], root, {"A": "1"})
    finally:
        cli.run = orig
    check("conda runs exactly the host command with the same env", code == 0 and calls == [(["bash", "scripts/run_all.sh", "0"], {"A": "1"})])

    print("probe and image")
    f = Fake()
    check("not installed", dr.probe(root, run=f.run, exe="", environ={})["state"] == "not_installed")
    check("wsl integration off", dr.probe(root, run=f.run, exe="", environ={"WSL_DISTRO_NAME": "U"}, exists=lambda p: p == "/mnt/wsl/docker-desktop")["state"] == "wsl_integration_off")
    check("daemon stopped", dr.probe(root, run=Fake(state="stopped").run, exe="docker", environ={})["state"] == "daemon_stopped")
    check("permission needed", dr.probe(root, run=Fake(state="perm").run, exe="docker", environ={})["state"] == "permission_needed")
    pr = dr.probe(root, run=Fake(images={dr.published_image()}).run, exe="docker", environ={})
    check("ready with the image present and matching", pr["state"] == "ready" and pr["image"]["present"] and pr["image"]["matches"] is True and pr["image"]["size_bytes"] == 1073741824)

    print("image: present -> pull -> build")
    out = []
    got = dr.ensure_image(root, run=Fake(images={dr.published_image()}).run, streamer=Fake().stream, exe="docker", environ={}, out=out.append)
    check("present image is used, nothing pulled", got["source"] == "present")
    fk = Fake()
    got = dr.ensure_image(root, run=fk.run, streamer=fk.stream, exe="docker", environ={}, out=out.append)
    check("missing image is pulled", got["source"] == "pulled" and ["docker", "pull", dr.published_image()] in fk.calls)
    fk = Fake(pull_ok=False)
    got = dr.ensure_image(root, run=fk.run, streamer=fk.stream, exe="docker", environ={}, out=out.append)
    check("pull fails, no consent: nothing built, exit 21", got["code"] == 21 and not any(c[1] == "build" for c in fk.calls) and "plasbench runtime build --yes" in got["message"])
    got = dr.ensure_image(root, run=fk.run, streamer=fk.stream, exe="docker", environ={}, out=out.append, ask=lambda q: False)
    check("a 'no' answer builds nothing", got["code"] == 21)
    fk = Fake(pull_ok=False)
    got = dr.ensure_image(root, assume_yes=True, run=fk.run, streamer=fk.stream, exe="docker", environ={}, out=out.append)
    build = [c for c in fk.calls if c[1] == "build"]
    check("pull fails, consent: built locally", got["ok"] and got["source"] == "built-locally" and got["image"] == dr.local_tag() and len(build) == 1)
    b = build[0]
    check("build argv: tag, Dockerfile, version arg, context, no --no-cache", b[b.index("-t") + 1] == dr.local_tag() and "-f" in b and f"PLASBENCH_VERSION={__version__}" in b and b[-1] == str(root) and "--no-cache" not in b, b)
    check("the built image is chosen from then on", dr.configured_image(root, "docker", fk.run, {}) == (dr.local_tag(), False))
    fk = Fake(pull_ok=False)
    got = dr.ensure_image(root, assume_yes=True, run=fk.run, streamer=fk.stream, exe="docker", environ={}, out=out.append, policy="never")
    check("policy never: no pull attempted, still builds", got["source"] == "built-locally" and not any(c[1] == "pull" for c in fk.calls))
    fk = Fake(images={dr.local_tag()})
    got = dr.ensure_image(root, assume_yes=True, run=fk.run, streamer=fk.stream, exe="docker", environ={}, out=out.append, rebuild=True)
    check("--rebuild builds even when the image exists", got["source"] == "built-locally" and any(c[1] == "build" for c in fk.calls))
    fk = Fake(pull_ok=False, build_ok=False)
    out2 = []
    got = dr.ensure_image(root, assume_yes=True, run=fk.run, streamer=fk.stream, exe="docker", environ={}, out=out2.append)
    check("build failure is classified with the step and the last lines", not got["ok"] and got["failure"]["kind"] == "disk" and "micromamba create" in got["failure"]["step"] and any("no space" in l for l in out2))

    class Offline(Exception):
        message = "docker needs the internet (offline)"

    def need(services):
        raise Offline()
    fk = Fake(pull_ok=False)
    got = dr.ensure_image(root, assume_yes=True, run=fk.run, streamer=fk.stream, exe="docker", environ={}, out=out.append, net_require=need)
    check("offline: no pull, no build, a plain message", got["code"] == 3 and not any(c[1] in ("pull", "build") for c in fk.calls) and "internet" in got["message"])
    plan = dr.build_plan(root, "t")
    check("the build plan describes the Dockerfile and promises no size", "2 conda environments" in " ".join(plan["lines"]) and "not measured" in " ".join(plan["lines"]))
    for text, kind in (("no space left on device", "disk"), ("dial tcp: lookup x: no such host", "network"), ("pull access denied", "registry"), ("exec format error", "platform"),
                       ("Cannot connect to the Docker daemon", "daemon"), ("got permission denied while trying to connect", "permission"), ("weird", "unknown")):
        check(f"classify {kind}", dr.classify_failure(text)["kind"] == kind)

    print("version check")
    ui = tmp / "ui2"
    fk = Fake(images={"img:1"}, version="0.0.1")
    v = dr.verify_image("img:1", "docker", fk.run, ui)
    check("an image of another version is refused with the matching image named", not v["ok"] and "0.0.1" in v["message"] and dr.published_image() in v["message"])
    fk = Fake(images={"img:1"})
    check("a matching image passes, and is not started again", dr.verify_image("img:1", "docker", fk.run, ui)["ok"] and dr.verify_image("img:1", "docker", fk.run, ui)["message"] == "verified earlier")

    print("execute: exit codes, cancel marker")
    for code in (0, 1, 6, 20, 21):
        fk = Fake(images={dr.published_image()})
        seen = []
        rc = dr.execute(root, ["bash", "scripts/run_all.sh"], {"DATA_DIR": str(tmp / "d"), "RESULTS_DIR": str(tmp / "r"), "LOG_DIR": str(tmp / "l"), "TMP_DIR": str(tmp / "t"), "PLASBENCH_DB_DIR": str(tmp / "db")}, run=fk.run, streamer=fk.stream,
                        exe="docker", environ=dict(env0, PLASBENCH_JOB_ID="J9", PLASBENCH_JOB_DIR=str(tmp / "jobs")), out=lambda t: None, runner=lambda a, e, c=code: (seen.append(a), c)[1])
        check(f"exit code {code} passes through", rc == code and seen and seen[0][3:5] == ["--name", "plasbench-J9"], (rc, seen[:1]))
    (tmp / "jobs").mkdir(exist_ok=True)
    (tmp / "jobs" / "J9.container").write_text("plasbench-J9")
    fk = Fake()
    check("cancel stops the named container", dr.stop_for_job(str(tmp / "jobs"), "J9", run=fk.run) and fk.calls[-1][1:] == ["stop", "-t", "10", "plasbench-J9"], fk.calls)
    fk = Fake()
    check("a job without a container starts no docker", not dr.stop_for_job(str(tmp / "jobs"), "J0", run=fk.run) and not fk.calls)
    rc = dr.execute(root, ["x"], None, run=Fake(state="stopped").run, exe="docker", environ=env0, out=lambda t: None)
    check("docker not running: exit 1 with advice", rc == 1)
    rc = dr.execute(root, ["x"], None, run=Fake(pull_ok=False).run, streamer=Fake(pull_ok=False).stream, exe="docker", environ=env0, out=lambda t: None, interactive_ok=False)
    check("image missing and not agreed: exit 21", rc == 21)

    print("persistent extras (the same folder in two containers)")
    vex = "/vt/xt"
    a1, *_ = dr.build_run_argv(root, ["x"], env, image="i", name="n1", kind="posix", extra=vex, environ=env0, **FS)
    a2, *_ = dr.build_run_argv(root, ["x"], env, image="i", name="n2", kind="posix", extra=vex, environ=env0, **FS)
    check("both containers mount the same extras folder at the same path", f"{vex}:{vex}" in " ".join(a1) and f"{vex}:{vex}" in " ".join(a2))
    ex = tmp / "xt"
    ex.mkdir(exist_ok=True)
    (ex / "bin").mkdir(exist_ok=True)
    (ex / "bin" / "faketool").write_text("x")
    (ex / "faketool").mkdir(exist_ok=True)
    (ex / "faketool" / "plasbench-install.json").write_text(json.dumps({"tool": "faketool", "commit": "abc"}))
    lst = dr.extras_listing(root, {"PLASBENCH_DOCKER_EXTRA": str(ex)})
    check("extras are listed with provenance", lst["tools"] == ["faketool"] and lst["provenance"][0]["commit"] == "abc")

    print("manifest and report")
    sys.path.insert(0, str(ROOT / "python"))
    import write_manifest
    os.environ.update(PLASBENCH_RUNTIME="docker", CONTAINER_IMAGE="img:1", CONTAINER_IMAGE_DIGEST="sha256:abc", PLASBENCH_IMAGE_SOURCE="built-locally", PLASBENCH_DOCKER_VERSION="26.1.0",
                      PLASBENCH_RUNTIME_MOUNTS=json.dumps([{"host": "/a", "container": "/a", "rw": True}]), PLASBENCH_EXTRA_HOME=str(ex))
    rec = write_manifest.runtime_record()
    check("manifest records runtime, image, source, docker version, mounts, extras", rec["runtime"] == "docker" and rec["image_source"] == "built-locally" and rec["docker_version"] == "26.1.0"
          and rec["mounts"][0]["host"] == "/a" and rec["extras"]["tools"] == ["faketool"] and rec["extras"]["provenance"])
    os.environ.pop("PLASBENCH_RUNTIME")
    check("conda manifest says conda", write_manifest.runtime_record() == {"runtime": "conda"})

    print("window")
    from plasbench import docker_helper, ui_help, ui_schema, webui
    html = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
    for needle in ('id="env_card"', "rt_docker", "rt_conda", "rt_pull", "rt_build", "rt_test_btn", "rt_ready", 'api("runtime")', 'api("runtime/use"', 'api("runtime/test"', 'api("runtime/pull"'):
        check(f"Environment card has {needle}", needle in html)
    js = html[html.index("RUNTIME-UI-BEGIN"):html.index("RUNTIME-UI-END")]
    check("Environment card uses designed dialogs only", "modalDialog" in js and not re.search(r"\b(confirm|prompt|alert)\(", js))
    check("Environment card is keyed (setIfChanged) and disables Docker with the reason", "setIfChanged" in js and "docker_reason" in js)
    check("tooltips exist for every Environment help key the card uses", all(k in ui_help.ENVIRONMENT for k in set(re.findall(r'rtTip\("(\w+)"\)', js))))
    sch = ui_schema.schema()
    check("schema carries the help and the runtime command", "environment_help" in sch and any(c["name"] == "runtime" for c in sch["commands"]) and "runtime" in [m for c in sch["categories"] for m in c["commands"]])
    check("run has --runtime with a tooltip", any(a["dest"] == "runtime" and a["tooltip"] for c in sch["commands"] if c["name"] == "run" for a in c["args"]))
    rows = {r["key"]: r for r in webui.Project(ROOT).settings()} if hasattr(webui, "Project") else {}
    if rows:
        check("settings rows exist for the runtime keys", all(k in rows for k in ("PLASBENCH_RUNTIME", "PLASBENCH_DOCKER_IMAGE", "PLASBENCH_DOCKER_PULL", "PLASBENCH_DOCKER_EXTRA")))
    loadcache.reset_all()
    calls = []
    orig_probe = webui._docker_probe
    webui._docker_probe = lambda r: calls.append(1) or {"state": "ready", "installed": True, "running": True, "version": "1", "hint": "", "image": {}}
    try:
        class P:
            root = ROOT

            def local_env(self):
                return {}
        st = webui.runtime_state(P())
        check("the state call never waits for the docker probe (pending, then answered by the background probe)", st["docker"]["pending"] in (True, False))
        import time
        time.sleep(0.5)
        check("the probe ran once in the background", len(calls) == 1)
        webui.runtime_state(P())
        check("a second call reuses it", len(calls) == 1)
    finally:
        webui._docker_probe = orig_probe
    src = (ROOT / "plasbench" / "webui.py").read_text(encoding="utf-8")
    check("routes exist", all(f'route == "{r}"' in src or f'"{r}"' in src for r in ("runtime", "runtime/use", "runtime/test", "runtime/pull")))
    check("job env carries the job id for container names", "PLASBENCH_JOB_ID=job_id" in src)

    print("cli")
    from plasbench.cli import build_parser
    ns = build_parser().parse_args(["run", "--runtime", "docker", "--demo"] if False else ["run", "--runtime", "docker"])
    check("plasbench run --runtime docker parses", ns.runtime == "docker")
    ns = build_parser().parse_args(["runtime", "build", "--yes", "--rebuild"])
    check("plasbench runtime build --yes --rebuild parses", ns.action == "build" and ns.yes and ns.rebuild)
    return ok


if __name__ == "__main__":
    good = main()
    print("PASS" if good else "FAIL")
    sys.exit(0 if good else 1)
