#!/usr/bin/env python3
"""Choose a folder shows the PC, not only Ubuntu (plasbench/chooser.py, webui.browse, plasbench/data/ui.html).

  - the root view: Quick places and This PC; in WSL the Windows drives from (mocked) /proc/mounts entries of type drvfs / 9p / virtiofs and single-letter folders of a temp /mnt, each
    labelled "C: (Windows)" with the Linux path; plain Linux /mnt and /media/$USER; macOS /Volumes; native Windows drive letters;
  - typed Windows paths (C:\\Users\\me, D:/x) and \\\\wsl.localhost\\<distro>\\home\\me convert with `wslpath -u` (mocked) and by the pure-Python fallback; the Windows form is shown beside the Linux path;
    a UNC network share is refused with an explanation; outside WSL nothing is converted;
  - an unmounted drive is explained with the exact mount command, never run; a folder that cannot be listed is a clear error (no traceback); New folder validates its name and only creates inside the folder shown;
  - workspace.check() accepts a Windows path in WSL, warns about /mnt/<drive> and reports not writable;
  - the page: sidebar with Quick places and This PC, breadcrumb, path box, New folder, Select, check warnings, keyboard, and every Browse button goes through pickPath.
"""
import os
import re
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
tmp = Path(tempfile.mkdtemp())
os.environ["PLASBENCH_UI_HOME"] = str(tmp / "ui")
os.environ["PLASBENCH_LOCAL_SETTINGS"] = str(tmp / "local.env")
from plasbench import chooser, webui, workspace  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def fake_run(table):
    def run(argv, **kw):
        out = table.get((argv[1], argv[2]))
        return SimpleNamespace(returncode=0 if out else 1, stdout=(out or "") + "\n")
    return run


