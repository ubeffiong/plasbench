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
    JOB_ID.activity                                              touched when the command prints something other than a "still working" notice: how long ago says whether it is stalled

The command runs in its own process group (its own session on POSIX), recorded as "pgid" in JOB_ID.pid. Cancelling the run, and the runner receiving SIGTERM, stop the whole group;
a server that starts later and finds the runner gone (it was killed with SIGKILL, which nothing can catch) stops the orphaned group and refuses to start or resume the run while any member is alive.

Answers typed in the window are appended to JOB_ID.in as JSON lines {"text": ..., "shown": ...}; the runner forwards each complete line's text to the command's standard input and
records `[you] <shown>` in the log (shown is masked for a secret), so a command that asks a question keeps working after the window reconnects.

The runner is the ONLY writer of the log while the command runs: it reads the command's output through a pipe and appends it itself. (Two writers on one file do not share an end-of-file
position on Windows, so one would overwrite the other.) Standard library only.
"""
import json
import os
import signal
import subprocess
import sys
import threading
import time

HEARTBEAT_SECONDS = 4
STALE_SECONDS = 20          # a heartbeat older than this means the runner is gone
POLL_SECONDS = 0.25
STALL_SECONDS_DEFAULT = 600  # no output for this long: the run is shown as stalled (PLASBENCH_STALL_SECONDS overrides; 0 turns it off)
KILL_GRACE_SECONDS = 8       # between SIGTERM and SIGKILL when stopping a group


def stall_seconds():
    """The no-output window after which a running job is called stalled (environment PLASBENCH_STALL_SECONDS, default 10 minutes, 0 = never)."""
    try:
        return max(0.0, float(os.environ.get("PLASBENCH_STALL_SECONDS", STALL_SECONDS_DEFAULT)))
    except ValueError:
        return float(STALL_SECONDS_DEFAULT)


def paths(job_dir, job_id):
    base = os.path.join(job_dir, job_id)
    return {"log": base + ".log", "pid": base + ".pid", "alive": base + ".alive", "exit": base + ".exit", "input": base + ".in", "activity": base + ".activity"}


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


def pid_alive(pid):
    """True while a process with this id exists (a zombie that nobody reaped counts as gone on POSIX)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok) and code.value == 259   # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:   # a zombie is dead for our purposes
        with open(f"/proc/{pid}/stat", "rb") as handle:
            return handle.read().rsplit(b")", 1)[1].split()[0] != b"Z"
    except (OSError, IndexError):
        return True


def group_alive(pgid):
    """True while any process of this process group is alive (POSIX; on Windows the leader's own pid is the only member that can be checked)."""
    try:
        pgid = int(pgid)
    except (TypeError, ValueError):
        return False
    if pgid <= 0:
        return False
    if os.name == "nt":
        return pid_alive(pgid)
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return any(_group_member_alive(pid, pgid) for pid in _pids())


def _pids():
    try:
        return [int(n) for n in os.listdir("/proc") if n.isdigit()]
    except OSError:
        return []


def _group_member_alive(pid, pgid):
    try:
        with open(f"/proc/{pid}/stat", "rb") as handle:
            fields = handle.read().rsplit(b")", 1)[1].split()
        return int(fields[2]) == pgid and fields[0] != b"Z"
    except (OSError, IndexError, ValueError):
        return False


def kill_group(pgid, grace=KILL_GRACE_SECONDS):
    """Stop every member of the process group: SIGTERM, then SIGKILL after `grace` seconds. Returns True when none is left. On Windows the tree is stopped with taskkill."""
    try:
        pgid = int(pgid)
    except (TypeError, ValueError):
        return True
    if pgid <= 0:
        return True
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pgid)], capture_output=True)
        return not pid_alive(pgid)
    for sig, wait in ((signal.SIGTERM, grace), (signal.SIGKILL, 3)):
        try:
            os.killpg(pgid, sig)
        except (ProcessLookupError, PermissionError):
            break
        end = time.time() + wait
        while time.time() < end and group_alive(pgid):
            time.sleep(0.1)
        if not group_alive(pgid):
            return True
    return not group_alive(pgid)


def stop_job_container(job_dir, job_id):
    """A job that runs its tools in Docker left JOB_ID.container (plasbench/docker_runtime.py): `docker stop` it, because stopping the docker client alone can leave the container going.
    Starts nothing for a job without that file. Never raises."""
    try:
        from . import docker_runtime
        return docker_runtime.stop_for_job(job_dir, job_id)
    except Exception:   # noqa: BLE001 - cancelling must always go on
        return False


def run_state(job_dir, job_id):
    """What is left of a run: whether its runner and any member of its process group are alive (read from JOB_ID.pid)."""
    info = read_json(paths(job_dir, job_id)["pid"]) or {}
    runner_alive = pid_alive(info.get("runner")) if info.get("runner") else False
    return {"runner": info.get("runner"), "pgid": info.get("pgid"), "runner_alive": runner_alive,
            "group_alive": group_alive(info.get("pgid")) if info.get("pgid") else False}


def idle_seconds(job_dir, job_id, now=None):
    """Seconds since the command last printed anything (not counting 'still working' notices), or None when unknown."""
    p = paths(job_dir, job_id)
    for key in ("activity", "log"):
        try:
            return max(0.0, (now or time.time()) - os.path.getmtime(p[key]))
        except OSError:
            continue
    return None


