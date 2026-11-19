"""PlasBench and Docker, as far as the folder window is concerned.

A window that runs INSIDE a container has no desktop (no folder dialog can open) and sees only the folders that were bind-mounted into it. So there the folder
chooser is the built-in browser, rooted at the mounts, and a person who needs another folder is given the exact `docker run` command that mounts it (never run for them).
From a window that runs on the computer itself, "run in Docker instead" is also only a command: it is built here, shown, and copied; the window does not stop itself or
start containers (the window listens on 127.0.0.1 only, so a container cannot host it reliably, and the image's default command is the command line, not the window).

Every system fact (environment, files, `docker info`) is an argument, so tests drive this with recorded /proc files. Standard library only.
"""
from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

DOCKER_REASON = ("This window runs inside Docker: there is no desktop to open a folder window in. The folders you can choose are the ones mounted into the container; "
                 "to use another folder, restart the container with it mounted")
IN_DOCKER_ENV = "PLASBENCH_IN_DOCKER"
PSEUDO_FS = {"proc", "sysfs", "cgroup", "cgroup2", "devpts", "mqueue", "devtmpfs", "securityfs", "debugfs", "tracefs", "binfmt_misc", "autofs", "configfs", "fusectl", "pstore", "bpf"}
SYSTEM_MOUNTS = ("/proc", "/sys", "/dev", "/run/lock", "/run/secrets", "/etc/resolv.conf", "/etc/hostname", "/etc/hosts", "/run/.containerenv", "/.dockerenv")
DRIVE_RE = re.compile(r"^([A-Za-z]):([\\/]|$)")
UNC_RE = re.compile(r"^[\\/]{2}[^\\/]+[\\/]+[^\\/]+")
UNC_WSL_RE = re.compile(r"^[\\/]{2}wsl(?:\.localhost|\$)[\\/]+([^\\/]+)(?:[\\/]+(.*))?$", re.I)


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


