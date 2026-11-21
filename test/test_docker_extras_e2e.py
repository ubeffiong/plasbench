#!/usr/bin/env python3
"""Real Docker, real micromamba, a non-root user: tool installs in Docker mode (env/install_tools.sh through plasbench/docker_runtime.py).

The production failure: the image's conda environments (/opt/conda/envs/*) are owned by the image's own user, the container runs as the HOST user (--user uid:gid), and
`plasbench check --yes` solved into /opt/conda/envs/plasbench: "Could not open lockfile ... conda-meta.lock", then "Permission denied" while unlinking packages. This builds a
fixture image with the same layout (the production base image, a root-owned env at /opt/conda/envs/plasbench with python + curl, the PlasBench scripts) and proves:
  * the PRE-FIX failure mode: micromamba run as the host user against the image's environment fails with a permission / lockfile error,
  * a read-only prefix is refused at once, with one clear message, and the image environment is not changed (also for a comma list of profiles),
  * the real install path (bash env/install_tools.sh --yes jq, through dr.execute: real mounts, --user, the wrapper) exits 0 and puts jq in the persistent extras folder,
  * a SECOND container finds and runs jq (persistence, PATH precedence), the files belong to the host user,
  * the image's conda-meta and file listing are byte-identical before and after everything above,
  * proc_stats works in an image that has no ps (the heartbeat never fails the command it watches).
Runs only where it is safe and possible (Linux, a Docker daemon, CI or PLASBENCH_E2E_DOCKER=1, the base image and the internet reachable); anywhere else it prints `n/a`
lines (never the word the suite counts as a skipped check) and passes."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from plasbench import __version__, docker_runtime as dr  # noqa: E402

BASE = "mambaorg/micromamba@sha256:e1476182cd40eb1f7c0cfae4adec9bfd78f3d7f05c61368306abfdc8939c1198"   # the production Dockerfile's base
ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


def na(why):
    print(f"  n/a   real Docker extras end-to-end: {why}")
    print("PASS")
    sys.exit(0)


FIXTURE = """FROM {base}
ARG PLASBENCH_VERSION=unknown
ARG IMAGE_NAME=x
ARG BUILD_DATE=x
LABEL org.opencontainers.image.version="$PLASBENCH_VERSION"
USER root
RUN micromamba create -y -n plasbench -c conda-forge python=3.12 curl && micromamba clean --all --yes
# The production layout: the environment belongs to root (here; in the image to its own user) and is not writable by the user the container runs as.
RUN chown -R root:root /opt/conda/envs && chmod -R go-w /opt/conda/envs && chmod -R go+rX /opt/conda
COPY plasbench /opt/plasbench/plasbench
COPY config /opt/plasbench/config
COPY env /opt/plasbench/env
COPY scripts /opt/plasbench/scripts
COPY python /opt/plasbench/python
COPY adapters /opt/plasbench/adapters
COPY tools.d /opt/plasbench/tools.d
RUN mkdir -p /opt/plasbench-bin && printf '#!/bin/sh\\nexec python -m plasbench "$@"\\n' > /opt/plasbench-bin/plasbench && chmod 0755 /opt/plasbench-bin/plasbench
ENV PATH=/opt/plasbench-bin:/opt/conda/envs/plasbench/bin:$PATH PYTHONPATH=/opt/plasbench
WORKDIR /opt/plasbench
"""


def docker(exe, args, timeout=900):
    """(exit code, output) of a docker command; never raises."""
    try:
        done = subprocess.run([exe] + args, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "timed out"
    return done.returncode, (done.stdout + done.stderr).decode("utf-8", "replace")


def main():
    if not sys.platform.startswith("linux"):
        na("not Linux (nothing is started on other systems)")
    if not (os.environ.get("CI") or os.environ.get("PLASBENCH_E2E_DOCKER") == "1"):
        na("neither CI nor PLASBENCH_E2E_DOCKER=1 is set")
    exe = shutil.which("docker")
    if not exe or dr.probe(None, exe=exe)["state"] != "ready":
        na("no Docker daemon answers")
    if os.getuid() == 0:
        na("running as root: a read-only environment cannot be demonstrated")
    if docker(exe, ["pull", BASE], 1500)[0] != 0 and docker(exe, ["image", "inspect", BASE])[0] != 0:
        na("the production base image cannot be pulled here")

    tmp = Path(tempfile.mkdtemp(prefix="pbx"))
    proj = tmp / "proj"
    for name in ("plasbench", "config", "env", "scripts", "python", "adapters", "tools.d"):
        shutil.copytree(ROOT / name, proj / name, ignore=shutil.ignore_patterns("__pycache__", ".git"))
    (proj / "Dockerfile").write_text(FIXTURE.format(base=BASE), encoding="utf-8")
    tag = f"plasbench-extras-e2e:{os.getpid()}"
    res, data, logs, tmpd, dbs, extras = (tmp / n for n in ("results", "data", "logs", "tmp", "dbs", "extras"))
    environ = dict(os.environ, PLASBENCH_DOCKER_IMAGE=tag, PLASBENCH_DOCKER_PULL="never", PLASBENCH_UI_HOME=str(tmp / "ui"), PLASBENCH_DOCKER_EXTRA=str(extras), HOME=str(tmp / "home"))
    os.makedirs(environ["HOME"], exist_ok=True)
    env = {"RESULTS_DIR": str(res), "DATA_DIR": str(data), "LOG_DIR": str(logs), "TMP_DIR": str(tmpd), "PLASBENCH_DB_DIR": str(dbs), "PLASBENCH_ASSUME_ONLINE": "1"}
    uid, gid = os.getuid(), os.getgid()
    user = ["--user", f"{uid}:{gid}", "--tmpfs", "/tmp/h:rw,exec,mode=1777", "-e", "HOME=/tmp/h"]
    lines = []

    def listing():
        """What the image's environments hold: the conda-meta records and the whole file listing, as one hash line each."""
        code, out = docker(exe, ["run", "--rm", "--user", "0", tag, "sh", "-c",
                                 "find /opt/conda/envs -path '*conda-meta*' -type f | sort | xargs cat | sha256sum; find /opt/conda/envs | sort | sha256sum; find /opt/conda/envs | wc -l"])
        return out.strip().splitlines()[-3:] if code == 0 else [f"listing failed: {out[-200:]}"]

    try:
        print("build the fixture image (production layout)")
        got = dr.ensure_image(proj, assume_yes=True, out=lines.append, environ=environ, rebuild=True, exe=exe)
        check("the fixture image is built", got["ok"] and got["image"] == tag, (got, lines[-8:]))
        if not got["ok"]:
            return False
        code, out = docker(exe, ["run", "--rm"] + user + [tag, "sh", "-c", "touch /opt/conda/envs/plasbench/conda-meta/x 2>&1; echo rc=$?; command -v ps || echo no-ps"])
        check("the image environment is NOT writable by the host user (the production layout)", "rc=0" not in out, out[-200:])
        print("  info  ps in this image:", "absent" if "no-ps" in out else "present")
        before = listing()
        check("the listing of the image's environments was taken", len(before) == 3 and not before[0].startswith("listing failed"), before)

        print("the failure before the fix (micromamba against the image environment, as the host user)")
        code, out = docker(exe, ["run", "--rm"] + user + [tag, "micromamba", "install", "-y", "-p", "/opt/conda/envs/plasbench", "-c", "conda-forge", "jq"], 900)
        check("it fails with a permission / lock error", code != 0 and re.search(r"permission denied|lockfile|not writable|read-only|cannot|errno 13", out, re.I), (code, out[-400:]))
        check("and leaves the environment as it was", listing() == before)

        print("a read-only prefix is refused at once")
        t0 = time.time()
        code, out = docker(exe, ["run", "--rm"] + user + ["-e", "PLASBENCH_IN_DOCKER=1", "-e", "PLASBENCH_ASSUME_ONLINE=1", tag, "bash", "env/install_tools.sh", "--yes", "jq"], 300)
        check("exit 1 with the read-only message and no solver run (seconds, not minutes)", code == 1 and "read-only for your user" in out and time.time() - t0 < 120, (code, round(time.time() - t0), out[-500:]))
        code, out = docker(exe, ["run", "--rm"] + user + ["-e", "PLASBENCH_IN_DOCKER=1", "-e", "PLASBENCH_ASSUME_ONLINE=1", tag, "bash", "env/install_tools.sh", "--yes", "utilities,reference-annotation"], 300)
        check("a list of profiles stops after the first: one diagnosis, the second never attempted",
              code == 1 and out.count("read-only for your user") == 1 and "install-tools reference-annotation =====" not in out, (code, out[-600:]))
        check("the image environment is unchanged after the refusals", listing() == before)

        print("the real install path (dr.execute: mounts, --user, the wrapper)")
        code = dr.execute(proj, ["bash", "env/install_tools.sh", "--yes", "jq"], env, environ=environ, exe=exe, out=lines.append)
        check("install-tools jq exits 0 as the host user", code == 0, (code, lines[-12:]))
        jq = extras / "envs" / "extras" / "bin" / "jq"
        check("jq is in the persistent extras folder on the host", jq.is_file(), sorted(p.name for p in (extras / "envs").glob("*")) if (extras / "envs").exists() else "no envs dir")
        check("the image's pinned packages did not leak into the extras environment", not (extras / "envs" / "extras" / "conda-meta" / "pinned").exists())

        print("persistence: a second container")
        code = dr.execute(proj, ["sh", "-c", 'command -v jq > "$RESULTS_DIR/where.txt"; jq --version > "$RESULTS_DIR/jq.txt"; echo "$PATH" > "$RESULTS_DIR/path.txt"'], env, environ=environ, exe=exe, out=lines.append)
        check("a new container finds and runs jq", code == 0 and (res / "where.txt").read_text().strip() == str(jq) and (res / "jq.txt").read_text().startswith("jq-"), (code, lines[-5:]))
        path = (res / "path.txt").read_text().strip().split(":") if (res / "path.txt").exists() else []
        check("PATH order: extras/bin, the image, then the extras environment", str(extras / "bin") in path and str(extras / "envs" / "extras" / "bin") in path
              and path.index("/opt/conda/envs/plasbench/bin") < path.index(str(extras / "envs" / "extras" / "bin")), path)
        listing_now = dr.extras_listing(proj, environ)
        check("the extras listing for the manifest names the tool and the package version", "jq" in listing_now["tools"] and any(p.startswith("jq=") for p in listing_now["packages"]), listing_now)
        wrong = [str(p) for p in list((extras).rglob("*"))[:5000] if p.lstat().st_uid != uid]
        check("every file in the extras folder belongs to the host user", not wrong, wrong[:5])
        check("the image's conda-meta and file listing are byte-identical after the install", listing() == before)

        print("a heartbeat in an image without ps")
        code, out = docker(exe, ["run", "--rm"] + user + [tag, "bash", "-c", "set -euo pipefail; source scripts/lib.sh; r=0; run_with_heartbeat 'quiet' sh -c 'sleep 2; exit 7' || r=$?; echo RC=$r; echo \"STATS=$(proc_stats $$)\""])
        check("the watched command's status comes back and proc_stats works", "RC=7" in out and "procs=" in out, out[-300:])
    finally:
        subprocess.run([exe, "rmi", "-f", tag], capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)
    return ok


if __name__ == "__main__":
    good = main()
    print("PASS" if good else "FAIL")
    sys.exit(0 if good else 1)
