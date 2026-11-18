#!/usr/bin/env python3
"""Where a user tool comes from: download it (https only), or locate it on this computer (docs/ADDING_TOOLS.md, "Where the tool comes from").

Nothing here runs during validation. `plasbench install-tools NAME` (env/install_tools.sh) calls `user_tools.py fetch NAME`,
which calls install_url() or install_local() below. The network and the process runner are arguments (`fetch`, `run`), so the
tests inject fakes and never touch the network.

Safety rules, each enforced in code and tested (test/test_user_tool_source.py):
  * the URL must be https:// with a host and no embedded credentials; a redirect to anything else is refused;
  * a declared sha256 must match, else the download is deleted and the install refused; without one the observed checksum
    is printed as a warning and recorded;
  * the download is size-capped (default 2 GB, [install] max_download_mb or PLASBENCH_TOOL_MAX_DOWNLOAD_MB) and has a
    socket timeout; it resumes after an interrupted connection;
  * archives are extracted by this module, never by tar/unzip: absolute paths, '..', drive letters, device files,
    FIFOs, hard links and symlinks that point outside the folder are refused, and the extracted size is capped;
  * git sources are cloned with every transport except https disabled, without submodules unless asked, and are pinned to
    the commit that `ref` resolved to (recorded);
  * every install appends one line to <tool folder>/download_provenance.jsonl: final URL, size, sha256 (or commit).
"""

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ARCHIVE_SUFFIXES = (".zip", ".tar.gz", ".tgz", ".tar.xz", ".tar.bz2", ".tar")
GIT_HOSTS = ("github.com", "gitlab.com", "bitbucket.org", "codeberg.org", "git.sr.ht")
DEFAULT_MAX_MB = 2048
DEFAULT_TIMEOUT = 600
PROVENANCE = "download_provenance.jsonl"
SRC_DIR = "src"
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")


class SourceError(RuntimeError):
    """An install that must stop: the message names the cause and the fix."""


# -- the URL ---------------------------------------------------------------------------------------------------------
def url_problems(url):
    """Why a download URL is refused (empty list: accepted). Only https, a host, no credentials."""
    if not url:
        return ["[install] url is required for method = url"]
    parsed = urllib.parse.urlparse(url.strip())
    scheme = parsed.scheme.lower()
    if scheme == "http":
        return [f"[install] url {url} uses http, which is refused (a plain-http download can be altered in transit): use https://"]
    if scheme != "https":
        shown = f"{scheme}://" if scheme else "no scheme"
        return [f"[install] url {url} has {shown}: only https:// is accepted (ftp, file, ssh and git transports are refused)"]
    if not parsed.hostname:
        return [f"[install] url {url} has no host name"]
    if parsed.username or parsed.password:
        return ["[install] url must not contain a user name or password (credentials do not belong in a manifest)"]
    return []


def detect_kind(url):
    """archive | git | file, from the URL alone."""
    parsed = urllib.parse.urlparse(url or "")
    path = parsed.path.lower().rstrip("/")
    if path.endswith(ARCHIVE_SUFFIXES):
        return "archive"
    if path.endswith(".git"):
        return "git"
    segments = [s for s in path.split("/") if s]
    if (parsed.hostname or "").lower() in GIT_HOSTS and len(segments) == 2 and "." not in segments[-1]:
        return "git"
    return "file"


def file_name_from_url(url):
    name = os.path.basename(urllib.parse.urlparse(url).path.rstrip("/")) or "download"
    return re.sub(r"[^A-Za-z0-9._+-]", "_", name)


def max_bytes(configured=""):
    for raw in (os.environ.get("PLASBENCH_TOOL_MAX_DOWNLOAD_MB", ""), str(configured or "")):
        if raw.strip().isdigit() and int(raw) > 0:
            return int(raw) * 1024 * 1024
    return DEFAULT_MAX_MB * 1024 * 1024


# -- checksums -------------------------------------------------------------------------------------------------------
def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_files(folder):
    folder = Path(folder)
    return sorted(p for p in folder.rglob("*") if (p.is_file() or p.is_symlink()) and ".git" not in p.relative_to(folder).parts)


def tree_checksum(path):
    """sha256 of a file, or of a folder: the sorted relative paths with their contents (symlinks by target)."""
    path = Path(path)
    if path.is_file():
        return file_sha256(path)
    digest = hashlib.sha256()
    for item in tree_files(path):
        digest.update(item.relative_to(path).as_posix().encode() + b"\0")
        if item.is_symlink():
            digest.update(b"->" + os.readlink(item).encode())
        else:
            digest.update(file_sha256(item).encode())
    return digest.hexdigest()


