#!/usr/bin/env python3
"""Where a user tool comes from (python/user_tool_source.py, [install] method = url | local). No network is used: the
download is an injected function, git is an injected runner, and the unsafe archives are built here."""

import hashlib
import io
import os
import stat
import sys
import tarfile
import tempfile
import urllib.error
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))

import user_tool_source as src  # noqa: E402
import user_tools as ut  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def raises(function, *args, **kwargs):
    try:
        function(*args, **kwargs)
    except src.SourceError as exc:
        return str(exc)
    return ""


def tar_bytes(members, mode="w:gz"):
    """members: list of (name, kind, payload) with kind file | dir | sym | hard | chr | fifo."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode=mode) as tf:
        for name, kind, payload in members:
            info = tarfile.TarInfo(name)
            if kind == "file":
                data = payload.encode()
                info.size, info.mode = len(data), 0o755
                tf.addfile(info, io.BytesIO(data))
            elif kind == "dir":
                info.type, info.mode = tarfile.DIRTYPE, 0o755
                tf.addfile(info)
            elif kind == "sym":
                info.type, info.linkname = tarfile.SYMTYPE, payload
                tf.addfile(info)
            elif kind == "hard":
                info.type, info.linkname = tarfile.LNKTYPE, payload
                tf.addfile(info)
            elif kind == "chr":
                info.type = tarfile.CHRTYPE
                tf.addfile(info)
            elif kind == "fifo":
                info.type = tarfile.FIFOTYPE
                tf.addfile(info)
    return buffer.getvalue()


def zip_bytes(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, payload, symlink in entries:
            info = zipfile.ZipInfo(name)
            if symlink:
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, payload)
    return buffer.getvalue()


class Response:
    """What urllib's urlopen returns: read(), headers, status, geturl()."""

    def __init__(self, data, final="https://example.org/x.tar.gz", status=200, length=None, fail_after=None):
        self.data, self._final, self.status, self.pos, self.fail_after = data, final, status, 0, fail_after
        self.headers = {"Content-Length": str(len(data) if length is None else length)}

    def read(self, n=-1):
        if self.fail_after is not None and self.pos >= self.fail_after:
            raise urllib.error.URLError("connection reset")
        end = len(self.data) if n < 0 else self.pos + n
        if self.fail_after is not None:
            end = min(end, self.fail_after)
        chunk = self.data[self.pos:end]
        self.pos += len(chunk)
        return chunk

    def geturl(self):
        return self._final

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_fetch(payload, final="https://cdn.example.org/real/tool-1.0.tar.gz"):
    calls = []

    def fetch(url, dest, limit, timeout):
        calls.append(url)
        Path(dest).write_bytes(payload)
        return {"final_url": final, "size": len(payload)}
    fetch.calls = calls
    return fetch


def manifest(folder, install, extra_run="", name="src_tool"):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "plasbench-tool.ini").write_text(
        f"[tool]\nname = {name}\ntask = binning_reconstruction\nanalysis_track = short_read\n[install]\n{install}\n"
        f"[run]\nmode = command\ncommand = {{src}}/run.sh {{contigs}} {{outdir}}{extra_run}\nrequires = contigs\n"
        f"[output]\nformat = contig_bins\npath = bins.tsv\n", encoding="utf-8", newline="\n")
    return folder / "plasbench-tool.ini"


