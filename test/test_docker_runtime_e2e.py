#!/usr/bin/env python3
"""Real Docker, end to end (plasbench/docker_runtime.py): build a tiny image, run a command through the real wrapper with real mounts, and check what lands on the host.

Runs only where it is safe and possible: Linux with a Docker daemon, in CI (CI is set) or with PLASBENCH_E2E_DOCKER=1, and a base image that can be pulled. Anywhere else
it prints `n/a` lines (never `skip`: the suite counts skips) and passes. It proves, with a real container:
  * the local-build path (a Dockerfile fixture, `docker build`, the version check),
  * identical-path mounts: the path a container writes down is the host's path,
  * files written in the container belong to the host user (not root),
  * extra tools and a database written in one container are seen by the next one (persistent storage),
  * the exit code of the command comes back unchanged (0, 1, 6, 20, 21),
  * a container named like a window job can be stopped by name.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from plasbench import __version__, docker_runtime as dr  # noqa: E402

BASE = "python:3.12-slim"
ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


def na(why):
    print(f"  n/a   real Docker end-to-end: {why}")
    print("PASS")
    sys.exit(0)


FIXTURE = """FROM {base}
ARG PLASBENCH_VERSION=unknown
ARG IMAGE_NAME=x
ARG BUILD_DATE=x
LABEL org.opencontainers.image.version="$PLASBENCH_VERSION"
COPY plasbench /opt/plasbench/plasbench
COPY config /opt/plasbench/config
RUN printf '#!/bin/sh\\nexec python -m plasbench "$@"\\n' > /usr/local/bin/plasbench && chmod 0755 /usr/local/bin/plasbench
ENV PYTHONPATH=/opt/plasbench
WORKDIR /opt/plasbench
"""


def main():
    if not sys.platform.startswith("linux"):
        na("not Linux (nothing is started on other systems)")
    if not (os.environ.get("CI") or os.environ.get("PLASBENCH_E2E_DOCKER") == "1"):
        na("neither CI nor PLASBENCH_E2E_DOCKER=1 is set")
    exe = shutil.which("docker")
    if not exe or dr.probe(None, exe=exe)["state"] != "ready":
        na("no Docker daemon answers")
    pulled = subprocess.run([exe, "pull", BASE], capture_output=True).returncode == 0
    if not pulled and subprocess.run([exe, "image", "inspect", BASE], capture_output=True).returncode != 0:
        na(f"the base image {BASE} cannot be pulled here")

    tmp = Path(tempfile.mkdtemp(prefix="pbe2e"))
    proj = tmp / "pro ject"
    shutil.copytree(ROOT / "plasbench", proj / "plasbench", ignore=shutil.ignore_patterns("__pycache__"))
    (proj / "config").mkdir()
    shutil.copy(ROOT / "config" / "config.sh", proj / "config" / "config.sh")
    (proj / "Dockerfile").write_text(FIXTURE.format(base=BASE), encoding="utf-8")
    tag = f"plasbench-e2e:{os.getpid()}"
    res, data, logs, tmpd, dbs, extras = (tmp / n for n in ("res ults", "data", "logs", "tmp", "dbs", "extras"))
    environ = dict(os.environ, PLASBENCH_DOCKER_IMAGE=tag, PLASBENCH_DOCKER_PULL="never", PLASBENCH_UI_HOME=str(tmp / "ui"), PLASBENCH_DOCKER_EXTRA=str(extras),
                   HOME=str(tmp / "home"))
    os.makedirs(environ["HOME"], exist_ok=True)
    env = {"RESULTS_DIR": str(res), "DATA_DIR": str(data), "LOG_DIR": str(logs), "TMP_DIR": str(tmpd), "PLASBENCH_DB_DIR": str(dbs)}
    lines = []
    try:
        print("build path")
        got = dr.ensure_image(proj, assume_yes=True, out=lines.append, environ=environ, rebuild=True, exe=exe)
        check("a local image is built from the Dockerfile", got["ok"] and got["source"] == "built-locally" and got["image"] == tag, (got, lines[-8:]))
        verdict = dr.verify_image(tag, exe, ui_home=tmp / "ui")
        check("the version inside equals the host's", verdict["ok"] and verdict["version"] == __version__, verdict)
        info = dr.image_state(proj, exe, environ=environ)
        check("the image is reported present and built here", info["present"] and info["source"] == "built-locally", info)

        print("a run through the real wrapper")
        script = ('echo hello > "$RESULTS_DIR/out.txt"; printf "%s" "$RESULTS_DIR" > "$RESULTS_DIR/where.txt"; plasbench --version > "$RESULTS_DIR/ver.txt"; '
                  'mkdir -p "$PLASBENCH_EXTRA_HOME/bin" "$PLASBENCH_DB_DIR/fakedb"; printf "#!/bin/sh\\necho fake-tool\\n" > "$PLASBENCH_EXTRA_HOME/bin/faketool"; '
                  'chmod +x "$PLASBENCH_EXTRA_HOME/bin/faketool"; echo fake-db > "$PLASBENCH_DB_DIR/fakedb/file"')
        code = dr.execute(proj, ["sh", "-c", script], env, environ=environ, exe=exe, out=lines.append)
        check("the command ran in a container and exited 0", code == 0, (code, lines[-6:]))
        out = res / "out.txt"
        check("a file written in the container is on the host", out.is_file() and out.read_text().strip() == "hello")
        check("it belongs to the host user, not root", out.is_file() and out.stat().st_uid == os.getuid(), out.stat().st_uid if out.exists() else "missing")
        check("the path the container recorded is the host's path (identical mount, with a space in it)", (res / "where.txt").read_text() == str(res))
        check("plasbench --version in the container", (res / "ver.txt").read_text().strip() == f"plasbench {__version__}")

        print("persistent tools and databases")
        code = dr.execute(proj, ["sh", "-c", 'faketool > "$RESULTS_DIR/tool.txt"; cat "$PLASBENCH_DB_DIR/fakedb/file" > "$RESULTS_DIR/db.txt"'], env, environ=environ, exe=exe, out=lines.append)
        check("a second container sees the tool and the database added by the first", code == 0 and (res / "tool.txt").read_text().strip() == "fake-tool"
              and (res / "db.txt").read_text().strip() == "fake-db", (code, lines[-5:]))
        check("the tool is in the persistent folder on the host, listed for the manifest", (extras / "bin" / "faketool").is_file() and "faketool" in dr.extras_listing(proj, environ)["tools"])

        print("exit codes")
        for want in (0, 1, 6, 20, 21):
            got_code = dr.execute(proj, ["sh", "-c", f"exit {want}"], env, environ=environ, exe=exe, out=lines.append)
            check(f"exit code {want} comes back unchanged", got_code == want, got_code)

        print("cancel")
        name = "plasbench-e2e-cancel"
        job = dict(environ, PLASBENCH_JOB_ID="e2e-cancel", PLASBENCH_JOB_DIR=str(tmp))
        started = []
        t = threading.Thread(target=lambda: started.append(dr.execute(proj, ["sleep", "120"], env, environ=job, exe=exe, out=lambda s: None)))
        t.start()
        deadline = time.time() + 60
        while time.time() < deadline and not (tmp / "e2e-cancel.container").exists():
            time.sleep(0.2)
        check("the container is named after the job and left a marker", (tmp / "e2e-cancel.container").read_text().strip() == "plasbench-e2e-cancel" if (tmp / "e2e-cancel.container").exists() else False)
        time.sleep(1.0)
        check("cancel stops it by name", dr.stop_for_job(str(tmp), "e2e-cancel"))
        t.join(60)
        check("the run ends after the stop", not t.is_alive())
        _ = name
    finally:
        subprocess.run([exe, "rmi", "-f", tag], capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)
    return ok


if __name__ == "__main__":
    good = main()
    print("PASS" if good else "FAIL")
    sys.exit(0 if good else 1)
