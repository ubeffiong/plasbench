#!/usr/bin/env python3
"""python/docker_diagnosis.py names the cause of a docker pull / build / start failure from its message and never invents one.

NOTE ON THE FIXTURES: the three messages marked PRODUCTION are the exact text of a failure seen on a production server (Docker Desktop 4.99.0, WSL 2 backend). Every other message is
a SAMPLE WRITTEN FROM KNOWLEDGE of the formats docker, containerd, BuildKit and Docker Desktop print; none was captured from a failing machine here. The rules match the stable fragment
of a message (for example 'read-only file system'), not a whole line, so a sample that differs in a path or an id is still recognised.
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))
import docker_diagnosis as dd  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


PROD_PULL = ('failed to extract layer (application/vnd.oci.image.layer.v1.tar+gzip sha256:2ed1956c) to overlayfs as "extract-349721246-tNeu sha256:3f5380d7": exit status 1: '
             'unpigz: skipping: <stdin>: corrupted -- incomplete deflate data')
PROD_BUILD = ('ERROR: failed to build: failed to solve: write /var/lib/desktop-containerd/daemon/io.containerd.metadata.v1.bolt/meta.db: read-only file system')
PROD_DIALOG = ('dockerd configuration error ... service command failed: daemon.json is invalid: : fork/exec /usr/local/bin/dockerd: no such file or directory')

# (label, text, cause, engine_unhealthy, retryable, build_ok, strings every result must contain somewhere in advice+commands)
TABLE = [
    ("PRODUCTION: corrupted layer (unpigz)", PROD_PULL, "corrupt_layer", False, True, False, ["docker info | grep -i -E 'proxy"]),
    ("PRODUCTION: read-only metadata database", PROD_BUILD, "read_only_filesystem", True, False, False, ["wsl --shutdown"]),
    ("PRODUCTION: dockerd configuration error dialog", PROD_DIALOG, "dockerd_config", True, False, False, ["wsl --shutdown"]),
    ("sample: unexpected EOF in a layer", "error pulling image configuration: download failed after attempts=6: unexpected EOF while extracting layer", "corrupt_layer", False, True, False, []),
    ("sample: digest mismatch", "failed to register layer: digest mismatch: expected sha256:aaa got sha256:bbb", "corrupt_layer", False, True, False, []),
    ("sample: invalid checksum", "Error response from daemon: invalid checksum digest format", "corrupt_layer", False, True, False, []),
    ("sample: read-only /var/lib/docker", "docker: Error response from daemon: mkdir /var/lib/docker/overlay2/x-init: read-only file system.", "read_only_filesystem", True, False, False, ["findmnt -T /var/lib/docker"]),
    ("sample: read-only overlay2", "failed to register layer: Error processing tar file(exit status 1): write /usr/lib/x: read-only file system", "read_only_filesystem", True, False, False, []),
    ("sample: no space left", "write /var/lib/docker/tmp/GetImageBlob1: no space left on device", "no_space", True, False, False, ["df -h /var/lib/docker"]),
    ("sample: no space in the Desktop VM", "ERROR: failed to solve: failed to copy: write /var/lib/desktop-containerd/daemon/x: no space left on device", "no_space", True, False, False, []),
    ("sample: disk quota", "Error response from daemon: disk quota exceeded", "no_space", True, False, False, []),
    ("sample: inodes", "mkdir /var/lib/docker/overlay2/abc: no inodes left on device", "inodes_exhausted", True, False, False, ["df -i"]),
    ("sample: daemon.json invalid", "unable to configure the Docker daemon with file /etc/docker/daemon.json: invalid character '}' looking for beginning of object key string", "dockerd_config", True, False, False, ["python3 -m json.tool /etc/docker/daemon.json"]),
    ("sample: cannot connect (linux)", "Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?", "daemon_stopped", True, False, False, ["sudo systemctl start docker"]),
    ("sample: error during connect (windows pipe)", 'error during connect: Get "http://%2F%2F.%2Fpipe%2FdockerDesktopLinuxEngine/v1.46/info": open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.', "daemon_stopped", True, False, False, []),
    ("sample: permission denied on the socket", "permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock: Get \"http://%2Fvar%2Frun%2Fdocker.sock/v1.24/info\": dial unix /var/run/docker.sock: connect: permission denied", "permission_socket", True, False, False, ["sudo usermod -aG docker $USER"]),
    ("sample: rate limit", "Error response from daemon: toomanyrequests: You have reached your pull rate limit.", "rate_limited", False, False, False, []),
    ("sample: pull access denied", "Error response from daemon: pull access denied for ghcr.io/ubeffiong/plasbench, repository does not exist or may require 'docker login': denied: requested access to the resource is denied", "image_not_found", False, False, True, []),
    ("sample: unauthorized (ghcr, not public)", "Error response from daemon: Head \"https://ghcr.io/v2/ubeffiong/plasbench/manifests/v0.5.5\": unauthorized", "access_denied", False, False, True, ["docker login ghcr.io"]),
    ("sample: denied (ghcr)", "Error response from daemon: error from registry: denied", "access_denied", False, False, True, []),
    ("sample: manifest unknown", "Error response from daemon: manifest for ghcr.io/ubeffiong/plasbench:v0.5.5 not found: manifest unknown: manifest unknown", "image_not_found", False, False, True, ["plasbench runtime build --yes"]),
    ("sample: no matching manifest (arm64)", "no matching manifest for linux/arm64/v8 in the manifest list entries", "platform_mismatch", False, False, True, ["plasbench runtime build --yes"]),
    ("sample: exec format error", "exec /usr/bin/sh: exec format error", "platform_mismatch", False, False, True, []),
    ("sample: x509 unknown authority", 'Get "https://ghcr.io/v2/": tls: failed to verify certificate: x509: certificate signed by unknown authority', "tls_untrusted", False, False, False, ["update-ca-certificates"]),
    ("sample: x509 unknown authority (plain)", "x509: certificate signed by unknown authority", "tls_untrusted", False, False, False, []),
    ("sample: clock skew", 'Get "https://ghcr.io/v2/": tls: failed to verify certificate: x509: certificate has expired or is not yet valid: current time 2024-01-01T00:00:00Z is before 2025-01-01', "tls_clock", False, False, False, ["date -u"]),
    ("sample: no such host", 'Get "https://ghcr.io/v2/": dial tcp: lookup ghcr.io on 127.0.0.53:53: no such host', "network", False, True, False, ["curl -sSI https://ghcr.io/v2/"]),
    ("sample: i/o timeout", 'Get "https://ghcr.io/v2/": dial tcp 140.82.121.34:443: i/o timeout', "network", False, True, False, []),
    ("sample: TLS handshake timeout", 'Get "https://ghcr.io/v2/": net/http: TLS handshake timeout', "network", False, True, False, []),
    ("sample: connection reset", "read tcp 10.0.0.2:51234->140.82.121.34:443: read: connection reset by peer", "network", False, True, False, []),
    ("sample: EOF during pull", 'error pulling image configuration: Get "https://pkg-containers.githubusercontent.com/x": EOF', "network", False, True, False, []),
    ("sample: proxyconnect", 'Get "https://ghcr.io/v2/": proxyconnect tcp: dial tcp 10.1.1.1:3128: connect: connection refused', "proxy_error", False, True, False, ["docker info | grep -i -E 'proxy'"]),
    ("sample: overlay2 invalid argument", "docker: Error response from daemon: failed to mount overlay: invalid argument", "storage_driver", True, False, False, []),
    ("sample: overlay2 driver error", "overlay2: invalid argument", "storage_driver", True, False, False, []),
    ("sample: snapshotter", "failed to create containerd task: failed to create shim task: snapshotter not loaded: overlayfs", "storage_driver", True, False, False, []),
    ("sample: containerd bolt timeout", "failed to start containerd: timeout waiting for bolt database", "storage_driver", True, False, False, []),
    ("sample: database is locked", "Error response from daemon: database is locked", "storage_driver", True, False, False, []),
    ("sample: cgroup", "docker: Error response from daemon: OCI runtime create failed: runc create failed: unable to start container process: cgroup mountpoint does not exist: unknown.", "cgroup_systemd", True, False, False, []),
    ("sample: BuildKit OOM", "ERROR: failed to solve: process \"/bin/sh -c micromamba create -n a\" did not complete successfully: exit code: 137", "build_out_of_memory", False, False, False, []),
    ("sample: ResourceExhausted", "ERROR: failed to solve: ResourceExhausted: grpc: received message larger than max", "buildkit_resources", False, False, False, []),
    ("sample: a failed build step", "ERROR: failed to solve: process \"/bin/sh -c micromamba create -n a\" did not complete successfully: exit code: 1", "build_step_failed", False, False, False, []),
    ("sample: Docker Desktop unable to start", "Docker Desktop is unable to start", "wsl_desktop_failure", True, False, False, ["wsl --update"]),
    ("sample: WSL distro terminated", "Docker Desktop - WSL distro terminated abruptly", "wsl_desktop_failure", True, False, False, []),
    ("sample: Wsl/Service hresult", "Wsl/Service/CreateInstance/CreateVm/HCS/HCS_E_SERVICE_NOT_AVAILABLE", "wsl_desktop_failure", True, False, False, []),
    ("sample: WSL integration off", "The command 'docker' could not be found in this WSL 2 distro. We recommend to activate the WSL integration in Docker Desktop settings.", "wsl_integration_off", True, False, False, ["wsl -l -v"]),
    ("sample: hung engine", "docker did not answer in time", "engine_timeout", True, False, False, []),
]


def main():
    print("classifier table (every message of the brief, three of them exact production text)")
    for label, text, cause, sick, retry, build, needles in TABLE:
        d = dd.diagnose(text, {"environment": "linux"})
        check(f"{label} -> {cause}", d["cause"] == cause, d["cause"])
        check(f"{label}: engine_unhealthy={sick} retryable={retry} build_ok={build}", (d["engine_unhealthy"], d["retryable"], d["build_ok"]) == (sick, retry, build), (d["engine_unhealthy"], d["retryable"], d["build_ok"]))
        check(f"{label}: evidence is a real line of the text, advice is a list of steps", d["evidence_lines"] and all(any(e.strip()[:60] in ln or ln.strip()[:60] in e for ln in text.splitlines() + [text]) for e in d["evidence_lines"]) and isinstance(d["advice"], list) and d["advice"], d["evidence_lines"])
        env_all = {e: dd.diagnose(text, {"environment": e}) for e in ("desktop_windows", "desktop_macos", "linux", "rootless")}
        blob = " ".join(x for e in env_all.values() for x in e["advice"] + e["commands"])
        for needle in needles:
            check(f"{label}: some environment gives {needle!r}", needle in blob)
    print("the exact production failure")
    d = dd.diagnose(PROD_PULL, {"environment": "desktop_windows", "image": "ghcr.io/ubeffiong/plasbench:v0.5.5"})
    check("pull: corrupted layer, retryable, a build is NOT the remedy, evidence names unpigz", d["cause"] == "corrupt_layer" and d["retryable"] and not d["build_ok"] and "unpigz" in " ".join(d["evidence_lines"]))
    check("pull: advice says not to build locally", any("Do NOT build" in s for s in d["advice"]))
    check("pull: the partial image is removed only as a last resort with its consequence", d["last_resort"] and d["last_resort"][0]["command"] == "docker image rm ghcr.io/ubeffiong/plasbench:v0.5.5" and "deletes" in d["last_resort"][0]["warning"])
    check("pull: Desktop advice includes wsl --shutdown and the Clean / Purge data warning", any("Purge" in x["command"] and "ALL images" in x["warning"] for x in d["last_resort"]))
    d = dd.diagnose(PROD_BUILD, {"environment": "desktop_windows"})
    check("build: read-only, engine unhealthy, exit 20 convention (user_action), no build", d["cause"] == "read_only_filesystem" and d["engine_unhealthy"] and d["user_action"] and not d["build_ok"] and not d["retryable"])
    check("build: Desktop advice quits Desktop, wsl --shutdown, restarts", any("wsl --shutdown" in s for s in d["advice"]) and "wsl --shutdown" in d["commands"])
    d = dd.diagnose(PROD_DIALOG, {"environment": "desktop_windows"})
    check("dialog: the wording 'daemon.json is invalid' is explained as a missing dockerd (damaged install)", d["cause"] == "dockerd_config" and any("MISSING" in s and "dockerd" in s for s in d["advice"]) and d["engine_unhealthy"])
    combined = "\n".join([PROD_PULL, PROD_BUILD, PROD_DIALOG])
    d = dd.diagnose(combined, {})
    check("all three together: the engine damage is the verdict, the others are listed in `also`", d["cause"] == "dockerd_config" and "read_only_filesystem" in d["also"] and "corrupt_layer" in d["also"], (d["cause"], d["also"]))
    d = dd.diagnose(PROD_BUILD, {})
    check("without any context desktop-containerd is recognised as Docker Desktop (both Desktop blocks, labelled)", d["environment"] == "desktop" and any(s.startswith("On Docker Desktop on Windows") for s in d["advice"]) and any(s.startswith("On Docker Desktop on macOS") for s in d["advice"]))
    d = dd.diagnose(PROD_BUILD, {"env": {"kind": "wsl2", "desktop_installed": True}})
    check("WSL 2 with Docker Desktop installed -> the Windows advice only", d["environment"] == "desktop_windows" and not any("macOS" in s for s in d["advice"]))

    print("read-only: the safe order on a Linux server")
    d = dd.diagnose("mkdir /var/lib/docker/overlay2/x: read-only file system", {"environment": "linux"})
    cmds = d["commands"]
    for want in ("docker info | grep -i 'docker root dir'", "df -h /var/lib/docker", "findmnt -T /var/lib/docker -o TARGET,SOURCE,FSTYPE,OPTIONS", "mount | grep ' /var/lib/docker'",
                 "dmesg | grep -i -E 'ext4|xfs|I/O error|remount' | tail -30", "sudo journalctl -u docker -u containerd --since '1 hour ago' | tail -50", "sudo systemctl stop docker docker.socket containerd"):
        check(f"command shown: {want}", want in cmds)
    order = " ".join(d["advice"])
    check("safe order: free space, stop docker, fsck while unmounted, remount rw, restart", order.index("free space if") < order.index("systemctl stop docker") < order.index("fsck") < order.index("remount read-write") < order.index("systemctl start docker"))
    check("never fsck a mounted filesystem is said", "UNMOUNTED" in order and "never fsck a mounted" in order)
    check("data-destroying steps are last resorts with consent text, not in `commands`", {x["command"] for x in d["last_resort"]} >= {"sudo docker system prune", "sudo mv /var/lib/docker /var/lib/docker.old"}
          and all("ALL" in x["warning"] or "removes" in x["warning"] for x in d["last_resort"]) and not any("prune" in c or "mv /var/lib" in c for c in cmds))
    print("safety rules for every rule and every environment")
    texts = [t for _, t, *_ in TABLE]
    for text in texts:
        for env in ("desktop_windows", "desktop_macos", "linux", "rootless", "unknown", "desktop"):
            d = dd.diagnose(text, {"environment": env})
            every = " ".join(d["commands"] + [x["command"] for x in d["last_resort"]])
            check_ok = "wsl --unregister" not in every or all(c.strip() == "wsl --unregister docker-desktop" for c in d["commands"] + [x["command"] for x in d["last_resort"]] if "wsl --unregister" in c)
            if not check_ok:
                check(f"only docker-desktop is ever unregistered ({env}, {text[:30]})", False, every)
            bad = [c for c in d["commands"] if re.search(r"\b(rm -r|rm -f|system prune|volume prune|image rm|builder prune|--unregister|mv /var/lib|fsck|mkfs)\b|mount -o remount", c)]
            if bad:
                check(f"`commands` never holds a deleting or moving command ({env}, {text[:30]})", False, bad)
    check("no rule suggests unregistering Ubuntu or any other distribution", not any(re.search(r"--unregister (?!docker-desktop)", " ".join(x["command"] for x in dd.diagnose(t, {"environment": "desktop_windows"})["last_resort"])) for t in texts))
    check("every unregister warning says docker-desktop only and that it is recreated", all("ONLY the `docker-desktop`" in x["warning"] and "recreates" in x["warning"] for t in texts for x in dd.diagnose(t, {"environment": "desktop_windows"})["last_resort"] if "--unregister" in x["command"]))
    check("only the three 'image unavailable' causes allow a build", {r["cause"] for r in dd.RULES if r.get("build")} == {"image_not_found", "access_denied", "platform_mismatch"})
    check("every engine/disk/storage/corruption cause refuses a build", all(not dd.diagnose(t, {})["build_ok"] for label, t, c, *_ in TABLE if c in ("read_only_filesystem", "no_space", "inodes_exhausted", "storage_driver", "corrupt_layer", "dockerd_config", "daemon_stopped", "network")))

    print("unknown is said to be unknown")
    log = "\n".join(f"line {i}" for i in range(40))
    d = dd.diagnose(log, {})
    check("unknown: cause unknown, confidence low, last 15 lines as evidence, no build, not unhealthy", d["cause"] == "unknown" and d["confidence"] == "low" and d["evidence_lines"] == [f"line {i}" for i in range(25, 40)] and not d["build_ok"] and not d["engine_unhealthy"])
    check("unknown: says it does not guess and does not build", any("will not guess" in s and "does not build" in s for s in d["advice"]))
    check("empty text is unknown too", dd.diagnose("", {})["cause"] == "unknown" and dd.diagnose(None, {})["cause"] == "unknown")
    check("'permission denied' on a folder is NOT mistaken for the registry's `denied:`", dd.diagnose("open /x: permission denied: not allowed", {})["cause"] == "unknown")

    print("environments")
    for kind, want in (({"kind": "macos"}, "desktop_macos"), ({"kind": "windows"}, "desktop_windows"), ({"kind": "linux"}, "linux"), ({"kind": "wsl2"}, "linux"), ({"kind": "wsl2", "desktop_installed": True}, "desktop_windows")):
        check(f"environment {kind} -> {want}", dd.environment_kind("", {"env": kind}) == want, dd.environment_kind("", {"env": kind}))
    check("rootless from docker info", dd.environment_kind("", {"env": {"kind": "linux"}, "docker_info": "Security Options: name=rootless"}) == "rootless")
    check("rootless advice differs from the system engine's", dd.diagnose("Cannot connect to the Docker daemon", {"environment": "rootless"})["commands"] != dd.diagnose("Cannot connect to the Docker daemon", {"environment": "linux"})["commands"])
    d = dd.diagnose("no space left on device", {"environment": "unknown"})
    check("unknown environment: all three blocks, each labelled", sum(1 for s in d["advice"] if s.startswith("On ")) >= 3)
    check("daemon stopped points to the existing #142 start command on Windows", "plasbench install-tools docker --start" in dd.diagnose("Cannot connect to the Docker daemon", {"environment": "desktop_windows"})["commands"])
    check("permission denied reuses the existing state's command", "plasbench install-tools docker" in dd.diagnose("permission denied while trying to connect to the Docker daemon socket", {"environment": "desktop_windows"})["commands"])
    check("render() shows evidence, steps, commands and the last-resort warning", all(w in dd.render(dd.diagnose(PROD_BUILD, {"environment": "linux"})) for w in ("evidence:", "1.", "Commands to run yourself", "Last resort ONLY", "WARNING")))
    check("causes() lists every rule plus unknown", set(dd.causes()) == {r["cause"] for r in dd.RULES} | {"unknown"})

    print("command line")
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "pull.log"
        log.write_bytes(PROD_BUILD.encode())
        done = subprocess.run([sys.executable, "-I", str(ROOT / "python" / "docker_diagnosis.py"), str(log), "--environment", "linux", "--format", "json"], capture_output=True, text=True, timeout=60)
        out = json.loads(done.stdout) if done.returncode == 0 else {}
        check("python -I docker_diagnosis.py FILE --format json", done.returncode == 0 and out.get("cause") == "read_only_filesystem", done.stderr[-200:])
        done = subprocess.run([sys.executable, "-I", str(ROOT / "python" / "docker_diagnosis.py"), str(log)], capture_output=True, text=True, timeout=60)
        check("text format prints the diagnosis", done.returncode == 0 and "Diagnosis:" in done.stdout)
    src = (ROOT / "python" / "docker_diagnosis.py").read_text(encoding="utf-8")
    check("stdlib only, Python 3.9 safe (from __future__ annotations, no write_text/read_text(newline=))", "from __future__ import annotations" in src and "write_text" not in src and "newline=" not in src and not re.search(r"^import (?!argparse|json|re|sys)", src, re.M))
    return not FAILED


if __name__ == "__main__":
    good = main()
    print("ALL DOCKER DIAGNOSIS TESTS PASSED" if good else "FAILED: " + "; ".join(FAILED))
    sys.exit(0 if good else 1)