def main():
    print("the URL")
    check("https is accepted", src.url_problems("https://example.org/a/tool-1.0.tar.gz") == [])
    for bad, word in (("http://example.org/t.tar.gz", "http"), ("ftp://example.org/t.tar.gz", "ftp"),
                      ("file:///etc/passwd", "file"), ("ext::sh -c id", "only https"), ("//example.org/t", "no scheme"),
                      ("https:///nohost", "no host"), ("https://user:pw@example.org/t.zip", "user name"), ("", "required")):
        problems = " ".join(src.url_problems(bad))
        check(f"refused: {bad or '(empty)'}", word in problems, problems)
    check("kind: archives by suffix", all(src.detect_kind(f"https://e.org/x{s}") == "archive"
                                          for s in (".zip", ".tar.gz", ".tgz", ".tar.xz", ".tar.bz2")))
    check("kind: .git and a github owner/repo are git; anything else is a file",
          src.detect_kind("https://e.org/x.git") == "git" and src.detect_kind("https://github.com/o/r") == "git"
          and src.detect_kind("https://github.com/o/r/releases/download/v1/tool") == "file"
          and src.detect_kind("https://e.org/tool.py") == "file")

    print("the download: size cap, redirects, resume")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        body = b"x" * 1000
        out = tmp / "a.bin"
        info = src.http_fetch("https://e.org/a.bin", out, 5000, opener=lambda req, timeout: Response(body))
        check("a download is written and sized", out.read_bytes() == body and info["size"] == 1000 and info["final_url"] == "https://example.org/x.tar.gz")
        msg = raises(src.http_fetch, "https://e.org/big", tmp / "b.bin", 500, opener=lambda req, timeout: Response(body))
        check("a declared size over the cap is refused before any byte is kept", "cap" in msg and not (tmp / "b.bin").exists(), msg)
        msg = raises(src.http_fetch, "https://e.org/big", tmp / "c.bin", 500, opener=lambda req, timeout: Response(body, length=1))
        check("a lying Content-Length cannot get past the cap while streaming", "exceeded" in msg and not (tmp / "c.bin.part").exists(), msg)
        msg = raises(src.http_fetch, "https://e.org/r", tmp / "d.bin", 5000,
                     opener=lambda req, timeout: Response(body, final="http://evil.example/x"))
        check("a redirect that leaves https is refused", "not https" in msg, msg)
        attempts = []

        def flaky(req, timeout):
            attempts.append(dict(req.header_items()))
            if len(attempts) == 1:
                return Response(body, fail_after=400)
            have = int(req.get_header("Range").split("=")[1].rstrip("-"))
            return Response(body[have:], status=206)
        info = src.http_fetch("https://e.org/f.bin", tmp / "f.bin", 5000, opener=flaky, attempts=3)
        check("an interrupted download resumes from the bytes already kept (Range)", (tmp / "f.bin").read_bytes() == body
              and attempts[1].get("Range") == "bytes=400-", attempts)

        print("install_url: verify, record, extract")
        payload = tar_bytes([("tool-1.0", "dir", ""), ("tool-1.0/run.sh", "file", "#!/bin/sh\necho hi\n"), ("tool-1.0/lib/x.txt", "file", "x")])
        sha = hashlib.sha256(payload).hexdigest()
        folder = tmp / "t1"
        logs = []
        entry = src.install_url({"name": "t1", "url": "https://example.org/tool-1.0.tar.gz", "sha256": sha}, folder,
                                fetch=fake_fetch(payload), log=logs.append)
        check("the archive is extracted into src/ with its single top-level folder stripped",
              (folder / "src" / "run.sh").is_file() and (folder / "src" / "lib" / "x.txt").is_file())
        check("a pinned sha256 is verified and recorded as verified", entry["sha256"] == sha and entry["sha256_verified"] is True)
        record = src.last_record(folder)
        check("download_provenance.jsonl has the final URL, size and sha256",
              record["final_url"] == "https://cdn.example.org/real/tool-1.0.tar.gz" and record["size"] == len(payload)
              and record["sha256"] == sha and record["url"] == "https://example.org/tool-1.0.tar.gz", record)
        check("the download folder is cleaned up", not (folder / ".download").exists())

        folder = tmp / "t2"
        logs = []
        entry = src.install_url({"name": "t2", "url": "https://example.org/tool-1.0.tar.gz"}, folder, fetch=fake_fetch(payload), log=logs.append)
        check("without a sha256 it installs, warns loudly with the observed checksum, and records it unverified",
              any("WARNING" in l and sha in l for l in logs) and entry["sha256_verified"] is False and entry["sha256"] == sha, logs)

        folder = tmp / "t3"
        msg = raises(src.install_url, {"name": "t3", "url": "https://example.org/tool-1.0.tar.gz", "sha256": "0" * 64}, folder,
                     fetch=fake_fetch(payload), log=lambda m: None)
        check("a sha256 mismatch is refused: nothing installed, download deleted, both checksums named",
              sha in msg and "0" * 64 in msg and not (folder / "src").exists() and not (folder / ".download").exists()
              and src.last_record(folder) == {}, msg)
        msg = raises(src.install_url, {"name": "t3", "url": "http://example.org/x.tar.gz"}, tmp / "t3b", fetch=fake_fetch(payload))
        check("install_url re-checks the URL: http is refused even if the manifest check was skipped", "http" in msg, msg)
        msg = raises(src.install_url, {"name": "t3", "url": "https://github.com/o/r.git", "sha256": sha}, tmp / "t3c", run=lambda *a, **k: None)
        check("sha256 does not apply to git", "git" in msg, msg)
        msg = raises(src.install_url, {"name": "t3", "url": "https://example.org/x.tar.gz", "kind": "archive", "sha256": "xyz"}, tmp / "t3d",
                     fetch=fake_fetch(payload))
        check("a malformed sha256 is refused", "64 hexadecimal" in msg, msg)

        single = b"#!/bin/sh\necho solo\n"
        folder = tmp / "t4"
        entry = src.install_url({"name": "t4", "url": "https://example.org/dl/solo.sh", "executable": True}, folder,
                                fetch=fake_fetch(single, "https://example.org/dl/solo.sh"), log=lambda m: None)
        check("kind = file keeps the single file under src/", (folder / "src" / "solo.sh").read_bytes() == single and entry["kind"] == "file")

        print("safe extraction")
        def extract(blob, name="a.tar.gz", limit=10 ** 8):
            dest = tmp / ("x_" + hashlib.md5(blob).hexdigest()[:8])
            archive = tmp / name
            archive.write_bytes(blob)
            return raises(src.safe_extract, archive, dest, limit), dest
        msg, dest = extract(tar_bytes([("d", "dir", ""), ("../evil.txt", "file", "x")]))
        check("tar path traversal ('../') is refused, naming the member", "../evil.txt" in msg and "climbs" in msg and not (tmp / "evil.txt").exists(), msg)
        msg, _ = extract(tar_bytes([("a/../../evil2.txt", "file", "x")]))
        check("a '..' hidden in the middle of a path is refused", "climbs" in msg, msg)
        msg, _ = extract(tar_bytes([("/etc/cron.d/x", "file", "x")]))
        check("a tar absolute path is refused", "absolute" in msg, msg)
        msg, _ = extract(tar_bytes([("C:/Windows/x.dll", "file", "x")]))
        check("a drive-letter path is refused", "absolute" in msg, msg)
        msg, _ = extract(tar_bytes([("pkg/ok.txt", "file", "x"), ("pkg/link", "sym", "../../../etc/passwd")]))
        check("a symlink that points out of the folder is refused", "symlink" in msg and "outside" in msg, msg)
        msg, _ = extract(tar_bytes([("pkg/ok.txt", "file", "x"), ("pkg/link", "sym", "/etc/passwd")]))
        check("an absolute symlink target is refused", "outside" in msg, msg)
        msg, _ = extract(tar_bytes([("pkg/ok.txt", "file", "x"), ("pkg/hl", "hard", "../../etc/passwd")]))
        check("a hard link out of the archive is refused", "hard link" in msg or "climbs" in msg, msg)
        msg, _ = extract(tar_bytes([("pkg/ok.txt", "file", "x"), ("pkg/dev", "chr", "")]))
        check("a device file is refused", "device" in msg, msg)
        msg, _ = extract(tar_bytes([("pkg/ok.txt", "file", "x"), ("pkg/fifo", "fifo", "")]))
        check("a FIFO is refused", "FIFO" in msg or "device" in msg, msg)
        msg, _ = extract(zip_bytes([("../zipslip.txt", b"x", False)]), "a.zip")
        check("zip-slip ('../') is refused", "climbs" in msg and not (tmp / "zipslip.txt").exists(), msg)
        msg, _ = extract(zip_bytes([("/abs/x", b"x", False)]), "b.zip")
        check("a zip absolute path is refused", "absolute" in msg, msg)
        msg, _ = extract(zip_bytes([("pkg/a", b"x", False), ("pkg/ln", b"../../outside", True)]), "c.zip")
        check("a zip symlink out of the folder is refused", "outside" in msg, msg)
        msg, _ = extract(tar_bytes([("p/big", "file", "x" * 5000)]), limit=100)
        check("an archive that expands past the size cap is refused (zip bomb guard)", "cap" in msg, msg)
        msg, dest = extract(tar_bytes([("p/ok.txt", "file", "fine"), ("p/inner", "sym", "ok.txt")]))
        check("a harmless archive with an inside symlink extracts", msg == "" and (dest / "ok.txt").read_text() == "fine")
        bad_archive = tmp / "bad.tar.gz"
        bad_archive.write_bytes(b"not an archive at all")
        check("a file that is not an archive is reported", "not a readable" in raises(src.safe_extract, bad_archive, tmp / "x_bad", 1000))
        mode = os.stat(dest / "ok.txt").st_mode
        check("extracted files never keep setuid/setgid bits", not mode & (stat.S_ISUID | stat.S_ISGID))
        check("a refused extraction leaves no half-installed src/ in the tool folder",
              not (raises(src.install_url, {"name": "t5", "url": "https://example.org/x.tar.gz"}, tmp / "t5",
                          fetch=fake_fetch(tar_bytes([("../evil", "file", "x")])), log=lambda m: None) == "")
              and not (tmp / "t5" / "src").exists())

        print("install_url: git (injected runner)")
        runs = []

        class Done:
            def __init__(self, out="", code=0):
                self.stdout, self.stderr, self.returncode = out, "boom" if code else "", code

        def runner(command, cwd=None, **kw):
            runs.append(command)
            if "clone" in command:
                dest = Path(command[-1])
                dest.mkdir(parents=True, exist_ok=True)
                (dest / "README").write_text("hi")
            return Done("c0ffee1234567890c0ffee1234567890c0ffee12\n" if "rev-parse" in command else "")
        folder = tmp / "g1"
        entry = src.install_url({"name": "g1", "url": "https://github.com/o/r.git", "ref": "v1.2.0"}, folder, run=runner, log=lambda m: None)
        clone = next(c for c in runs if "clone" in c)
        check("git: a tag is cloned shallow with --branch, only the https transport allowed, no submodules",
              "--depth" in clone and "--branch" in clone and "v1.2.0" in clone and "protocol.allow=never" in clone
              and "protocol.https.allow=always" in clone and not any("submodule" in c for c in runs), clone)
        check("git: the resolved commit is recorded", entry["commit"].startswith("c0ffee") and src.last_record(folder)["ref"] == "v1.2.0")
        runs.clear()
        src.install_url({"name": "g1", "url": "https://github.com/o/r.git", "ref": "0123abc"}, tmp / "g2", run=runner, log=lambda m: None)
        check("git: a commit id is cloned then checked out detached", any("checkout" in c and "0123abc" in c for c in runs), runs)
        runs.clear()
        src.install_url({"name": "g1", "url": "https://github.com/o/r.git", "ref": "v1", "submodules": "yes"}, tmp / "g3", run=runner, log=lambda m: None)
        check("git: submodules only when asked", any("submodule" in c for c in runs))
        msg = raises(src.install_url, {"name": "g4", "url": "https://github.com/o/r.git"}, tmp / "g4", run=lambda *a, **k: Done("", 1), log=lambda m: None)
        check("git: a failing clone is a clear error and leaves no src/", "boom" in msg and not (tmp / "g4" / "src").exists(), msg)

        print("method = local")
        tool_src = tmp / "mytool"
        (tool_src / "bin").mkdir(parents=True)
        (tool_src / "bin" / "mytool").write_text("#!/bin/sh\necho 1\n")
        (tool_src / "README").write_text("v1")
        folder = tmp / "l1"
        entry = src.install_local({"name": "l1", "path": str(tool_src), "mode": "copy"}, folder, log=lambda m: None)
        check("copy: the folder is copied under src/ and its tree checksum recorded",
              (folder / "src" / "bin" / "mytool").is_file() and entry["sha256"] == src.tree_checksum(tool_src) and entry["mode"] == "copy")
        before = src.tree_checksum(folder / "src")
        (tool_src / "README").write_text("v2")
        check("copy: later changes to the original do not touch the copy (reproducible)", src.tree_checksum(folder / "src") == before
              and src.tree_checksum(tool_src) != before)
        logs = []
        entry = src.install_local({"name": "l2", "path": str(tool_src), "mode": "link"}, tmp / "l2", log=logs.append)
        check("link: nothing is copied, the path and checksum are recorded, and it warns the tool can change",
              not (tmp / "l2" / "src").exists() and entry["src"] == str(tool_src.resolve()) and any("can change" in l for l in logs), logs)
        single_file = tmp / "solo.py"
        single_file.write_text("print(1)\n")
        entry = src.install_local({"name": "l3", "path": str(single_file)}, tmp / "l3", log=lambda m: None)
        check("a single file is copied as src/<name> with its sha256", (tmp / "l3" / "src" / "solo.py").is_file()
              and entry["sha256"] == src.file_sha256(single_file) and entry["kind"] == "file")
        msg = raises(src.install_local, {"name": "l4", "path": str(tmp / "missing")}, tmp / "l4", log=lambda m: None)
        check("a missing path names it and the fix", "does not exist" in msg and "missing" in msg, msg)
        os.environ["PLASBENCH_TOOL_MAX_DOWNLOAD_MB"] = "1"
        big = tmp / "big.bin"
        big.write_bytes(b"0" * (2 * 1024 * 1024))
        msg = raises(src.install_local, {"name": "l5", "path": str(big)}, tmp / "l5", log=lambda m: None)
        os.environ.pop("PLASBENCH_TOOL_MAX_DOWNLOAD_MB")
        check("a copy over the size cap is refused with the link alternative (cap set by an environment variable)", "mode = link" in msg, msg)
        check("tilde and $VAR in the path are expanded", src.local_target("~/x") == Path.home() / "x"
              and src.local_target("$PLASBENCH_NOT_SET_XYZ/y").name == "y")

        print("through the manifest: {src}, install plan, fingerprint")
        tools = tmp / "tools"
        url_manifest = manifest(tools / "src_tool", "method = url\nurl = https://example.org/tool-1.0.tar.gz\n"
                                f"sha256 = {sha}\nbuild_command = make -C {{src}}\nverify_command = {{src}}/run.sh --help")
        tool = ut.UserTool(url_manifest)
        check("{src} is the folder src/ beside the manifest", tool.src_path() == tool.folder / "src")
        inputs = {"contigs": str(tmp / "c.fa"), "graph": "", "reads_1": "", "reads_2": "", "long_reads": ""}
        (tmp / "c.fa").write_text(">c\nACGT\n")
        spec = tool.run_spec("s1", inputs, str(tmp / "out"), "2")
        check("before install the run is skipped with the fix", "not installed" in spec["missing"] and "plasbench install-tools src_tool" in spec["missing"], spec["missing"])
        plan = tool.install_plan()
        check("the install plan fetches the source, builds inside it, and verifies with {src} resolved",
              plan[1][:2] == ["python3", str(Path(ut.__file__).resolve())] and plan[1][2:] == ["fetch", "src_tool"]
              and plan[2][0] == "BUILD" and plan[2][2] == str(tool.folder / "src") and str(tool.folder / "src") in plan[2][1]
              and plan[-1][0] == "VERIFY" and str(tool.folder / "src") in plan[-1][1], plan)
        before_sig = tool.run_spec("s1", inputs, str(tmp / "out"), "2")["checksum"]
        tool.install_source(fetch=fake_fetch(payload), log=lambda m: None)
        spec = tool.run_spec("s1", inputs, str(tmp / "out"), "2")
        check("after install {src} is substituted (shell-quoted) into the command", spec["missing"] == "" and str(tool.folder / "src") in spec["command"], spec)
        check("downloaded files do not enter the manifest checksum, but the recorded download does change the fingerprint",
              spec["checksum"] != before_sig and tool.checksum() == ut.UserTool(url_manifest).checksum())
        check("the run spec carries the tasks and the source summary", spec["task_ids"] == "src_tool=binning_reconstruction"
              and '"method": "url"' in spec["source"] and sha in spec["source"], spec["source"])
        a = ut.UserTool(manifest(tmp / "t_a" / "src_tool", f"method = url\nurl = https://example.org/a.tar.gz\nsha256 = {sha}"))
        b = ut.UserTool(manifest(tmp / "t_b" / "src_tool", f"method = url\nurl = https://example.org/b.tar.gz\nsha256 = {sha}"))
        c = ut.UserTool(manifest(tmp / "t_c" / "src_tool", f"method = url\nurl = https://example.org/a.tar.gz\nsha256 = {'1' * 64}"))
        sig = lambda t: t.source_signature()  # noqa: E731
        check("source_signature differs for a different URL and for a different pinned sha256, and is stable for the same manifest",
              len({sig(a), sig(b), sig(c)}) == 3 and sig(a) == sig(ut.UserTool(a.path)))

        local_dir = tmp / "localtool"
        (local_dir / "bin").mkdir(parents=True)
        (local_dir / "bin" / "run.sh").write_text("echo a\n")
        for mode in ("copy", "link"):
            lm = ut.UserTool(manifest(tmp / f"lt_{mode}" / "src_tool", f"method = local\npath = {local_dir.as_posix()}\nmode = {mode}"))
            expected = lm.folder / "src" if mode == "copy" else local_dir
            check(f"local {mode}: {{src}} is {'a copy under src/' if mode == 'copy' else 'the located folder itself'}", lm.src_path() == expected, lm.src_path())
            if mode == "copy":
                lm.install_source(log=lambda m: None)
            first = lm.source_signature()
            (local_dir / "bin" / "run.sh").write_text("echo b with more bytes\n")
            if mode == "copy":
                check("local copy: editing the original does not change the fingerprint until it is installed again", lm.source_signature() == first)
                lm.install_source(log=lambda m: None)
                check("local copy: installing again records the new checksum, so the fingerprint changes", lm.source_signature() != first)
            else:
                check("local link: a changed file changes the fingerprint (it is read on every run)", lm.source_signature() != first)
            (local_dir / "bin" / "run.sh").write_text("echo a\n")
        warn_manifest = ut.validate_text("[tool]\nname = ll\ntask = classification\nanalysis_track = short_read\n[install]\nmethod = local\n"
                                         f"path = {local_dir.as_posix()}\nmode = link\n[run]\nmode = command\ncommand = {{src}}/bin/run.sh {{contigs}}\n"
                                         "requires = contigs\n[output]\nformat = contig_labels\npath = l.tsv\nlabel_column = 2\n")
        check("local link validates with a warning that the tool can change under the benchmark",
              warn_manifest["ok"] and any("change under the benchmark" in w for w in warn_manifest["warnings"]), warn_manifest)

    if FAILED:
        print("USER TOOL SOURCE TESTS FAILED")
        return 1
    print("ALL USER TOOL SOURCE TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