def quick_signature(path):
    """A content-free signature (relative names, sizes, mtimes) for a linked location that is checked on every run."""
    path = Path(path)
    if not path.exists():
        return "missing"
    if path.is_file():
        info = path.stat()
        return f"file:{info.st_size}:{info.st_mtime_ns}"
    digest = hashlib.sha256()
    for item in tree_files(path):
        try:
            info = item.stat()
        except OSError:
            continue
        digest.update(f"{item.relative_to(path).as_posix()}:{info.st_size}:{info.st_mtime_ns}\n".encode())
    return "tree:" + digest.hexdigest()[:32]


def tree_size(path):
    path = Path(path)
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in tree_files(path) if not p.is_symlink())


# -- downloading -----------------------------------------------------------------------------------------------------
def _require_online(url):
    """Say plainly, before a download starts, that the internet is not reachable (plasbench/netcheck.py, loaded through plasbench_common); never blocks when the check is unavailable."""
    try:
        import plasbench_common
        module = plasbench_common.netcheck_module()
    except Exception:  # noqa: BLE001 - the check is a courtesy
        return
    if module is None:
        return
    try:
        module.require("internet", action=f"Downloading {urllib.parse.urlparse(url).netloc or 'the tool'}")
    except module.NoInternet as exc:
        raise SourceError(exc.message) from exc


