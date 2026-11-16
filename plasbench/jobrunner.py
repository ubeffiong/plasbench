#!/usr/bin/env python3
"""The detached runner behind every job started from `plasbench ui`.

A run used to be a child of the window's server: when the server stopped (the terminal was closed, the machine slept, the window was quit) the run went with it, or was left
behind with nothing watching it. The server now starts each job through this runner instead:

    python -m plasbench.jobrunner JOBDIR JOB_ID CWD -- COMMAND ...

The runner is detached (its own session or process group, no console of its own), so it survives the server. It starts the command, writes the command's output to JOBDIR/JOB_ID.log,
and keeps three small files beside the log so ANY server, including a new one started later, can find the run again:

    JOB_ID.pid     {"runner": pid, "child": pid, "started": t}      written once the command has started
    JOB_ID.alive   touched every few seconds                      a fresh file means the run is still going (a stale one cannot be confused with a reused pid)
    JOB_ID.exit    {"code": n, "ended": t}                       written, atomically, when the command ends however it ends (not when the runner itself is killed)

Answers typed in the window are appended to JOB_ID.in as JSON lines {"text": ..., "shown": ...}; the runner forwards each complete line's text to the command's standard input and
records `[you] <shown>` in the log (shown is masked for a secret), so a command that asks a question keeps working after the window reconnects.

The runner is the ONLY writer of the log while the command runs: it reads the command's output through a pipe and appends it itself. (Two writers on one file do not share an end-of-file
position on Windows, so one would overwrite the other.) Standard library only.
"""
import json
import os
import subprocess
import sys
import threading
import time

HEARTBEAT_SECONDS = 4
STALE_SECONDS = 20          # a heartbeat older than this means the runner is gone
POLL_SECONDS = 0.25


def paths(job_dir, job_id):
    base = os.path.join(job_dir, job_id)
    return {"log": base + ".log", "pid": base + ".pid", "alive": base + ".alive", "exit": base + ".exit", "input": base + ".in"}


def _write_json(path, payload):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    os.replace(tmp, path)


def _touch(path):
    try:
        with open(path, "a"):
            os.utime(path, None)
    except OSError:
        pass


def read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def is_alive(job_dir, job_id, now=None):
    """True while the runner's heartbeat is fresh and it has not recorded an exit."""
    p = paths(job_dir, job_id)
    if os.path.exists(p["exit"]):
        return False
    try:
        age = (now or time.time()) - os.path.getmtime(p["alive"])
    except OSError:
        return False
    return age < STALE_SECONDS


def run(job_dir, job_id, cwd, command):
    p = paths(job_dir, job_id)
    _touch(p["alive"])
    _touch(p["input"])
    log = open(p["log"], "ab")
    log_lock = threading.Lock()

    def write_log(data):
        with log_lock:
            log.write(data)
            log.flush()
    kwargs = {}
    if os.name == "nt":
        # a hidden console that the command and everything it starts share: a console program started from a detached process would otherwise open a window of its own
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | 0x08000000   # CREATE_NO_WINDOW
    try:
        proc = subprocess.Popen(command, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kwargs)
    except OSError as exc:
        write_log(f"\n[PlasBench] ERROR: could not start the command: {exc}\n".encode())
        log.close()
        _write_json(p["exit"], {"code": 127, "ended": time.time()})
        return 127
    _write_json(p["pid"], {"runner": os.getpid(), "child": proc.pid, "started": time.time()})
    done = threading.Event()

    def copy_output():
        while True:
            chunk = os.read(proc.stdout.fileno(), 65536)
            if not chunk:
                break
            write_log(chunk)

    reader = threading.Thread(target=copy_output, daemon=True)
    reader.start()

    def pump():
        offset, last_beat = 0, 0.0
        while not done.is_set():
            if time.time() - last_beat >= HEARTBEAT_SECONDS:
                _touch(p["alive"])
                last_beat = time.time()
            try:
                size = os.path.getsize(p["input"])
            except OSError:
                size = 0
            if size > offset:
                with open(p["input"], "rb") as handle:
                    handle.seek(offset)
                    chunk = handle.read(size - offset)
                end = chunk.rfind(b"\n")
                if end >= 0:   # only complete lines are forwarded
                    for line in chunk[:end + 1].splitlines():
                        try:
                            entry = json.loads(line.decode("utf-8"))
                            text, shown = str(entry["text"]), str(entry.get("shown", entry["text"]))
                        except (ValueError, KeyError, UnicodeDecodeError):
                            continue
                        try:
                            proc.stdin.write((text + "\n").encode("utf-8"))
                            proc.stdin.flush()
                        except (OSError, ValueError):
                            pass
                        write_log(f"\n[you] {shown}\n".encode("utf-8"))
                    offset += end + 1
            done.wait(POLL_SECONDS)

    thread = threading.Thread(target=pump, daemon=True)
    thread.start()
    code = proc.wait()
    reader.join(timeout=5)   # everything the command printed is in the log before the exit is recorded
    done.set()
    thread.join(timeout=2)
    try:
        proc.stdin.close()
    except (OSError, ValueError):
        pass
    log.close()
    _write_json(p["exit"], {"code": code, "ended": time.time()})
    return code


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--" not in argv or argv.index("--") != 3:
        sys.stderr.write("usage: python -m plasbench.jobrunner JOBDIR JOB_ID CWD -- COMMAND ...\n")
        return 2
    job_dir, job_id, cwd = argv[:3]
    return run(job_dir, job_id, cwd, argv[4:])


if __name__ == "__main__":
    sys.exit(main())