# ---------------------------------------------------------------- is this window inside a container?
def in_docker(env=None, exists=os.path.exists, read=_read) -> bool:
    """True inside a container: PLASBENCH_IN_DOCKER set, /.dockerenv or /run/.containerenv present, a docker / containerd / kubepods path in /proc/1/cgroup (cgroup v1),
    or Docker's per-container files in /proc/self/mountinfo (cgroup v2, where /proc/1/cgroup says only '0::/')."""
    env = os.environ if env is None else env
    flag = (env.get(IN_DOCKER_ENV) or "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return True
    if flag in ("0", "false", "no", "off"):
        return False
    if exists("/.dockerenv") or exists("/run/.containerenv"):
        return True
    cg = read("/proc/1/cgroup") or ""
    if re.search(r"(^|/)(docker|kubepods|containerd|libpod|lxc)(-|/|\.|$)", cg, re.M):
        return True
    mi = read("/proc/self/mountinfo") or ""
    return "/docker/containers/" in mi or "/containers/storage/" in mi


# ---------------------------------------------------------------- what is mounted
def _unescape(text: str) -> str:
    """Decode the kernel's octal escapes (\\040 is a space, \\344\\270\\255 is one UTF-8 character): the bytes are collected first, then decoded."""
    if "\\" not in text:
        return text
    raw = re.sub(rb"\\([0-7]{3})", lambda m: bytes([int(m.group(1), 8) & 255]), text.encode("utf-8", "surrogateescape"))
    return raw.decode("utf-8", "replace")


def parse_mountinfo(text: str) -> list:
    """Every line of /proc/self/mountinfo as {'mount_point', 'root', 'fstype', 'source', 'options', 'readonly'}. Octal escapes (\\040 = a space) are decoded."""
    rows = []
    for line in (text or "").splitlines():
        parts = line.split()
        if "-" not in parts[6:] or len(parts) < 10:
            continue
        dash = parts.index("-", 6)
        if len(parts) < dash + 3:
            continue
        opts = parts[5].split(",")
        rows.append({"mount_point": _unescape(parts[4]), "root": _unescape(parts[3]), "fstype": parts[dash + 1], "source": _unescape(parts[dash + 2]),
                     "options": opts, "readonly": "ro" in opts})
    return rows


def host_hint(root: str, fstype: str = "") -> str:
    """The folder on the Docker host a mount comes from, when the mount tells: Docker Desktop shows a Windows drive as /run/desktop/mnt/host/c/... or /host_mnt/c/...;
    a Linux host shows its own path. '' when it cannot be told (Docker never reports the host path reliably)."""
    for prefix in ("/run/desktop/mnt/host/", "/host_mnt/", "/mnt/host/"):
        if root.startswith(prefix):
            rest = root[len(prefix):].strip("/").split("/")
            if rest and len(rest[0]) == 1 and rest[0].isalpha():
                return rest[0].upper() + ":\\" + "\\".join(rest[1:])
            return "/" + "/".join(rest)
    return root if root.startswith("/") and root != "/" else ""


def user_mounts(text: str | None = None, read=_read) -> list:
    """The folders mounted into this container by the person who started it (bind mounts and volumes): [{'container_path', 'kind': 'bind'|'volume', 'host_path', 'name',
    'readonly', 'fstype'}], system mounts (/proc, /dev, /etc/hosts...) left out."""
    text = read("/proc/self/mountinfo") if text is None else text
    out = []
    for row in parse_mountinfo(text or ""):
        mp = row["mount_point"]
        if mp == "/" or any(mp == s or mp.startswith(s + "/") for s in SYSTEM_MOUNTS):
            continue
        if row["fstype"] in PSEUDO_FS or "/docker/containers/" in row["root"] or "/containers/storage/" in row["root"]:
            continue
        if row["fstype"] == "tmpfs" or row["fstype"] == "overlay":
            continue
        vol = re.search(r"/volumes/([^/]+)/_data(?:/|$)", row["root"])
        out.append({"container_path": mp, "kind": "volume" if vol else "bind", "name": vol.group(1) if vol else "",
                    "host_path": "" if vol else host_hint(row["root"], row["fstype"]), "readonly": row["readonly"], "fstype": row["fstype"]})
    out.sort(key=lambda r: r["container_path"])
    return out


def mount_roots(mounts: list) -> list:
    """The places the built-in browser starts from in a container: each mount, with a plain label."""
    rows = []
    for m in mounts:
        where = f"volume {m['name']}" if m["kind"] == "volume" else (f"from {m['host_path']}" if m["host_path"] else "bind mount")
        rows.append({"path": m["container_path"], "label": f"{m['container_path']} ({where}{', read-only' if m['readonly'] else ''})"})
    return rows


# ---------------------------------------------------------------- the docker run command
def container_name(path: str, taken=()) -> str:
    """/mnt/<name> for a host folder: the last part of the path, letters digits . _ - only, unique among `taken`."""
    base = re.split(r"[\\/]+", path.rstrip("\\/"))[-1] or "data"
    if len(base) == 2 and base[1] == ":":
        base = "drive_" + base[0].lower()
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._-") or "data"
    cand, n = name, 2
    while cand in taken:
        cand, n = f"{name}_{n}", n + 1
    return cand


def host_arg(path: str, shell: str = "posix") -> tuple:
    """(path the docker command should use, error). `shell` is 'posix' (Linux, macOS, WSL, Git Bash with MSYS_NO_PATHCONV) or 'powershell' (Windows, Docker Desktop).
    D:\\data -> /mnt/d/data (posix, the WSL form) or D:\\data (powershell); /mnt/d/x -> D:\\x for powershell; a UNC share is refused with the reason."""
    text = str(path or "").strip().strip('"').strip("'")
    if not text or re.search(r"[\x00-\x1f]", text):
        return "", "Type or paste a folder path first."
    drive = DRIVE_RE.match(text)
    wsl_unc = UNC_WSL_RE.match(text)
    if wsl_unc and shell == "posix":
        return "/" + (wsl_unc.group(2) or "").replace("\\", "/").strip("/"), ""
    if UNC_RE.match(text):
        return "", ("A network share (" + text + ") cannot be mounted into a container directly. Map it to a drive letter in Windows (or mount it in WSL with `mount -t drvfs`), "
                    "then use that drive path." if not wsl_unc else "A WSL folder (\\\\wsl.localhost\\...) is mounted from a WSL terminal using its Linux path, not from PowerShell.")
    if drive:
        rest = text[2:].replace("\\", "/").strip("/")
        if shell == "powershell":
            return text[0].upper() + ":\\" + rest.replace("/", "\\"), ""
        return f"/mnt/{text[0].lower()}" + ("/" + rest if rest else ""), ""
    if text.startswith("/"):
        m = re.match(r"^/mnt/([a-zA-Z])(/.*)?$", text)
        if shell == "powershell":
            if m:
                return m.group(1).upper() + ":\\" + (m.group(2) or "").strip("/").replace("/", "\\"), ""
            return "", "That is a Linux path. Docker Desktop in PowerShell needs a Windows path such as D:\\data; from a WSL terminal use the Linux form."
        return text.rstrip("/") or "/", ""
    return "", "Use a full path, such as D:\\data or /home/me/data (a relative path means a different folder in every terminal)."


def _quote(arg: str, shell: str) -> str:
    return shlex.quote(arg) if shell == "posix" else '"' + arg.replace('"', '`"') + '"'


def run_command(entries: list, shell: str = "posix", image: str = "plasbench:local", command: str = "bash", existing: list | None = None) -> dict:
    """The `docker run` command (and the docker compose snippet) that starts the container with each host folder mounted at /mnt/<name>.
    entries: [{'path': host path as typed, 'name': optional, 'readonly': bool}]; existing: mounts the container already has (kept, listed, host path only when known).
    -> {'ok', 'errors': [...], 'mounts': [{'host', 'container', 'readonly'}], 'command', 'compose', 'notes': [...]}. Nothing is executed."""
    errors, mounts, taken = [], [], set()
    for e in entries or []:
        host, err = host_arg(e.get("path", ""), shell)
        if err:
            errors.append(err)
            continue
        if ":" in host and not DRIVE_RE.match(host):
            errors.append(f"{host} contains a colon, which `docker run -v` cannot take; rename the folder or use a path without it.")
            continue
        name = container_name(e.get("name") or host, taken)
        taken.add(name)
        mounts.append({"host": host, "container": f"/mnt/{name}", "readonly": bool(e.get("readonly"))})
    if not mounts and not errors:
        errors.append("Add at least one folder.")
    ex_lines = []
    for m in existing or []:
        if m.get("kind") == "volume" and m.get("name"):
            ex_lines.append((f"{m['name']}:{m['container_path']}", True))
        elif m.get("host_path"):
            hp, _err = host_arg(m["host_path"], shell)
            if hp:
                ex_lines.append((f"{hp}:{m['container_path']}" + (":ro" if m.get("readonly") else ""), True))
    sep = " `\n  " if shell == "powershell" else " \\\n  "
    flags = [f"-v {_quote(m['host'] + ':' + m['container'] + (':ro' if m['readonly'] else ''), shell)}" for m in mounts]
    keep = [f"-v {_quote(v, shell)}" for v, _ in ex_lines]
    cmd = sep.join(["docker run --rm -it"] + keep + flags + [f"{image} {command}"])
    compose = "services:\n  plasbench:\n    image: " + image + "\n    volumes:\n" + "".join(
        f"      - {json_str(v)}\n" for v in [x for x, _ in ex_lines] + [m["host"] + ":" + m["container"] + (":ro" if m["readonly"] else "") for m in mounts])
    notes = ["The folders appear inside the container at the /mnt/<name> paths shown; choose those paths in the window.",
             "The command is not run for you: it starts a new container, so stop the old one first (Ctrl+C in its terminal or `docker stop`).",
             "Files you write there are written to the host folder; the image's tools run inside the container."]
    if ex_lines:
        notes.append("The mounts this container already has are kept in the command; check them (Docker does not always say which host folder a mount came from).")
    else:
        notes.append("Add back any mounts and options you used when you started the container (for example -p and --env-file).")
    return {"ok": not errors, "errors": errors, "mounts": mounts, "command": cmd if mounts else "", "compose": compose if mounts else "", "notes": notes}


def json_str(text: str) -> str:
    import json
    return json.dumps(text)


# ---------------------------------------------------------------- "run PlasBench in Docker instead" (a window on the computer itself)
def switch_offer(docker_state: dict | None, script_exists: bool) -> dict:
    """{'offered': bool, 'reason': why not}. Offered only when Docker answers `docker info` and scripts/docker_run.sh exists; never when this window already runs in Docker."""
    st = docker_state or {}
    if not st.get("installed"):
        return {"offered": False, "reason": "Docker is not installed on this computer"}
    if not st.get("running"):
        return {"offered": False, "reason": "Docker is installed but not running (start Docker Desktop or the docker service)"}
    if not script_exists:
        return {"offered": False, "reason": "scripts/docker_run.sh was not found in this PlasBench folder"}
    return {"offered": True, "reason": "", "image_ready": bool(st.get("image"))}


def switch_plan(project_root: str, data_dir: str, workspace: str, shell: str = "posix", image: str = "plasbench:local") -> dict:
    """The commands that run PlasBench's pipeline in Docker with the chosen folders mounted: -> {'ok', 'errors', 'command', 'steps': [...], 'notes': [...]}.
    posix: `cd <root> && PLASBENCH_WORKSPACE=... PLASBENCH_DATA_DIR=... scripts/docker_run.sh plasbench run ...`; powershell: the equivalent `docker run`."""
    errors = []
    root, e = host_arg(project_root, shell)
    errors += [e] if e else []
    data, e = host_arg(data_dir, shell) if data_dir else ("", "")
    errors += [e] if e else []
    work, e = host_arg(workspace, shell) if workspace else ("", "")
    errors += [e] if e else []
    if errors:
        return {"ok": False, "errors": errors, "command": "", "steps": [], "notes": []}
    tail = "plasbench --project-root /opt/plasbench run --samples /work/config/accessions.tsv"
    if shell == "posix":
        env = []
        if work:
            env.append(f"PLASBENCH_WORKSPACE={shlex.quote(work)}")
        if data:
            env.append(f"PLASBENCH_DATA_DIR={shlex.quote(data)}")
        command = f"cd {shlex.quote(root)} && " + " ".join(env + [f"scripts/docker_run.sh {tail}"])
    else:
        mounts = [(root + "\\config", "/work/config:ro"), (data or root + "\\data", "/work/data"), (root + "\\logs", "/work/logs"), (root + "\\results", "/work/results"),
                  (work or root + "\\studies", "/work/studies")]
        command = (" `\n  ".join(["docker run --rm"] + [f'-v "{h}:{c}"' for h, c in mounts]
                                 + ["-e DATA_DIR=/work/data -e LOG_DIR=/work/logs -e PLASBENCH_WORKSPACE=/work/studies", f"{image} {tail}"]))
    steps = ["Stop nothing: this window keeps running; the Docker command is separate.",
             "Open a terminal" + (" (a WSL terminal if Docker Desktop's WSL integration is on)" if shell == "posix" else " (PowerShell)") + " and paste the command.",
             "The tools run inside the image; results are written to the folders you mounted."]
    notes = [f"Mounted: data folder {data or '(the default data folder)'}, studies folder {work or '(the default studies folder)'}.",
             "Docker mounts only these folders; anything outside them is not visible to the container.",
             "This is a command to copy: PlasBench does not start containers for you, because the window itself listens on 127.0.0.1 only and cannot be reached inside a container."]
    return {"ok": True, "errors": [], "command": command, "steps": steps, "notes": notes}