def http_fetch(url, dest, limit, timeout=DEFAULT_TIMEOUT, attempts=3, opener=urllib.request.urlopen):
    """Download `url` to `dest` (resuming `dest.part` after an interrupted connection). Returns {"final_url", "size"}.
    Refuses a response over `limit` bytes and a redirect that leaves https."""
    dest = Path(dest)
    part = Path(str(dest) + ".part")
    if opener is urllib.request.urlopen:
        _require_online(url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    last = None
    for attempt in range(1, attempts + 1):
        have = part.stat().st_size if part.exists() else 0
        headers = {"User-Agent": "PlasBench-tool-install"}
        if have:
            headers["Range"] = f"bytes={have}-"
        try:
            with opener(urllib.request.Request(url, headers=headers), timeout=timeout) as response:
                final = response.geturl() if hasattr(response, "geturl") else url
                if urllib.parse.urlparse(final).scheme.lower() != "https":
                    raise SourceError(f"{url} redirected to {final}, which is not https; refused")
                status = getattr(response, "status", 200)
                length = response.headers.get("Content-Length") if getattr(response, "headers", None) else None
                if status == 206:
                    mode = "ab"
                else:
                    mode, have = "wb", 0
                if length and length.isdigit() and have + int(length) > limit:
                    raise SourceError(f"{url} is {have + int(length)} bytes, over the {limit} byte cap "
                                      f"(raise [install] max_download_mb or PLASBENCH_TOOL_MAX_DOWNLOAD_MB if you trust it)")
                total = have
                with open(part, mode) as out:
                    for chunk in iter(lambda: response.read(1 << 20), b""):
                        total += len(chunk)
                        if total > limit:
                            out.close()
                            part.unlink(missing_ok=True)
                            raise SourceError(f"{url} exceeded the {limit} byte download cap; stopped and deleted the partial file")
                        out.write(chunk)
            os.replace(part, dest)
            return {"final_url": final, "size": dest.stat().st_size}
        except SourceError:
            raise
        except (urllib.error.URLError, OSError, TimeoutError) as exc:   # interrupted: resume from the bytes already kept
            last = exc
            if isinstance(exc, urllib.error.HTTPError) and exc.code in (403, 404, 410):
                raise SourceError(f"{url}: HTTP {exc.code} ({exc.reason}); check the url") from exc
            time.sleep(min(2 * attempt, 5) if attempt < attempts else 0)
    raise SourceError(f"download of {url} failed after {attempts} attempts: {last}")


# -- safe extraction -------------------------------------------------------------------------------------------------
def _bad_member(name):
    """Why an archive member name is refused, or ''."""
    normalised = name.replace("\\", "/")
    if normalised.startswith("/") or re.match(r"^[A-Za-z]:", normalised):
        return "an absolute path"
    if ".." in normalised.split("/"):
        return "a path that climbs out of the folder ('..')"
    if "\x00" in name:
        return "a NUL byte in the name"
    return ""


def _inside(root, target):
    root = os.path.realpath(root)
    target = os.path.realpath(target)
    return target == root or target.startswith(root + os.sep)


def _link_ok(root, member_path, link_target):
    if os.path.isabs(link_target) or re.match(r"^[A-Za-z]:", link_target):
        return False
    return _inside(root, os.path.join(os.path.dirname(member_path), link_target))


def _top_level(names):
    """The single top-level folder every member lives in (stripped on extraction), or ''."""
    tops = {n.replace("\\", "/").lstrip("./").split("/")[0] for n in names if n.replace("\\", "/").strip("/")}
    full = [n.replace("\\", "/").strip("/") for n in names]
    if len(tops) == 1 and all("/" in n or n == next(iter(tops)) for n in full):
        top = next(iter(tops))
        if any(n != top for n in full):
            return top
    return ""


def _symlink(link, target):
    """Create an (already vetted) symlink; where the system will not allow it (Windows without the privilege) the file it
    points to is copied instead when it is already extracted, otherwise the link is skipped."""
    try:
        os.symlink(link, target)
    except OSError:
        pointed = Path(os.path.dirname(target)) / link
        if pointed.is_file():
            shutil.copyfile(pointed, target)


def safe_extract(archive, dest, limit):
    """Extract a zip or tar archive into `dest` (created, must be empty), refusing every unsafe member with the member's name.
    A single top-level folder is stripped. Returns the number of files written."""
    archive, dest = Path(archive), Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    cap, count, files = limit * 4, 0, 0
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            infos = zf.infolist()
            top = _top_level([i.filename for i in infos])
            total = sum(i.file_size for i in infos)
            if total > cap or len(infos) > 500000:
                raise SourceError(f"{archive.name} would extract to {total} bytes in {len(infos)} entries, over the safety cap")
            for info in infos:
                reason = _bad_member(info.filename)
                if reason:
                    raise SourceError(f"{archive.name}: member '{info.filename}' is {reason}; refusing to extract")
                rel = info.filename.replace("\\", "/")
                rel = rel[len(top) + 1:] if top and rel.startswith(top + "/") else ("" if rel.strip("/") == top else rel)
                if not rel.strip("/"):
                    continue
                target = dest / rel
                mode = (info.external_attr >> 16) & 0o170000
                if mode == stat.S_IFLNK:
                    link = zf.read(info).decode("utf-8", "replace")
                    if not _link_ok(dest, str(target), link):
                        raise SourceError(f"{archive.name}: '{info.filename}' is a symlink to '{link}', outside the folder; refusing")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    _symlink(link, target)
                    continue
                if mode in (stat.S_IFCHR, stat.S_IFBLK, stat.S_IFIFO, stat.S_IFSOCK):
                    raise SourceError(f"{archive.name}: '{info.filename}' is a device or special file; refusing")
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not _inside(dest, target):
                    raise SourceError(f"{archive.name}: '{info.filename}' would be written outside the folder; refusing")
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
                perm = (info.external_attr >> 16) & 0o777
                os.chmod(target, (perm & 0o755) | 0o600 if perm else 0o644)
                files += 1
        return files
    try:
        tf = tarfile.open(archive, "r:*")
    except tarfile.TarError as exc:
        raise SourceError(f"{archive.name} is not a readable zip or tar archive: {exc}") from exc
    with tf:
        members = tf.getmembers()
        top = _top_level([m.name for m in members])
        total = sum(m.size for m in members if m.isfile())
        if total > cap or len(members) > 500000:
            raise SourceError(f"{archive.name} would extract to {total} bytes in {len(members)} entries, over the safety cap")
        for member in members:
            reason = _bad_member(member.name)
            if reason:
                raise SourceError(f"{archive.name}: member '{member.name}' is {reason}; refusing to extract")
            if member.isdev() or member.isfifo():
                raise SourceError(f"{archive.name}: '{member.name}' is a device or FIFO; refusing")
            rel = member.name.replace("\\", "/")
            rel = rel[len(top) + 1:] if top and rel.startswith(top + "/") else ("" if rel.strip("/") == top else rel)
            rel = rel.lstrip("./") if rel.startswith("./") else rel
            if not rel.strip("/"):
                continue
            target = dest / rel
            if member.issym():
                if not _link_ok(dest, str(target), member.linkname):
                    raise SourceError(f"{archive.name}: '{member.name}' is a symlink to '{member.linkname}', outside the folder; refusing")
                target.parent.mkdir(parents=True, exist_ok=True)
                _symlink(member.linkname, target)
            elif member.islnk():
                source = member.linkname.replace("\\", "/")
                if top and source.startswith(top + "/"):
                    source = source[len(top) + 1:]
                if _bad_member(member.linkname) or not _inside(dest, dest / source) or not (dest / source).is_file():
                    raise SourceError(f"{archive.name}: '{member.name}' is a hard link to '{member.linkname}', which is not a file inside "
                                      f"the archive; refusing")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(dest / source, target)
                files += 1
            elif member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                if not _inside(dest, target):
                    raise SourceError(f"{archive.name}: '{member.name}' would be written outside the folder; refusing")
                target.parent.mkdir(parents=True, exist_ok=True)
                with tf.extractfile(member) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
                os.chmod(target, (member.mode & 0o755) | 0o600 if member.mode else 0o644)   # no setuid/setgid/sticky
                files += 1
            else:
                raise SourceError(f"{archive.name}: '{member.name}' is an unsupported entry type; refusing")
    return files


# -- provenance ------------------------------------------------------------------------------------------------------
def record(folder, entry):
    entry = dict(entry, downloaded_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    with open(Path(folder) / PROVENANCE, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")
    return entry


def last_record(folder):
    path = Path(folder) / PROVENANCE
    if not path.is_file():
        return {}
    last = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            last = json.loads(line)
        except ValueError:
            continue
    return last


def _fresh(folder):
    src = Path(folder) / SRC_DIR
    if src.exists() or src.is_symlink():
        shutil.rmtree(src) if src.is_dir() and not src.is_symlink() else src.unlink()
    return src


# -- install ---------------------------------------------------------------------------------------------------------
def install_url(spec, folder, fetch=http_fetch, run=subprocess.run, log=print):
    """Download and unpack (or clone) `spec` into <folder>/src. spec keys: name, url, sha256, kind, ref, submodules,
    max_download_mb, timeout. Returns the provenance entry. Raises SourceError, leaving no half-installed src/."""
    folder = Path(folder)
    problems = url_problems(spec.get("url", ""))
    if problems:
        raise SourceError("; ".join(problems))
    url = spec["url"].strip()
    kind = spec.get("kind") or "auto"
    kind = detect_kind(url) if kind == "auto" else kind
    declared = (spec.get("sha256") or "").strip().lower()
    if declared and not SHA256_RE.match(declared):
        raise SourceError("[install] sha256 must be 64 hexadecimal characters")
    if declared and kind == "git":
        raise SourceError(f"sha256 = {declared} does not apply to kind = git; pin the commit with ref instead")
    limit = max_bytes(spec.get("max_download_mb", ""))
    timeout = int(spec.get("timeout") or DEFAULT_TIMEOUT)
    folder.mkdir(parents=True, exist_ok=True)
    entry = {"tool": spec.get("name", ""), "method": "url", "url": url, "kind": kind, "sha256_declared": declared,
             "sha256_verified": False, "build_command": spec.get("build_command", "")}
    if kind == "git":
        _install_git(spec, url, folder, entry, run, log)
    else:
        work = folder / ".download"
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True)
        name = file_name_from_url(url)
        target = work / name
        # A half-finished earlier attempt (the .part file) is kept inside the work folder and resumed.
        info = fetch(url, target, limit, timeout)
        got = file_sha256(target)
        entry.update(final_url=info.get("final_url", url), size=target.stat().st_size, sha256=got)
        if declared and got != declared:
            target.unlink(missing_ok=True)
            shutil.rmtree(work, ignore_errors=True)
            raise SourceError(f"{url}: sha256 is {got} but the manifest pins {declared}; the download was deleted and nothing was "
                              f"installed. If you trust the new file, update [install] sha256.")
        entry["sha256_verified"] = bool(declared)
        if declared:
            log(f"  sha256 verified ({got})")
        else:
            log(f"WARNING: no sha256 pinned for {url}; the download could not be verified. Observed sha256: {got} (recorded in "
                f"{folder / PROVENANCE}). Add `sha256 = {got}` to [install] to make a changed file fail the next install.")
        src = _fresh(folder)
        try:
            if kind == "archive":
                if not name.lower().endswith(ARCHIVE_SUFFIXES):
                    raise SourceError(f"kind = archive but {name} is not one of {', '.join(ARCHIVE_SUFFIXES)}")
                entry["files"] = safe_extract(target, src, limit)
            else:
                src.mkdir(parents=True)
                shutil.copy2(target, src / name)
                os.chmod(src / name, 0o755 if spec.get("executable") else 0o644)
        except SourceError:
            shutil.rmtree(src, ignore_errors=True)
            raise
        finally:
            shutil.rmtree(work, ignore_errors=True)
        entry["tree_sha256"] = tree_checksum(src)
    entry["src"] = str(folder / SRC_DIR)
    return record(folder, entry)


def _git(run, args, cwd=None):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    command = ["git", "-c", "protocol.allow=never", "-c", "protocol.https.allow=always", "-c", "core.symlinks=true"] + args
    result = run(command, cwd=cwd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise SourceError(f"git {' '.join(args[:2])} failed: {(result.stderr or result.stdout or '').strip()[:400]}")
    return (result.stdout or "").strip()


def _install_git(spec, url, folder, entry, run, log):
    ref = (spec.get("ref") or "").strip()
    submodules = (spec.get("submodules") or "no").lower() in ("yes", "true", "1")
    src = _fresh(folder)
    is_commit = bool(COMMIT_RE.match(ref)) and not re.match(r"^v?\d+(\.\d+)*$", ref)
    try:
        if ref and not is_commit:
            _git(run, ["clone", "--depth", "1", "--branch", ref, "--single-branch", url, str(src)])
        else:
            _git(run, ["clone", url, str(src)])
            if ref:
                _git(run, ["checkout", "--detach", ref], cwd=str(src))
        if submodules:
            _git(run, ["submodule", "update", "--init", "--recursive", "--depth", "1"], cwd=str(src))
        commit = _git(run, ["rev-parse", "HEAD"], cwd=str(src))
    except SourceError:
        shutil.rmtree(src, ignore_errors=True)
        raise
    entry.update(final_url=url, ref=ref, commit=commit, submodules=submodules, sha256="", size=0)
    if not ref:
        log(f"WARNING: no ref given for {url}: cloned the default branch at commit {commit} (recorded). Pin `ref` for a reproducible install.")


def local_target(value):
    """The path on this computer for what the user typed ('~', $VAR, a Windows drive path under WSL)."""
    text = os.path.expandvars(os.path.expanduser((value or "").strip().strip('"')))
    try:
        from plasbench import chooser
        text = chooser.to_linux(text)
    except Exception:  # noqa: BLE001 - the conversion is a convenience; the typed path is used as-is without it
        pass
    return Path(text)


def install_local(spec, folder, log=print):
    """Locate (link) or copy a tool already on this computer. spec keys: name, path, mode, max_download_mb."""
    folder = Path(folder)
    source = local_target(spec.get("path", ""))
    if not source.exists():
        raise SourceError(f"[install] path {spec.get('path')} does not exist on this computer (looked for {source}); "
                          f"fix the path or copy the tool there")
    mode = (spec.get("mode") or "copy").lower()
    folder.mkdir(parents=True, exist_ok=True)
    entry = {"tool": spec.get("name", ""), "method": "local", "local_path": str(source.resolve()), "mode": mode,
             "kind": "file" if source.is_file() else "folder", "build_command": spec.get("build_command", "")}
    if mode == "link":
        entry.update(sha256=tree_checksum(source), size=tree_size(source), src=str(source.resolve()))
        log(f"WARNING: mode = link: PlasBench uses {source} in place, so the tool can change under the benchmark. "
            f"Recorded checksum {entry['sha256']}; use mode = copy for a reproducible run.")
        return record(folder, entry)
    limit = max_bytes(spec.get("max_download_mb", ""))
    size = tree_size(source)
    if size > limit:
        raise SourceError(f"{source} is {size} bytes, over the {limit} byte cap for a copy; use mode = link or raise max_download_mb")
    dest = _fresh(folder)
    if source.is_file():
        dest.mkdir(parents=True)
        shutil.copy2(source, dest / source.name)
    else:
        shutil.copytree(source, dest, symlinks=False, ignore=shutil.ignore_patterns(".git"))
    entry.update(sha256=tree_checksum(dest / source.name if source.is_file() else dest), size=size, src=str(dest))
    log(f"  copied {source} -> {dest} (checksum {entry['sha256']})")
    return record(folder, entry)