def is_stalled(job_dir, job_id, now=None, window=None):
    """True when the run is going (a fresh heartbeat, no exit) but has printed nothing for the stall window: a hung or frozen tool still has a live runner."""
    window = stall_seconds() if window is None else window
    if window <= 0 or not is_alive(job_dir, job_id, now):
        return False
    idle = idle_seconds(job_dir, job_id, now)
    return idle is not None and idle > window


ACTIVE_SECONDS = 180     # a file written this recently means the run is working
ACTIVITY_MAX_ENTRIES = 2000
ACTIVITY_MAX_SECONDS = 2.0


def recent_activity(roots, now=None, max_entries=ACTIVITY_MAX_ENTRIES, max_seconds=ACTIVITY_MAX_SECONDS, limit=12, active_seconds=ACTIVE_SECONDS):
    """The files modified most recently under `roots` (never following symlinks, at most `max_entries` entries or `max_seconds` seconds of walking).

    Returns {"status": "active"|"quiet", "files": [{"root", "path", "size", "age_seconds"}], "walked", "truncated"}: active when anything changed in the last
    `active_seconds`. Paths are relative to their root. A growing `.part` file shows a download that is still writing."""
    now = time.time() if now is None else now
    deadline = time.monotonic() + max_seconds
    found, walked, truncated = [], 0, False
    for root in roots:
        if not root or not os.path.isdir(root) or os.path.islink(root):
            continue
        stack = [root]
        while stack and not truncated:
            current = stack.pop()
            try:
                with os.scandir(current) as it:
                    entries = list(it)
            except OSError:
                continue
            for entry in entries:
                walked += 1
                if walked > max_entries or time.monotonic() > deadline:
                    truncated = True
                    break
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        st = entry.stat(follow_symlinks=False)
                        found.append((st.st_mtime, st.st_size, root, os.path.relpath(entry.path, root)))
                except OSError:
                    continue
    found.sort(key=lambda f: -f[0])
    files = [{"root": r, "path": rel.replace(os.sep, "/"), "size": size, "age_seconds": max(0.0, round(now - mtime, 1))} for mtime, size, r, rel in found[:limit]]
    active = bool(found) and now - found[0][0] <= active_seconds
    return {"status": "active" if active else "quiet", "files": files, "walked": min(walked, max_entries), "truncated": truncated}


def lock_holder(results_dir):
    """The live holder of RESULTS_DIR/.run.lock as {"pid", "pgid", "started", "what"}, or None when there is no lock or nothing of it is alive."""
    if not results_dir or os.name == "nt":   # on Windows the pipeline runs in WSL or Git Bash: its pids are not Windows pids, so they cannot be checked from here
        return None
    try:
        with open(os.path.join(results_dir, ".run.lock"), encoding="utf-8") as handle:
            lock = dict(line.rstrip("\n").split("=", 1) for line in handle if "=" in line)
    except OSError:
        return None
    pid = lock.get("pid", "")
    pgid = lock.get("pgid", "")
    if pid_alive(pid) and not heartbeat_stale(results_dir):
        return lock
    if pgid and group_alive(pgid):
        return lock
    return None


def heartbeat_stale(results_dir, now=None):
    """True when RESULTS_DIR/.run.lock.heartbeat exists and is older than PLASBENCH_LOCK_STALE_SECONDS (default 60): scripts/lib.sh treats such a lock as stale even
    while its pid is alive (a reused pid). A lock with no heartbeat file (an older version) is never called stale here."""
    try:
        limit = float(os.environ.get("PLASBENCH_LOCK_STALE_SECONDS", "") or 60)
        age = (time.time() if now is None else now) - os.path.getmtime(os.path.join(results_dir, ".run.lock.heartbeat"))
    except (OSError, ValueError):
        return False
    return age > limit


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
    if os.name != "nt":
        kwargs["start_new_session"] = True   # the command leads its own process group, so one killpg stops it and everything it started
        kwargs["env"] = dict(os.environ, PLASBENCH_JOB_GROUP="1")   # tells the stage scripts their process group is this job's (scripts/lib.sh acquire_run_lock)
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
    _write_json(p["pid"], {"runner": os.getpid(), "child": proc.pid, "pgid": proc.pid, "started": time.time()})
    _touch(p["activity"])
    done = threading.Event()

    def stop_group(signum=None, frame=None):
        """SIGTERM/SIGINT/SIGHUP to the runner stops the command's whole group, then the run ends normally (its exit file says it was signalled)."""
        threading.Thread(target=kill_group, args=(proc.pid,), daemon=True).start()
        threading.Thread(target=stop_job_container, args=(job_dir, job_id), daemon=True).start()
    if os.name != "nt" and threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            try:
                signal.signal(sig, stop_group)
            except (ValueError, OSError):
                pass

    def copy_output():
        while True:
            chunk = os.read(proc.stdout.fileno(), 65536)
            if not chunk:
                break
            write_log(chunk)
            # A "still working" notice from run_with_heartbeat comes from the shell, not the tool: it must not make a silent tool look alive.
            if any(line.strip() and b"still working:" not in line for line in chunk.splitlines()):
                _touch(p["activity"])

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