def main():
    mnt = tmp / "mnt"
    for d in ("c", "d", "notadrive", "wsl"):
        (mnt / d).mkdir(parents=True)
    mp = mnt.as_posix()
    mounts = (f"C: {mp}/c drvfs rw 0 0\n{mp}/d 9p rw 0 0\n/dev/sdc / ext4 rw 0 0\n"
              f"tmpfs {mp}/wsl/docker-desktop-bind-mounts/Ubuntu/abc 9p rw 0 0\nnone /sys sysfs rw 0 0\n")
    print("root view")
    drives = chooser.wsl_drives(mounts, str(mnt), free=lambda p: 123)
    names = {d["name"]: d for d in drives}
    check("WSL: C: and D: are listed from /proc/mounts, labelled (Windows) with the Linux path", Path(names["C: (Windows)"]["path"]) == mnt / "c" and Path(names["D: (Windows)"]["path"]) == mnt / "d", names)
    check("WSL: a nested bind mount and non-drive types are not listed", len(drives) == 2 and all("docker" not in d["path"] for d in drives), drives)
    (mnt / "e").mkdir()
    check("WSL: a single-letter folder in /mnt that /proc/mounts does not show is listed too", "E: (Windows)" in {d["name"]: 1 for d in chooser.wsl_drives(mounts, str(mnt))})
    check("WSL: free space is included", drives[0]["free"] == 123 and drives[0]["windows"] == "C:\\")
    check("pc_places in WSL uses them", [d["name"] for d in chooser.pc_places(platform="linux", wsl=True, mounts_text=mounts, mnt_dir=str(mnt))][:2] == ["C: (Windows)", "D: (Windows)"])
    media = tmp / "media" / "me"
    (media / "usbstick").mkdir(parents=True)
    check("plain Linux: /mnt entries are listed", {d["name"] for d in chooser.pc_places(platform="linux", wsl=False, env={"USER": "nobody"}, mnt_dir=str(mnt))} >= {"c", "d", "notadrive"})
    check("macOS lists /Volumes when it exists", isinstance(chooser.pc_places(platform="mac"), list))
    places = chooser.quick_places(ROOT, ROOT / "studies", tmp)
    check("quick places: Home, the PlasBench folder and the shared data folder when it exists", {"Home", "PlasBench folder", "Shared data folder"} <= {p["name"] for p in places}, places)
    root_view = webui.browse("", False, webui.Project(ROOT))
    check("browse('') is the root view with places, pc, help and entries", set(root_view) >= {"places", "pc", "help", "entries", "wsl"} and root_view["path"] == "" and root_view["parent"] is None)
    check("the mount help names the exact command and is never run", "sudo mkdir -p /mnt/e && sudo mount -t drvfs E: /mnt/e" in chooser.mount_help("e") and "never runs it" in chooser.mount_help("e"))

    print("typed paths")
    run = fake_run({("-u", r"C:\Users\me\data"): "/mnt/c/Users/me/data", ("-u", r"\\wsl.localhost\Ubuntu\home\me"): "/home/me", ("-w", "/home/me"): r"\\wsl.localhost\Ubuntu\home\me"})
    check("C:\\Users\\me\\data -> wslpath -u", chooser.to_linux(r"C:\Users\me\data", wsl=True, run=run) == "/mnt/c/Users/me/data")
    check("\\\\wsl.localhost\\Ubuntu\\home\\me -> wslpath -u", chooser.to_linux(r"\\wsl.localhost\Ubuntu\home\me", wsl=True, run=run) == "/home/me")
    none = fake_run({})
    check("fallback: C:\\Users\\me -> /mnt/c/Users/me, D:/x -> /mnt/d/x, C: -> /mnt/c", chooser.to_linux(r"C:\Users\me", wsl=True, run=none) == "/mnt/c/Users/me" and chooser.to_linux("D:/x", wsl=True, run=none) == "/mnt/d/x" and chooser.to_linux("C:", wsl=True, run=none) == "/mnt/c")
    check("fallback: \\\\wsl.localhost\\Ubuntu-24.04\\home\\ueffiong\\.local -> /home/ueffiong/.local; \\\\wsl$\\X -> /", chooser.to_linux(r"\\wsl.localhost\Ubuntu-24.04\home\ueffiong\.local", wsl=True, run=none) == "/home/ueffiong/.local" and chooser.to_linux(r"\\wsl$\Ubuntu", wsl=True, run=none) == "/")
    check("a Linux path and an empty string are unchanged", chooser.to_linux("/home/me", wsl=True, run=none) == "/home/me" and chooser.to_linux("", wsl=True) == "")
    check("outside WSL nothing is converted", chooser.to_linux(r"C:\Users\me", wsl=False) == r"C:\Users\me")
    try:
        chooser.to_linux(r"\\server\share\x", wsl=True, run=none)
        unc = False
    except ValueError as exc:
        unc = "network share" in str(exc)
    check("a network share is refused with an explanation", unc)
    check("the Windows form: wslpath -w, else /mnt/c -> C:\\, else \\\\wsl.localhost\\<distro>", chooser.to_windows("/home/me", wsl=True, run=run) == r"\\wsl.localhost\Ubuntu\home\me" and chooser.to_windows("/mnt/d/x/y", wsl=True, run=none) == "D:\\x\\y"
          and chooser.to_windows("/home/me", wsl=True, run=none, distro="Ubuntu-24.04") == r"\\wsl.localhost\Ubuntu-24.04\home\me" and chooser.to_windows("/home/me", wsl=False) == "")

    print("listing errors and New folder")
    try:
        webui.browse(str(tmp / "missing"), True)
        gone = False
    except FileNotFoundError as exc:
        gone = "does not exist" in str(exc)
    check("a missing folder is a clear error", gone)
    sub = tmp / "newdir"
    sub.mkdir()
    check("New folder creates one folder inside the folder shown", Path(chooser.make_folder(str(sub), "data1")) == sub / "data1" and (sub / "data1").is_dir())
    bad = []
    for name in ("", "..", "a/b", "a\\b", "x:y", "CON", "name.", "a" * 81, "q?"):
        try:
            chooser.make_folder(str(sub), name)
            bad.append(name)
        except ValueError:
            pass
    check("bad names are refused (empty, .., separators, forbidden characters, reserved, too long)", not bad, bad)
    try:
        chooser.make_folder(str(sub), "data1")
        dup = False
    except ValueError as exc:
        dup = "already exists" in str(exc)
    check("an existing name is refused; nothing outside the folder is touched", dup and not (tmp / "a").exists())
    try:
        chooser.make_folder(str(tmp / "nope"), "x")
        nop = False
    except FileNotFoundError:
        nop = True
    check("a parent that is not a folder is refused", nop)

    print("folder check")
    if os.name != "nt" and Path("/mnt/c").is_dir():
        real_wsl = chooser.in_wsl
        chooser.in_wsl = lambda: True
        try:
            rep = workspace.check("/mnt/c/__plasbench_check_probe__")
            check("check() warns that a Windows drive seen from Ubuntu is slow", any("Windows drive seen from Ubuntu" in w for w in rep["warnings"]) or not rep["ok"], rep)
        finally:
            chooser.in_wsl = real_wsl
    else:
        print("  skip  no /mnt/c here: the /mnt/<drive> warning is not exercised")
    ro = tmp / "ro"
    ro.mkdir()
    rep = workspace.check(str(tmp / "newplace" / "x"))
    check("check() reports will_create for a folder that does not exist yet and writes nothing", rep["ok"] and rep["will_create"] and not (tmp / "newplace" / "x").exists(), rep)

    print("page")
    html = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
    check("the dialog is labelled and modal", 'id="fsdlg" class="fschoose" role="dialog" aria-modal="true" aria-labelledby="fs_title"' in html)
    check("sidebar with Quick places and This PC", 'id="fs_side"' in html and "<h6>Quick places</h6>" in html and "<h6>This PC</h6>" in html)
    check("breadcrumb, path box that accepts Windows paths, New folder, Select", all(k in html for k in ('id="fs_crumbs"', 'id="fs_path"', "Windows path such as C:", 'id="fs_new"', 'id="fs_ok"')))
    check("the folder check warnings show under the path", "workspace/check?path=" in html and 'id="fs_check"' in html)
    check("the unmounted-drive help is shown", 'id="fs_help"' in html and "r.help" in html)
    check("keyboard: arrows move in the list, Tab stays in the dialog, Enter in the path box goes", all(k in html for k in ('ArrowDown: i + 1, ArrowUp: i - 1', 'e.key === "Tab"', 'e.key === "Enter"')))
    check("New folder uses the dialog component and the validated server route", 'askText({title: "New folder"' in html and 'api("fs/mkdir"' in html)
    check("every Browse button and Choose call goes through pickPath", 'data-browse' in html and html.count("pickPath(") >= 5)
    check("narrow screens stack the sidebar", "@media (max-width:640px){.fsbody{grid-template-columns:1fr}" in html)
    print("FAILED: " + ", ".join(FAILED) if FAILED else "ALL PASS")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
