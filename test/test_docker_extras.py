#!/usr/bin/env python3
"""Docker-mode extras, the Python side: the runtime wrapper's PATH precedence and the extras variables, the pull/build heartbeat (once a minute, not twice), the
read-only-environment classifier, the source-install guard, the container-aware WSL notes and limits, the Docker line of `plasbench check` inside a container, and the
MOB-suite database arguments. The shell side is test_docker_extras.sh; the real container is test_docker_extras_e2e.py."""
import os
import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "python"))
from plasbench import computer_info as ci, docker_runtime as dr  # noqa: E402
import docker_setup as ds  # noqa: E402
import install_diagnosis as idg  # noqa: E402
import annotate_reference as ar  # noqa: E402
import preflight_resources as pf  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


print("the runtime wrapper")
FS = dict(exists=lambda p: True, isdir=lambda p: True, makedirs=lambda *a, **k: None)
argv, _env, _plan = dr.build_run_argv(ROOT, ["true"], {"DATA_DIR": "/vt/d", "RESULTS_DIR": "/vt/r", "LOG_DIR": "/vt/l", "TMP_DIR": "/vt/t", "SAMPLE_SHEET": "/vt/s.tsv", "PLASBENCH_DB_DIR": "/vt/db"}, image="img:1", name="n", kind="posix", uid=1000, gid=1000,
                                      extra="/vt/extras", environ={"PATH": "/bin"}, **FS)
text = " ".join(argv)
check("the extras environment is named for the container", "PLASBENCH_EXTRA_PREFIX=/vt/extras/envs/extras" in text, text[-400:])
check("the extras folder is mounted read-write at its own path", "-v /vt/extras:/vt/extras" in text and "-v /vt/extras:/vt/extras:ro" not in text)
wrapper = argv[argv.index("-c") + 1]
check("PATH order: extras/bin, the image's PATH, then the extras environment", wrapper.index("$PLASBENCH_EXTRA_BIN") < wrapper.index("$PATH") < wrapper.index("$PLASBENCH_EXTRA_PREFIX/bin"), wrapper)
check("HOME is a writable scratch folder", f"HOME={dr.CONTAINER_HOME}" in text and f"{dr.CONTAINER_HOME}:rw" in text)
check("conda variables point into extras", "CONDA_PKGS_DIRS=/vt/extras/pkgs" in text and "CONDA_ENVS_PATH=/vt/extras/envs:/opt/conda/envs" in text)
import subprocess  # noqa: E402
if os.name != "nt":
    out = subprocess.run(["sh", "-c", wrapper, "x", "sh", "-c", "echo $PATH"], env={"PATH": "/usr/bin:/bin", "PLASBENCH_EXTRA_BIN": "/e/bin", "PLASBENCH_EXTRA_PREFIX": "/e/envs/extras"},
                         capture_output=True, text=True).stdout.strip()
    check("the wrapper builds that PATH when run", out == "/e/bin:/usr/bin:/bin:/e/envs/extras/bin", out)

print("the pull heartbeat (once a minute)")
import inspect  # noqa: E402
check("stream() defaults to one notice a minute", inspect.signature(dr.stream).parameters["heartbeat"].default == 60.0)
src = inspect.getsource(dr.ensure_image)
check("pull and build pass the minute interval, not 30 s", "30.0" not in src and src.count("60.0") >= 2, re.findall(r".*(?:30|60)\.0.*", src))
lines = []
code, _tail = dr.stream([sys.executable, "-c", "import time; time.sleep(2.6)"], out=lines.append, heartbeat=1.0, what="pulling x")
beats = [l for l in lines if "still working" in l]
check("a quiet command gets at most one notice per interval", code == 0 and 1 <= len(beats) <= 2, (code, beats))

print("the read-only environment classifier")
d = idg.diagnose("error    libmamba Could not open lockfile '/opt/conda/envs/plasbench/conda-meta/conda-meta.lock'", "/h/extras", container=True)
check("a lockfile error in a container is classified with the path and the extras folder", d and d["cause"] == "read_only_environment" and d["path"].endswith("conda-meta.lock")
      and "/h/extras" in d["advice"] and "read-only" in d["title"], d)
