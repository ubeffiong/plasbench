#!/usr/bin/env python3
"""KEEP_AWAKE (python/keep_awake.py, python/run_sentinel.py): the run asks the operating system not to sleep while it is active and lets go when it ends or dies.

Fake `powershell.exe`, `systemd-inhibit` and `caffeinate` programs on PATH record how they were started and stopped, so no real power request is made:
  - WSL: powershell.exe is started with an encoded script, reports it is holding, and ends when its input closes (the run ended, or the sentinel was killed)
  - Linux: systemd-inhibit --what=sleep around a loop that ends with the run's pid;  macOS: caffeinate -i -w <pid>
  - KEEP_AWAKE=0 starts nothing; WSL without Windows interop prints the powercfg note and does not fail
  - the sentinel ends (and releases) when the run's pid disappears: a crash never leaves the machine unable to sleep
The real Windows call was verified separately through WSL (see docs/PERFORMANCE_AUDIT.md)."""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


if os.name == "nt" or not Path("/bin/sh").exists():
    print("skipped: needs a POSIX shell for the fake tools")
    sys.exit(0)


def shim(directory, name, body):
    path = Path(directory) / name
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)


def wait_for(predicate, seconds=15):
    end = time.time() + seconds
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.1)
    return predicate()


def read(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


def start_sentinel(env, results, pid):
    Path(results).mkdir(parents=True, exist_ok=True)
    full = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", **env)
    return subprocess.Popen([sys.executable, str(ROOT / "python" / "run_sentinel.py"), "--pid", str(pid), "--results-dir", str(results), "--interval", "0.2"],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=full)


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    bindir, log = tmp / "bin", tmp / "log"
    bindir.mkdir()
    log.mkdir()
    base = {"PATH": str(bindir) + os.pathsep + "/usr/bin:/bin"}

    # ---------------- WSL: fake powershell.exe ----------------
    shim(bindir, "powershell.exe", f'echo "start $*" >> {log}/ps.txt\necho PB_KEEP_AWAKE_ON\ncat > /dev/null\necho stopped >> {log}/ps.txt\n')
    runner = subprocess.Popen(["sleep", "60"])                       # the "run"
    sentinel = start_sentinel(dict(base, PB_KEEP_AWAKE_PLATFORM="wsl"), tmp / "r1", runner.pid)
    note = sentinel.stdout.readline().strip()
    check("the plain note is printed once the request is held", "keeping this computer awake while the run is active; it can still turn the screen off" in note, note)
    started = read(log / "ps.txt")
    check("powershell.exe was started with an encoded command (no quoting trouble)", "-EncodedCommand" in started and "-NonInteractive" in started, started)
    runner.kill()
    runner.wait()
    check("the sentinel ends when the run's process disappears (a crash)", wait_for(lambda: sentinel.poll() is not None))
    check("... and the helper was told to stop (its input closed)", wait_for(lambda: "stopped" in read(log / "ps.txt")))
    events = [json.loads(line) for line in read(tmp / "r1" / "run_events.jsonl").splitlines()]
    check("keep_awake and keep_awake_released events are recorded",
          bool(events) and events[0]["event"] == "keep_awake" and any(e["event"] == "keep_awake_released" for e in events), events)

    # the sentinel itself killed hard: the helper's input closes, so it ends too
    (log / "ps.txt").unlink()
    runner = subprocess.Popen(["sleep", "60"])
    sentinel = start_sentinel(dict(base, PB_KEEP_AWAKE_PLATFORM="wsl"), tmp / "r1b", runner.pid)
    sentinel.stdout.readline()
    sentinel.send_signal(signal.SIGKILL)
    sentinel.wait()
    check("a sentinel killed with SIGKILL still releases the request (the helper sees its input close)", wait_for(lambda: "stopped" in read(log / "ps.txt")))
    runner.kill()
    runner.wait()

    # ---------------- WSL without Windows interop ----------------
    nointerop = tmp / "bin_none"
    nointerop.mkdir()
    sentinel = start_sentinel({"PATH": str(nointerop) + os.pathsep + "/usr/bin:/bin", "PB_KEEP_AWAKE_PLATFORM": "wsl"}, tmp / "r2", os.getpid())
    note = sentinel.stdout.readline().strip()
    check("WSL without Windows interop says it cannot prevent sleep and names the powercfg setting",
          "cannot prevent sleep here" in note and "powercfg /change standby-timeout-ac 0" in note, note)
    sentinel.send_signal(signal.SIGTERM)
    check("... and does not fail (exit 0)", sentinel.wait(15) == 0)

    # ---------------- KEEP_AWAKE=0 ----------------
    if (log / "ps.txt").exists():
        (log / "ps.txt").unlink()
    sentinel = start_sentinel(dict(base, PB_KEEP_AWAKE_PLATFORM="wsl", KEEP_AWAKE="0"), tmp / "r3", os.getpid())
    note = sentinel.stdout.readline().strip()
    sentinel.send_signal(signal.SIGTERM)
    sentinel.wait(15)
    check("KEEP_AWAKE=0 asks for nothing and says so", "KEEP_AWAKE=0" in note and not (log / "ps.txt").exists(), note)

    # ---------------- Linux: systemd-inhibit ----------------
    shim(bindir, "systemd-inhibit", f'echo "inhibit $*" >> {log}/inh.txt\nwhile [ "$1" != "sh" ] && [ $# -gt 0 ]; do shift; done\nexec "$@"\n')
    runner = subprocess.Popen(["sleep", "3"])
    sentinel = start_sentinel(dict(base, PB_KEEP_AWAKE_PLATFORM="linux"), tmp / "r4", runner.pid)
    note = sentinel.stdout.readline().strip()
    inh = read(log / "inh.txt")
    check("Linux: systemd-inhibit --what=sleep is used, and not idle or shutdown", "--what=sleep" in inh and "idle" not in inh and "shutdown" not in inh, inh)
    check("Linux: the note is printed", "keeping this computer awake" in note, note)
    check("Linux: the sentinel ends by itself when the run ends", wait_for(lambda: sentinel.poll() is not None, 25))
    runner.wait()

    # ---------------- macOS: caffeinate ----------------
    shim(bindir, "caffeinate", f'echo "caffeinate $*" >> {log}/caf.txt\nsleep 30\n')
    runner = subprocess.Popen(["sleep", "60"])
    sentinel = start_sentinel(dict(base, PB_KEEP_AWAKE_PLATFORM="macos"), tmp / "r5", runner.pid)
    sentinel.stdout.readline()
    wait_for(lambda: read(log / "caf.txt"))
    caf = read(log / "caf.txt")
    check("macOS: caffeinate -i (idle sleep only; the display may still sleep) watches the run's pid", f"-i -w {runner.pid}" in caf and "-d" not in caf, caf)
    runner.kill()
    runner.wait()
    check("macOS: the sentinel ends with the run", wait_for(lambda: sentinel.poll() is not None))

    # ---------------- the shell side and the settings ----------------
    lib = read(ROOT / "scripts" / "lib.sh")
    run_all = read(ROOT / "scripts" / "run_all.sh")
    check("run_all.sh starts the sentinel after the run lock and stops it before finishing", "_pb_sentinel_start" in run_all and "_pb_sentinel_stop" in run_all)
    check("the sentinel's output goes to a file, never to the console pipe", '> "$note_file"' in lib)
    check("KEEP_AWAKE defaults to 1 in config.sh", 'KEEP_AWAKE="${KEEP_AWAKE:-1}"' in read(ROOT / "config" / "config.sh"))
    check("KEEP_AWAKE is listed in config/ai_settable.tsv as a flag",
          any(line.split("\t")[:3] == ["KEEP_AWAKE", "flag", "0|1"] for line in read(ROOT / "config" / "ai_settable.tsv").splitlines()))

print("\nall keep-awake checks passed" if ok else "\nFAILED")
sys.exit(0 if ok else 1)