d = idg.diagnose("mv: cannot move '/opt/conda/envs/mobsuite/x/databases' to 'y': Permission denied", "", container=True)
check("an mv error names the folder", d and d["path"] == "/opt/conda/envs/mobsuite/x/databases", d)
check("an unrelated error is not classified", idg.diagnose("HTTP 503 from conda.anaconda.org", "", container=True) is None)
d = idg.diagnose("Permission denied", "", container=False)
check("outside a container the advice does not mention the extras", d and "extras" not in d["advice"], d)

print("the source-install guard")
import source_install as si  # noqa: E402
with tempfile.TemporaryDirectory() as tmp:
    ro = Path(tmp) / "image" / "envs" / "plasbench"
    (ro / "bin").mkdir(parents=True)
    layout = si.Layout(ro, "plasbench", "gplas2")
    can_block = os.name != "nt" and hasattr(os, "geteuid") and os.geteuid() != 0
    if can_block:
        os.chmod(ro, 0o555), os.chmod(ro / "bin", 0o555), os.chmod(ro.parent, 0o555)
        try:
            check("a read-only prefix is found before anything is built", si._first_unwritable(layout) != "", si._first_unwritable(layout))
        finally:
            os.chmod(ro.parent, 0o755), os.chmod(ro, 0o755), os.chmod(ro / "bin", 0o755)
    else:
        print("  n/a   read-only prefix check: this user can write to a read-only folder here")
    check("a writable prefix passes", si._first_unwritable(layout) == "", si._first_unwritable(layout))

print("inside a container")
old = os.environ.get("PLASBENCH_IN_DOCKER")
os.environ["PLASBENCH_IN_DOCKER"] = "1"
try:
    check("preflight does not treat a container as WSL (no Windows-drive probe)", pf._is_wsl() is False)
    from plasbench import platform_info as pi  # noqa: E402
    check("platform_info.in_wsl is False in a container", pi.in_wsl() is False)
    env = ci.environment("linux", meminfo="MemTotal: 8000000 kB\nMemAvailable: 4000000 kB\n", cpuinfo="processor : 0\n", cgroups=None, affinity=2, in_wsl=False)
    check("container limits are reported with where to change them", any("Settings > Resources" in x["text"] for x in env["limits"]) or os.name == "nt", env["limits"])
    check("no WSL limit text in a container", not any(x["what"] == "wsl" for x in env["limits"]))
    st = {"state": "in_container", "version": "", "context": "", "server_version": ""}
    line = ds.check_line(st)
    check("the Docker line inside a container has no 'Next:' action", "Next:" not in line and "container" in line, line)
finally:
    if old is None:
        os.environ.pop("PLASBENCH_IN_DOCKER", None)
    else:
        os.environ["PLASBENCH_IN_DOCKER"] = old
env = ci.environment("linux", meminfo="MemTotal: 8000000 kB\nMemAvailable: 4000000 kB\n", cpuinfo="processor : 0\n", cgroups={"memory": None, "cpus": None, "source": None}, affinity=2, in_wsl=True)
check("host WSL behaviour is unchanged", any(x["what"] == "wsl" for x in env["limits"]))
st = {"state": "not_installed", "version": "", "context": "", "server_version": ""}
try:
    check("outside a container the check line still names the next command", "plasbench install-tools docker" in ds.check_line(dict(st)))
except Exception as exc:  # noqa: BLE001
    check("outside a container the check line still works", False, exc)

print("MOB-suite database arguments")
with tempfile.TemporaryDirectory() as tmp:
    store = Path(tmp) / "mob_suite" / "databases"
    store.mkdir(parents=True)
    e = {"PLASBENCH_IN_DOCKER": "1", "PLASBENCH_DB_DIR": tmp}
    check("an empty store gives no -d", ar.mob_db_args(e) == [])
    for n in ("status.txt", "ncbi_plasmid_full_seqs.fas", "ncbi_plasmid_full_seqs.fas.msh", "repetitive.dna.fas"):
        (store / n).write_text("x")
    check("a complete store in a container gives -d <store>", ar.mob_db_args(e) == ["-d", str(store)])
    check("outside a container never", ar.mob_db_args({"PLASBENCH_DB_DIR": tmp}) == [])

print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
