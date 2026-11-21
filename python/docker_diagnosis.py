#!/usr/bin/env python3
"""Say WHY a docker pull, build or start failed, from the words docker printed, and what to do about it. Never guess.

PlasBench used to answer an unrecognised pull failure by building the image locally, which takes hours and fails the same way on an engine that cannot write. This reads the
error text with a table of rules (RULES, tried in order, so the priority is visible and a new message is one row), in the style of python/assembler_diagnosis.py:

  python3 -I python/docker_diagnosis.py LOGFILE [--environment desktop_windows|desktop_macos|linux|rootless] [--format text|json]

`diagnose(text, context)` returns
  cause            a short stable id (corrupt_layer, read_only_filesystem, no_space, dockerd_config, daemon_stopped, ... unknown)
  title            one line, in words
  confidence       high (docker says it in words), medium (a symptom points to it), low (nothing recognised: unknown)
  evidence_lines   the lines of the text the verdict rests on (never invented; for unknown, the last 15 lines)
  advice           the steps, in the safe order (a list of sentences); read-only checks first, anything that changes data last and with its consequence
  commands         copyable commands for the environment (read-only diagnostics, and the safe stop/start ones)
  last_resort      [{command, warning}] steps that DELETE or MOVE data: shown with consent text, never run by PlasBench
  retryable        True when trying the same pull again can work (flaky network, a layer cut short)
  engine_unhealthy True when the engine itself cannot work (it cannot write, has no disk, is damaged): stop before any pull or build
  build_ok         True ONLY when the image is genuinely unavailable (not published, private, wrong platform): a local build is then a real remedy
  user_action      True when only the person can fix it (restart or reset Docker Desktop, free disk, log in): PlasBench reports exit 20 "waiting for you"
  environment      desktop_windows | desktop_macos | desktop | linux | rootless | unknown (what the advice is written for)
  also             other causes the text matches as well (the first one in the table is the verdict)

PlasBench runs only read-only diagnostics. Every command here is shown for the person to run; none is run for them. The sample messages in test/test_docker_diagnosis.py are
written from knowledge of docker's message formats (labelled samples, not captured logs), plus the exact messages of the failure seen on a production server.
Standard library only; Python 3.9 compatible.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

TAIL_LINES = 15
MAX_EVIDENCE = 4
LINE_MAX = 300
ENVIRONMENTS = ("desktop_windows", "desktop_macos", "desktop", "linux", "rootless", "unknown")
GHCR_LOGIN = "echo $GITHUB_TOKEN | docker login ghcr.io -u <your GitHub user name> --password-stdin"
# Which advice blocks an environment shows. `unknown` shows all three, each labelled, because nothing says which one applies.
BLOCKS = {"desktop_windows": ["desktop_windows"], "desktop_macos": ["desktop_macos"], "desktop": ["desktop_windows", "desktop_macos"], "linux": ["linux"], "rootless": ["rootless"],
          "unknown": ["linux", "desktop_windows", "desktop_macos"]}
LABELS = {"desktop_windows": "Docker Desktop on Windows (WSL 2)", "desktop_macos": "Docker Desktop on macOS", "linux": "Docker Engine on Linux (systemd)", "rootless": "rootless Docker"}

QUIT_RESET_WIN = ["Quit Docker Desktop completely (tray icon > Quit Docker Desktop), then in Windows PowerShell run `wsl --shutdown`, wait 10 seconds and start Docker Desktop again."]
FREE_C = "Docker Desktop keeps its disk (docker_data.vhdx or the containerd data) on the drive that holds your Windows profile, usually C:. When that drive is full or the disk file is damaged, the engine goes read-only or fails."
UNREGISTER_WARNING = ("ONLY the `docker-desktop` distribution, never Ubuntu or any other distribution of yours (`wsl -l -v` lists them). Every image, container and volume inside Docker Desktop's "
                      "own storage is deleted; Docker Desktop recreates the distribution at its next start.")
PURGE_WARNING = ("Docker Desktop > Troubleshoot > Clean / Purge data deletes ALL images, containers and volumes kept by Docker Desktop; Reset to factory defaults also resets its settings. "
                 "Your own folders and PlasBench's studies are not inside Docker and are not touched.")

# One rule: cause, title, confidence, patterns (any match), flags, advice and commands by environment ("any" applies everywhere).
# flags: retry (a same-pull retry can work), sick (the engine cannot work), build (a local build is a real remedy), user (only the person can fix it).
RULES = [
    dict(cause="dockerd_config", title="Docker Desktop's engine cannot start (damaged install or an invalid engine configuration)", confidence="high",
         patterns=[r"dockerd configuration error", r"daemon\.json is invalid", r"fork/exec\s+\S*dockerd:\s*no such file", r"unable to configure the docker daemon with file",
                   r"service command failed", r"failed to start daemon:.*(config|json)", r"invalid character .* in .*daemon\.json|json: cannot unmarshal .*daemon"],
         sick=True, user=True,
         advice={"any": ["Despite the wording, `daemon.json is invalid` together with `fork/exec .../dockerd: no such file or directory` means the engine program (dockerd) is MISSING where Docker looks for it: "
                         "a damaged or half-finished Docker update, or damaged storage under it. It is rarely a typing error in your own settings. PlasBench stopped before pulling or building: no engine, nothing to build with.",
                         "If you edited the Docker Engine JSON yourself, check it is valid JSON first (a stray comma is the other common cause)."],
                 "desktop_windows": QUIT_RESET_WIN + ["Open Docker Desktop > Settings > Docker Engine and press Reset to default if you changed it; then Apply & restart.",
                                                      "Still failing: Docker Desktop > Troubleshoot > Reset to factory defaults (see the warning below), or uninstall and reinstall Docker Desktop (keep this version's installer from docker.com).",
                                                      FREE_C + " Free space there first (Settings > Resources > Disk image location shows where)."],
                 "desktop_macos": ["Quit Docker Desktop (menu bar whale > Quit), reopen it from Applications and wait for `Docker Desktop is running`.", "Still failing: Troubleshoot > Reset to factory defaults, or reinstall Docker Desktop.",
                                   "Check the Mac has free disk space (Apple menu > About This Mac > Storage)."],
                 "linux": ["Check the engine program exists and the configuration is valid JSON (the commands below only read). A package that lost files is repaired by reinstalling it (`sudo apt-get install --reinstall docker-ce` or `sudo dnf reinstall docker-ce`), then `sudo systemctl restart docker`."],
                 "rootless": ["Check `dockerd-rootless.sh` exists (`which dockerd-rootless.sh`) and that ~/.config/docker/daemon.json is valid JSON; reinstall with `dockerd-rootless-setuptool.sh install` if files are missing."]},
         commands={"desktop_windows": ["wsl --shutdown", "wsl -l -v"], "linux": ["command -v dockerd; ls -l \"$(command -v dockerd)\"", "python3 -m json.tool /etc/docker/daemon.json", "sudo dockerd --validate --config-file=/etc/docker/daemon.json",
                                                                                "sudo journalctl -u docker --since '1 hour ago' | tail -50", "dpkg -V docker-ce  # or: rpm -V docker-ce"],
                   "rootless": ["which dockerd-rootless.sh", "python3 -m json.tool ~/.config/docker/daemon.json"]},
         last_resort={"desktop_windows": [("wsl --unregister docker-desktop", UNREGISTER_WARNING), ("Docker Desktop > Troubleshoot > Reset to factory defaults", PURGE_WARNING)],
                      "desktop_macos": [("Docker Desktop > Troubleshoot > Reset to factory defaults", PURGE_WARNING)]}),
    dict(cause="read_only_filesystem", title="the filesystem Docker writes to is read-only", confidence="high",
         patterns=[r"read-only file system", r"readonly (database|file ?system)", r"attempt to write a readonly database", r"\bEROFS\b"],
         sick=True, user=True,
         advice={"any": ["The disk or storage Docker keeps its images and metadata on has become read-only: the engine cannot write (a Linux disk is remounted read-only after disk or filesystem errors; Docker Desktop's virtual disk can go read-only after a crash, a full drive or a forced shutdown). "
                         "PlasBench stopped before pulling or building: a local build would run for hours and fail at the first write. Do not retry or build until this is fixed.",
                         "Look first: the read-only commands below show where Docker keeps its data and how it is mounted."],
                 "linux": ["Safe order: 1) free space if the disk is full (`df -h /var/lib/docker`); 2) read the kernel log: `I/O error` lines mean the disk itself is failing (back up and replace it); "
                           "3) stop Docker: `sudo systemctl stop docker docker.socket containerd`; 4) fsck the filesystem while it is UNMOUNTED (never fsck a mounted filesystem; the device is the SOURCE column of findmnt; a root filesystem needs a rescue boot); "
                           "5) remount read-write (`sudo mount -o remount,rw <mount point>`) or reboot; 6) `sudo systemctl start docker`, then `plasbench runtime doctor`."],
                 "rootless": ["Rootless Docker keeps data under ~/.local/share/docker: check that this folder's disk is writable (`touch ~/.local/share/docker/.t && rm ~/.local/share/docker/.t`) and not full (`df -h ~`), then `systemctl --user restart docker`."],
                 "desktop_windows": QUIT_RESET_WIN + [FREE_C, "If the next start is still read-only: Docker Desktop > Troubleshoot > Clean / Purge data, then Reset to factory defaults (see the warning below)."],
                 "desktop_macos": ["Quit Docker Desktop completely and reopen it. Check the Mac has free disk space.", "Still read-only: Troubleshoot > Clean / Purge data, then Reset to factory defaults (see the warning below)."]},
         commands={"linux": ["docker info | grep -i 'docker root dir'", "df -h /var/lib/docker", "findmnt -T /var/lib/docker -o TARGET,SOURCE,FSTYPE,OPTIONS", "mount | grep ' /var/lib/docker'",
                             "dmesg | grep -i -E 'ext4|xfs|I/O error|remount' | tail -30", "sudo journalctl -u docker -u containerd --since '1 hour ago' | tail -50",
                             "sudo systemctl stop docker docker.socket containerd", "sudo systemctl start docker"],
                   "rootless": ["df -h ~", "systemctl --user restart docker"], "desktop_windows": ["wsl --shutdown", "wsl -l -v"]},
         last_resort={"linux": [("sudo docker system prune", "removes stopped containers, unused networks and dangling images; it frees space but cannot repair a read-only disk. Images in use are kept."),
                                ("sudo mv /var/lib/docker /var/lib/docker.old", "moves ALL images, containers and volumes aside (Docker recreates an empty folder). Only with Docker stopped and your volumes backed up; delete the old folder only when sure.")],
                      "desktop_windows": [("wsl --unregister docker-desktop", UNREGISTER_WARNING), ("Docker Desktop > Troubleshoot > Clean / Purge data", PURGE_WARNING)],
                      "desktop_macos": [("Docker Desktop > Troubleshoot > Clean / Purge data", PURGE_WARNING)]}),
    dict(cause="wsl_desktop_failure", title="Docker Desktop's WSL 2 backend stopped or cannot start", confidence="high",
         patterns=[r"docker desktop is unable to start", r"docker desktop - wsl distro terminated abruptly", r"wsl distro terminated abruptly", r"Wsl/Service/\S+", r"\bHCS_E_\w+|WSL_E_\w+|\b0x8007\w{4}\b.*wsl",
                   r"the virtual machine or container .* (is not|could not)", r"wsl --update", r"WSL 2 (requires|is not) ", r"vmcompute"],
         sick=True, user=True,
         advice={"any": ["Docker Desktop's Linux backend (WSL 2) terminated or did not start, so there is no engine to pull or build with."],
                 "desktop_windows": ["In Windows PowerShell: `wsl --shutdown`, then `wsl --update`, then start Docker Desktop again (wait for `Engine running`).", "Check virtualization is on (Task Manager > Performance > CPU > Virtualization: Enabled) and the Windows features `Virtual Machine Platform` and `Windows Subsystem for Linux` are installed.",
                                     "If a HRESULT such as Wsl/Service/... appears again, restart Windows, then try once more; " + FREE_C],
                 "desktop_macos": ["Quit and reopen Docker Desktop; update it from the menu bar whale > Check for updates."],
                 "linux": ["This message is about Docker Desktop's WSL backend; on a Linux engine see the other diagnoses (`sudo systemctl status docker`)."]},
         commands={"desktop_windows": ["wsl --shutdown", "wsl --update", "wsl -l -v", "wsl --status"]},
         last_resort={"desktop_windows": [("wsl --unregister docker-desktop", UNREGISTER_WARNING), ("Docker Desktop > Troubleshoot > Reset to factory defaults", PURGE_WARNING)]}),
    dict(cause="inodes_exhausted", title="Docker's disk has no free inodes", confidence="high",
         patterns=[r"no (free )?inodes", r"out of inodes", r"inode.*(exhaust|full|limit)", r"\bIFree\b.*\b100%"],
         sick=True, user=True,
         advice={"any": ["The filesystem has free space but no free inodes (millions of tiny files, usually unused images or build cache): new files cannot be created. PlasBench stopped before pulling or building."],
                 "linux": ["Confirm with `df -i`, free inodes by removing unused Docker data you no longer need (`docker system df` shows what is reclaimable; the prune commands below delete data), or move Docker's data folder to a larger filesystem."],
                 "desktop_windows": ["Docker Desktop > Troubleshoot > Clean / Purge data frees inodes (deletes all Docker data: see below), or use `docker system prune` from a terminal."],
                 "desktop_macos": ["Docker Desktop > Troubleshoot > Clean / Purge data, or `docker system prune` from a terminal."]},
         commands={"linux": ["df -i /var/lib/docker", "docker system df"], "desktop_windows": ["docker system df"], "desktop_macos": ["docker system df"]},
         last_resort={"any": [("docker system prune", "removes stopped containers, unused networks and dangling images; add --all only if you accept deleting every image not in use by a container."),
                              ("docker builder prune -f", "removes the build cache only; the next build starts from nothing and is slow.")]}),
    dict(cause="no_space", title="Docker's disk is full", confidence="high",
         patterns=[r"no space left on device", r"disk quota exceeded", r"\bENOSPC\b", r"not enough (disk )?space", r"insufficient (disk )?space", r"write /var/lib/docker/.*: no space"],
         sick=True, user=True,
         advice={"any": ["The disk Docker keeps its images on has no free space left. A pull or build only makes it worse and a half-written layer can be damaged. PlasBench stopped before pulling or building.",
                         "Free space first; the commands below only read (they show where Docker's disk is and what uses it)."],
                 "linux": ["Check `docker info | grep 'Docker Root Dir'` and `df -h` of that folder; free space on THAT filesystem (not just your home). If Docker's folder is on a small partition, move it to a larger disk (`data-root` in /etc/docker/daemon.json) after stopping Docker."],
                 "rootless": ["Rootless Docker uses ~/.local/share/docker: free space on the filesystem of your home folder (`df -h ~`)."],
                 "desktop_windows": [FREE_C, "Free space on that drive (Windows Settings > System > Storage), or move Docker's disk image: Docker Desktop > Settings > Resources > Advanced > Disk image location. Raise the virtual disk limit there if it is the limit that is full."],
                 "desktop_macos": ["Free space on the Mac, or raise Docker Desktop > Settings > Resources > Virtual disk limit, then Apply & restart."]},
         commands={"linux": ["docker info | grep -i 'docker root dir'", "df -h /var/lib/docker", "docker system df"], "rootless": ["df -h ~", "docker system df"], "desktop_windows": ["docker system df"], "desktop_macos": ["docker system df", "df -h"]},
         last_resort={"any": [("docker system prune", "removes stopped containers, unused networks and dangling images. Review `docker system df` first; add --all only if you accept deleting every image not used by a container."),
                              ("docker builder prune -f", "removes the build cache only; the next build is slow.")]}),
    dict(cause="storage_driver", title="Docker's storage driver or containerd failed", confidence="high",
         patterns=[r"overlay2?:.*(invalid argument|no such file|input/output error|operation not permitted)", r"failed to mount .*overlay", r"mount.*overlay.*(invalid argument|failed)", r"snapshotter",
                   r"containerd:.*(bolt|timeout|database)", r"bolt.*(timeout|locked|corrupt)|meta\.db", r"database is locked", r"failed to create (shim|task)", r"error creating overlay mount",
                   r"driver .*overlay.* failed|failed to (initialize|start) .*storage driver", r"input/output error"],
         sick=True, user=True,
         advice={"any": ["The engine's storage layer (overlay2 / containerd snapshotter / its metadata database) reported an error. Pulling or building again will not help and can leave half-written layers. PlasBench stopped before pulling or building.",
                         "Typical causes: the disk is full or read-only, a filesystem that does not support overlay (some network or encrypted folders), a crash that left the metadata database locked or damaged, or a kernel/Docker mismatch."],
                 "linux": ["Read the engine log (`sudo journalctl -u docker -u containerd`), check `docker info | grep -i -E 'storage driver|backing filesystem|root dir'`: overlay2 needs ext4 or xfs with d_type (`ftype=1`). Then restart the services: `sudo systemctl restart containerd docker`.",
                           "A locked database is released by restarting; a damaged one needs Docker's data folder rebuilt (last resort, deletes all Docker data)."],
                 "rootless": ["Rootless overlay needs kernel 5.11+ or fuse-overlayfs: `docker info | grep -i 'storage driver'`; restart with `systemctl --user restart docker`."],
                 "desktop_windows": QUIT_RESET_WIN + [FREE_C],
                 "desktop_macos": ["Quit and reopen Docker Desktop; free disk space on the Mac."]},
         commands={"linux": ["docker info | grep -i -E 'storage driver|backing filesystem|root dir|supports d_type'", "df -h /var/lib/docker", "sudo journalctl -u docker -u containerd --since '1 hour ago' | tail -50",
                             "sudo systemctl restart containerd docker"], "rootless": ["docker info | grep -i 'storage driver'", "systemctl --user restart docker"], "desktop_windows": ["wsl --shutdown"]},
         last_resort={"linux": [("sudo mv /var/lib/docker /var/lib/docker.old", "moves ALL images, containers and volumes aside; only with Docker stopped and volumes backed up.")],
                      "desktop_windows": [("Docker Desktop > Troubleshoot > Clean / Purge data", PURGE_WARNING)], "desktop_macos": [("Docker Desktop > Troubleshoot > Clean / Purge data", PURGE_WARNING)]}),
    dict(cause="corrupt_layer", title="a downloaded image layer is corrupted or incomplete", confidence="high",
         patterns=[r"incomplete deflate data", r"unpigz:.*corrupted|corrupted -- ", r"failed to extract layer", r"invalid checksum", r"digest mismatch|content digest .* not found|expected sha256:.* got sha256:",
                   r"failed to register layer", r"invalid diff ?id|diffid", r"(layer|gzip|unpigz|extract|apply|untar|tar:).{0,200}unexpected EOF|unexpected EOF.{0,200}(layer|gzip|tar)", r"gzip: invalid header|not in gzip format|invalid tar header|unexpected end of (gzip|tar)"],
         retry=True,
         advice={"any": ["A layer of the image was cut short or altered on its way to this computer (an unstable connection, a proxy or antivirus that rewrites downloads) or the local layer store is damaged. "
                         "Finished layers are kept, so pulling the same image again usually fixes a transient cut; PlasBench retries up to PLASBENCH_DOCKER_PULL_RETRIES times (default 2) and then stops.",
                         "Do NOT build the image locally to get around it: the build pulls the same base layers and needs far more time and space.",
                         "Check for a proxy first (proxies commonly corrupt large downloads): the command below prints Docker's proxy settings. Try another network, a wired connection or a VPN off.",
                         "If it repeats for different images, suspect the disk or memory (kernel log: `I/O error`), see the read-only diagnosis; if only this image repeats, remove the partial image and pull again (shown below: it deletes that image only)."],
                 "linux": ["Also check free space and the disk: `df -h /var/lib/docker`, `dmesg | grep -i 'I/O error'`; then `sudo systemctl restart docker` and pull again."],
                 "desktop_windows": ["Restart Docker Desktop (and `wsl --shutdown`) and pull again; if the same layer fails again, Troubleshoot > Clean / Purge data is the last step (see below)."],
                 "desktop_macos": ["Restart Docker Desktop and pull again; Troubleshoot > Clean / Purge data is the last step (see below)."]},
         commands={"any": ["docker info | grep -i -E 'proxy|root dir|storage driver'", "docker pull {image}"], "linux": ["df -h /var/lib/docker", "dmesg | grep -i -E 'I/O error|ext4|xfs' | tail -20", "sudo journalctl -u docker -u containerd --since '1 hour ago' | tail -50"]},
         last_resort={"any": [("docker image rm {image}", "deletes this image (and its downloaded layers) from this computer; the next pull downloads it all again."),
                              ("docker builder prune -f", "removes the build cache only.")],
                      "desktop_windows": [("Docker Desktop > Troubleshoot > Clean / Purge data", PURGE_WARNING)], "desktop_macos": [("Docker Desktop > Troubleshoot > Clean / Purge data", PURGE_WARNING)]}),
    dict(cause="cgroup_systemd", title="a cgroup or systemd problem stops containers from starting", confidence="medium",
         patterns=[r"cgroups?:.*(not|cannot|failed|mountpoint|no such)", r"failed to (create|join) .*cgroup", r"oci runtime create failed.*(cgroup|systemd)", r"systemd.*(cgroup|dbus|slice)",
                   r"cgroup2? .*(not (mounted|supported)|hierarchy)", r"unable to apply cgroup|openat2 .*cgroup"],
         sick=True, user=True,
         advice={"any": ["The container runtime could not set up cgroups (the resource limits of a container): Docker and the init system disagree about the cgroup driver, or cgroups are not mounted."],
                 "linux": ["Compare `docker info | grep -i cgroup` with the init system (`stat -fc %T /sys/fs/cgroup` prints cgroup2fs for v2); the usual fix is the same driver on both (`\"exec-opts\": [\"native.cgroupdriver=systemd\"]` in /etc/docker/daemon.json) then `sudo systemctl restart docker`. Check the kernel log for related errors."],
                 "rootless": ["Rootless Docker with cgroup v2 needs systemd user sessions and delegation: see docs.docker.com/engine/security/rootless/ (\"Limiting resources\"); `loginctl enable-linger $USER` keeps the user session alive."],
                 "desktop_windows": QUIT_RESET_WIN, "desktop_macos": ["Quit and reopen Docker Desktop."]},
         commands={"linux": ["docker info | grep -i -E 'cgroup|init'", "stat -fc %T /sys/fs/cgroup", "sudo journalctl -u docker --since '1 hour ago' | tail -50"], "desktop_windows": ["wsl --shutdown"]}),
    dict(cause="wsl_integration_off", title="Docker Desktop's WSL integration is off for this Linux distribution", confidence="high",
         patterns=[r"could not be found in this wsl 2 distro", r"activate the wsl integration", r"docker: command .* not found.*wsl"],
         sick=True, user=True,
         advice={"any": ["The docker command in this Linux (WSL) distribution is only a stub: Docker Desktop's WSL integration is switched off for it."],
                 "desktop_windows": ["Docker Desktop > Settings > Resources > WSL integration > switch on this distribution > Apply & restart. PlasBench can open that page: `plasbench install-tools docker --open-integration`."],
                 "linux": ["Inside WSL: see the Docker Desktop WSL integration (docs.docker.com/desktop/features/wsl/) or install Docker Engine in this distribution."]},
         commands={"desktop_windows": ["plasbench install-tools docker --open-integration", "wsl -l -v"]}),
    dict(cause="permission_socket", title="this account may not use the Docker socket", confidence="high",
         patterns=[r"permission denied while trying to connect to the docker daemon socket", r"got permission denied while trying to connect", r"permission denied.*docker\.sock"],
         sick=True, user=True,
         advice={"any": ["Docker is running but this account is not allowed to talk to it (the same state `plasbench install-tools docker` reports as permission needed)."],
                 "linux": ["Add your user to the docker group, then log out and back in (or `newgrp docker`): `sudo usermod -aG docker $USER`. Check with `id -nG`. The docker group is root-equivalent: only for users you trust.", "Or run PlasBench from an account that already has access."],
                 "rootless": ["Rootless Docker: point DOCKER_HOST at your own socket: `export DOCKER_HOST=unix:///run/user/$(id -u)/docker.sock` and make sure `systemctl --user status docker` is active."],
                 "desktop_windows": ["Inside WSL the user must be in the docker group or Docker Desktop's integration must be on: `plasbench install-tools docker` shows the exact state."],
                 "desktop_macos": ["Start Docker Desktop; check `ls -l /var/run/docker.sock` or `docker context ls`."]},
         commands={"linux": ["id -nG", "ls -l /var/run/docker.sock", "sudo usermod -aG docker $USER"], "rootless": ["export DOCKER_HOST=unix:///run/user/$(id -u)/docker.sock", "systemctl --user status docker"],
                   "desktop_windows": ["plasbench install-tools docker"], "desktop_macos": ["docker context ls"]}),
    dict(cause="daemon_stopped", title="the Docker engine is not running", confidence="high",
         patterns=[r"cannot connect to the docker daemon", r"is the docker daemon running", r"error during connect", r"docker daemon is not running", r"dockerDesktopLinuxEngine", r"open //\./pipe/docker",
                   r"error response from daemon: .*(daemon|engine) is (shutting down|not ready)", r"connection refused.*docker\.sock|docker\.sock.*(no such file|connection refused)", r"cannot connect to .*docker\.sock"],
         sick=True, user=True,
         advice={"any": ["Docker is installed but its engine is not answering (not started, still starting, or crashed). This is the `Docker is not running` state of `plasbench install-tools docker`."],
                 "desktop_windows": ["Start Docker Desktop (Start menu, or `plasbench install-tools docker --start`) and wait until it says `Engine running`; the first start takes a few minutes. If it will not start, see `Docker Desktop is unable to start` and run `wsl --shutdown` first."],
                 "desktop_macos": ["Start Docker Desktop (`open -a Docker`) and wait for the whale to stop animating."],
                 "linux": ["`sudo systemctl status docker` shows why; start it with `sudo systemctl start docker` (and `sudo systemctl enable docker` to start at boot). If it fails to start: `sudo journalctl -u docker -n 50`."],
                 "rootless": ["`systemctl --user status docker`, then `systemctl --user start docker`; `DOCKER_HOST` must be unix:///run/user/$(id -u)/docker.sock."]},
         commands={"desktop_windows": ["plasbench install-tools docker --start", "wsl --shutdown"], "desktop_macos": ["open -a Docker"], "linux": ["sudo systemctl status docker --no-pager", "sudo systemctl start docker", "sudo journalctl -u docker -n 50 --no-pager"],
                   "rootless": ["systemctl --user status docker --no-pager", "systemctl --user start docker"]}),
    dict(cause="engine_timeout", title="Docker did not answer in time (the engine is hung or very slow)", confidence="medium",
         patterns=[r"docker did not answer in time", r"context deadline exceeded.*(docker|daemon)|request returned 5\d\d .* for API route"],
         sick=True, user=True,
         advice={"any": ["The engine accepted the connection but did not answer: it is hung, starting, or its disk is stuck. Waiting longer rarely helps."],
                 "linux": ["Check `sudo systemctl status docker` and the kernel log for disk problems; `sudo systemctl restart docker` (running containers stop)."],
                 "desktop_windows": QUIT_RESET_WIN, "desktop_macos": ["Quit Docker Desktop and reopen it; if it hangs again use Troubleshoot > Restart."]},
         commands={"linux": ["sudo systemctl status docker --no-pager", "dmesg | grep -i -E 'I/O error|blocked for more than' | tail -20"], "desktop_windows": ["wsl --shutdown"]}),
    dict(cause="rate_limited", title="the registry limits how often images can be pulled (rate limit)", confidence="high",
         patterns=[r"toomanyrequests", r"rate limit", r"too many requests", r"\b429\b.*(pull|registry|manifest)"],
         advice={"any": ["The registry is refusing pulls from this address for now (many computers behind one address, or an anonymous limit). It clears by itself; PlasBench does not build locally for this.",
                         "Log in to raise the limit (a free account is enough), wait some minutes, or pull through a mirror inside your organisation."],
                 "linux": ["`docker login` (Docker Hub) or, for ghcr.io, a GitHub token: `" + GHCR_LOGIN + "`."]},
         commands={"any": [GHCR_LOGIN]}),
    dict(cause="image_not_found", title="the image or its tag does not exist in the registry", confidence="high",
         patterns=[r"manifest unknown", r"manifest for .* not found", r"not found: manifest", r"repository does not exist", r"name unknown", r"\bnot found: not found\b", r"no such image.*registry|tag does not exist",
                   r"failed to resolve reference .*: .*not found"],
         build=True,
         advice={"any": ["The registry answered, and it has no such image or tag (this version of PlasBench has not been published as an image, or the name was mistyped). Building it here from the Dockerfile is the remedy: `plasbench runtime build --yes` (long, needs the internet and several GB).",
                         "Or choose an image that exists: set PLASBENCH_DOCKER_IMAGE (Settings) to a tag from the project's packages page."]},
         commands={"any": ["plasbench runtime build --yes"]}),
    dict(cause="access_denied", title="the registry refused access to the image (private, not yet public, or a stale login)", confidence="high",
         patterns=[r"pull access denied", r"unauthorized", r"(?<!permission )denied: ", r"error from registry: denied", r"requested access to the resource is denied", r"authentication required", r"insufficient_scope", r"\b403\b.*(forbidden|ghcr)"],
         build=True,
         advice={"any": ["The registry refused the pull: the image is private or not yet public, or a login stored on this computer is stale or lacks the `read:packages` permission.",
                         "If you have access, log in with a GitHub personal access token (classic, `read:packages`): `" + GHCR_LOGIN + "`. If an old login is the cause: `docker logout ghcr.io` first.",
                         "If the image is simply not public yet, building it here is the remedy: `plasbench runtime build --yes` (consent needed; hours)."]},
         commands={"any": [GHCR_LOGIN, "docker logout ghcr.io", "plasbench runtime build --yes"]}),
    dict(cause="platform_mismatch", title="the image is not built for this computer's architecture", confidence="high",
         patterns=[r"no matching manifest for", r"exec format error", r"platform .* does not match", r"requested image's platform", r"image with reference .* was found but does not match"],
         build=True,
         advice={"any": ["The published image is built for linux/amd64 and this computer is a different architecture (for example ARM). Building natively here IS the fix: `plasbench runtime build --yes` makes an image for this computer.",
                         "On Apple Silicon, Docker Desktop can instead run the amd64 image under emulation (slow): `export DOCKER_DEFAULT_PLATFORM=linux/amd64`. An `exec format error` after a successful pull means the emulator (QEMU/binfmt) is missing: `docker run --privileged --rm tonistiigi/binfmt --install all`."]},
         commands={"any": ["plasbench runtime build --yes", "docker info --format '{{.Architecture}}'"]}),
    dict(cause="tls_clock", title="the computer's clock is wrong, so the registry certificate looks invalid", confidence="high",
         patterns=[r"certificate has expired or is not yet valid", r"x509: certificate (has expired|is not yet valid)", r"certificate is not valid .* current time", r"current time .* is after"],
         user=True,
         advice={"any": ["The certificate check failed because of the date: the clock of this computer (or of Docker Desktop's virtual machine after sleep or hibernation) is wrong. Check with `date -u`."],
                 "linux": ["Enable time sync: `sudo timedatectl set-ntp true`, check `timedatectl status`."],
                 "desktop_windows": ["Windows: Settings > Time & language > Date & time > Sync now; then `wsl --shutdown` and restart Docker Desktop (the WSL clock can drift after sleep)."],
                 "desktop_macos": ["System Settings > General > Date & Time > set automatically; restart Docker Desktop."]},
         commands={"any": ["date -u"], "linux": ["timedatectl status", "sudo timedatectl set-ntp true"], "desktop_windows": ["wsl --shutdown"]}),
    dict(cause="tls_untrusted", title="the registry's certificate is not trusted (corporate proxy or missing CA certificate)", confidence="high",
         patterns=[r"x509: certificate signed by unknown authority", r"tls: failed to verify", r"x509: .*(unknown authority|not trusted|self[- ]signed)", r"certificate verify failed", r"tls: bad certificate"],
         advice={"any": ["Docker does not trust the certificate the registry presented. On an organisation network this is a proxy that re-signs HTTPS traffic (its CA certificate must be installed where Docker can see it); otherwise a wrong system clock or a missing CA bundle.",
                         "Ask your IT team for the proxy's CA certificate (a .crt file). Do not set `insecure-registries` for ghcr.io: it turns off the check that protects the image.",
                         "Print Docker's proxy settings with the command below; proxies are set in the Docker service, not only in your shell."],
                 "linux": ["Install the CA for the system and restart Docker: copy it to /usr/local/share/ca-certificates/, run `sudo update-ca-certificates`, then `sudo systemctl restart docker`. A proxy for the daemon belongs in a systemd drop-in (docs.docker.com/engine/daemon/proxy/)."],
                 "desktop_windows": ["Install the proxy CA in the Windows certificate store (Docker Desktop uses it), and set the proxy in Docker Desktop > Settings > Resources > Proxies; then restart Docker Desktop."],
                 "desktop_macos": ["Add the CA to the macOS Keychain (System, Always Trust) and set the proxy in Docker Desktop > Settings > Resources > Proxies; restart Docker Desktop."]},
         commands={"any": ["docker info | grep -i -E 'proxy'", "date -u"], "linux": ["sudo update-ca-certificates", "sudo systemctl restart docker"]}),
    dict(cause="proxy_error", title="a proxy between this computer and the registry failed", confidence="high",
         patterns=[r"proxyconnect tcp", r"proxy (error|authentication required)|\b407\b.*proxy", r"bad gateway|\b502\b.*(registry|proxy)|\b503\b.*(registry|proxy)", r"error pulling image configuration.*(proxy)"],
         retry=True,
         advice={"any": ["Docker reached for a proxy and it failed (down, wrong address, or wants a login). Proxies are also a common cause of cut-short layers.",
                         "The command below prints the proxy settings Docker uses. They must be right for the Docker SERVICE (not only your shell), and `NO_PROXY` should hold the registry's hosts if they need no proxy.",
                         "PlasBench retries a pull a few times; if it keeps failing, fix the proxy or try a network without it."],
                 "linux": ["Daemon proxy: a systemd drop-in with HTTP_PROXY / HTTPS_PROXY / NO_PROXY, then `sudo systemctl daemon-reload && sudo systemctl restart docker` (docs.docker.com/engine/daemon/proxy/)."],
                 "desktop_windows": ["Docker Desktop > Settings > Resources > Proxies."], "desktop_macos": ["Docker Desktop > Settings > Resources > Proxies."]},
         commands={"any": ["docker info | grep -i -E 'proxy'", "env | grep -i proxy"], "linux": ["systemctl show --property=Environment docker"]}),
    dict(cause="network", title="the network failed during the pull (DNS, timeout, reset or cut connection)", confidence="high",
         patterns=[r"no such host", r"dial tcp:? .*lookup|lookup .* on .*:53", r"i/o timeout", r"tls handshake timeout", r"connection reset by peer", r"temporary failure in name resolution", r"network is unreachable",
                   r"connection refused", r"could not resolve|name or service not known", r"timeout exceeded|net/http: .*timeout|client\.timeout", r"context deadline exceeded", r"error pulling image configuration",
                   r"read tcp .*(reset|broken pipe|timeout)", r"broken pipe", r"(received )?unexpected EOF|\bEOF\b"],
         retry=True,
         advice={"any": ["The connection to the registry (ghcr.io) broke or never formed: DNS, a flaky or filtered network, a VPN, or a proxy. This is usually temporary; finished layers are kept, so PlasBench retries a few times (PLASBENCH_DOCKER_PULL_RETRIES, default 2) and then stops.",
                         "Building locally needs the internet too (the base image, conda-forge, bioconda), so it is not a way around this: stop, fix the connection, run the same command again (a pull resumes).",
                         "Check: can this computer reach the registry (`curl -sSI https://ghcr.io/v2/`: expect HTTP 401, which means reachable), is a VPN or proxy in the way, does DNS answer. Try `docker pull` again later or from another network, or a mirror/registry cache in your organisation."],
                 "linux": ["If DNS fails only inside Docker: set `\"dns\": [\"1.1.1.1\", \"8.8.8.8\"]` in /etc/docker/daemon.json and `sudo systemctl restart docker`."],
                 "desktop_windows": ["Docker Desktop > Settings > Resources > Network (DNS), and check Windows' own connection; `wsl --shutdown` and restart if the VM lost its network."],
                 "desktop_macos": ["Restart Docker Desktop; check the macOS network and VPN."]},
         commands={"any": ["curl -sSI https://ghcr.io/v2/", "docker info | grep -i -E 'proxy'"], "linux": ["resolvectl status | head -20  # or: cat /etc/resolv.conf"]}),
    dict(cause="build_out_of_memory", title="a build step was killed for lack of memory", confidence="high",
         patterns=[r"exit code: 137", r"signal: killed", r"\bkilled\b.*(oom|memory)|oom.?kill|out of memory", r"cannot allocate memory", r"exit status 137"],
         user=True,
         advice={"any": ["A build step was killed (exit 137): the engine's memory limit was reached. Conda solving needs a few GB at once.",
                         "Give Docker more memory and build again; finished layers are cached, so it resumes."],
                 "desktop_windows": ["Raise memory in C:\\Users\\<you>\\.wslconfig (`[wsl2]` then `memory=8GB`), then `wsl --shutdown` and restart Docker Desktop."],
                 "desktop_macos": ["Docker Desktop > Settings > Resources > Memory: raise it (8 GB or more), Apply & restart."],
                 "linux": ["Check `free -h`; close other programs, add swap, or build on a machine with more memory. `dmesg | grep -i 'out of memory'` confirms the kernel killed it."],
                 "rootless": ["Check `free -h` and the user's memory limits (`systemctl --user show -p MemoryMax docker`)."]},
         commands={"any": ["docker info | grep -i 'total memory'"], "linux": ["free -h", "dmesg | grep -i -E 'out of memory|oom' | tail -20"], "desktop_windows": ["wsl --shutdown"]}),
    dict(cause="buildkit_resources", title="BuildKit ran out of a resource (ResourceExhausted)", confidence="medium",
         patterns=[r"ResourceExhausted", r"resource exhausted", r"too many open files", r"received message larger than max"],
         user=True,
         advice={"any": ["BuildKit reported a resource limit (message size, open files, memory or disk). Free disk space and memory, close other builds, and run the build again: cached layers are reused.",
                         "A very large build context also triggers this: PlasBench builds with the folder's .dockerignore; make sure the folder holds no large data folders."],
                 "linux": ["Check `ulimit -n` and `docker system df`; `docker builder prune` (deletes the build cache) frees space."]},
         commands={"any": ["docker system df"], "linux": ["ulimit -n", "df -h /var/lib/docker"]}),
    dict(cause="build_step_failed", title="a build step failed", confidence="medium",
         patterns=[r"failed to solve", r"did not complete successfully", r"executor failed running", r"\bERROR: failed to build\b"],
         advice={"any": ["A step of the build failed (the lines above name the step and the program's own error). If it is a download error, the network or a conda channel is the cause; run the build again to resume from the cached layers.",
                         "The tail of the build output below is the evidence; PlasBench does not guess beyond it."]}),
]

UNKNOWN = dict(cause="unknown", title="docker stopped with an error PlasBench does not recognise", confidence="low", patterns=[], advice={"any": [
    "PlasBench could not tie this to a known cause, so it will not guess (and it does not build the image locally after an unknown error). The last lines of docker's output are the evidence.",
    "Run `plasbench runtime doctor` for the engine health checks; search the message text with Docker's documentation, or send the output with the doctor report (`plasbench runtime doctor --json`) to whoever supports your Docker."]},
    commands={"any": ["plasbench runtime doctor", "docker info", "docker version"]})


def environment_kind(text="", context=None) -> str:
    """desktop_windows | desktop_macos | desktop | linux | rootless | unknown, from the context (the detected environment, an explicit `environment`) and, failing that, the text itself."""
    context = context or {}
    explicit = context.get("environment")
    if isinstance(explicit, str) and explicit in ENVIRONMENTS:
        return explicit
    env = context.get("env") if isinstance(context.get("env"), dict) else (explicit if isinstance(explicit, dict) else {})
    kind = str(env.get("kind") or context.get("env_kind") or "").lower()
    info = str(context.get("docker_info") or "")
    low = (text or "") + "\n" + info
    lowered = low.lower()
    if context.get("rootless") or "rootless" in lowered or re.search(r"/run/user/\d+/docker", lowered):
        return "rootless"
    desktop = "docker desktop" in lowered or "desktop-containerd" in lowered or "dockerdesktoplinuxengine" in lowered or "docker-desktop" in lowered or bool(env.get("desktop_installed"))
    if kind == "windows" or (kind in ("wsl2", "wsl1") and desktop):
        return "desktop_windows"
    if kind in ("wsl2", "wsl1"):
        return "linux"
    if kind == "macos":
        return "desktop_macos"
    if re.search(r"(?i)wsl|\\\\\.\\pipe\\docker|//\./pipe/docker|\.vhdx", low):
        return "desktop_windows"
    if kind in ("linux", "container"):
        return "desktop" if "desktop-containerd" in lowered else "linux"
    if desktop:
        return "desktop"
    return "unknown"


def _lines(text):
    return [ln.rstrip() for ln in (text or "").replace("\r", "\n").split("\n") if ln.strip()]


def _clip(line):
    line = line.strip()
    return line if len(line) <= LINE_MAX else line[:LINE_MAX - 1] + "..."


def _evidence(rule, text, lines):
    found = []
    rows = text.splitlines()
    for pattern in rule["patterns"]:
        m = re.search(pattern, text, re.I)
        if m:
            at = text.count(chr(10), 0, m.start())
            row = _clip(rows[at] if at < len(rows) else m.group(0))
            if row and row not in found:
                found.append(row)
        if len(found) >= MAX_EVIDENCE:
            break
    return found


def _gather(table, env, image):
    """The environment's block plus the "any" block, in order; for `unknown`, every environment's block with a label."""
    blocks = BLOCKS.get(env, BLOCKS["unknown"])
    labelled = len(blocks) > 1

    def pick(entry):
        out = [s.replace("{image}", image) for s in entry.get("any", [])]
        for block in blocks:
            for item in entry.get(block, []):
                out.append((f"On {LABELS[block]}: " if labelled else "") + item.replace("{image}", image))
        return out
    return pick(table)


def _commands(rule, env, image):
    blocks = BLOCKS.get(env, BLOCKS["unknown"])
    table = rule.get("commands", {})
    out = [c.replace("{image}", image) for c in table.get("any", [])]
    for block in blocks:
        out += [c.replace("{image}", image) for c in table.get(block, [])]
    return list(dict.fromkeys(out))


def _last_resort(rule, env, image):
    blocks = BLOCKS.get(env, BLOCKS["unknown"])
    table = rule.get("last_resort", {})
    items = list(table.get("any", []))
    for block in blocks:
        items += table.get(block, [])
    seen, out = set(), []
    for command, warning in items:
        command = command.replace("{image}", image)
        if command not in seen:
            seen.add(command)
            out.append({"command": command, "warning": warning})
    return out


def diagnose(text, context=None) -> dict:
    """The diagnosis of an error text. `context` (all optional): environment (a kind or the docker_setup.detect_environment() dict), image, docker_info (text of `docker info`), rootless, purpose."""
    context = context or {}
    text = text or ""
    image = str(context.get("image") or "<image>")
    env = environment_kind(text, context)
    hits = [rule for rule in RULES if any(re.search(p, text, re.I) for p in rule["patterns"])]
    if not hits:
        tail = [_clip(ln) for ln in _lines(text)[-TAIL_LINES:]]
        return dict(cause="unknown", title=UNKNOWN["title"], confidence="low", evidence_lines=tail, advice=_gather(UNKNOWN["advice"], env, image), commands=_commands(UNKNOWN, env, image),
                    last_resort=[], retryable=False, engine_unhealthy=False, build_ok=False, user_action=False, environment=env, also=[])
    rule = hits[0]
    return dict(cause=rule["cause"], title=rule["title"], confidence=rule["confidence"], evidence_lines=_evidence(rule, text, _lines(text)) or [_clip(ln) for ln in _lines(text)[-3:]],
                advice=_gather(rule["advice"], env, image), commands=_commands(rule, env, image), last_resort=_last_resort(rule, env, image),
                retryable=bool(rule.get("retry")), engine_unhealthy=bool(rule.get("sick")), build_ok=bool(rule.get("build")), user_action=bool(rule.get("user")),
                environment=env, also=[r["cause"] for r in hits[1:]])


def causes() -> list:
    return [r["cause"] for r in RULES] + ["unknown"]


def render(d) -> str:
    """The diagnosis as text for a terminal or a log."""
    out = [f"Diagnosis: {d['title']} ({d['cause']}, confidence {d['confidence']})"]
    out += ["  evidence: " + ln for ln in d["evidence_lines"]]
    out += [f"  {i}. {s}" for i, s in enumerate(d["advice"], 1)]
    if d["commands"]:
        out.append("  Commands to run yourself (PlasBench does not run these):")
        out += ["    " + c for c in d["commands"]]
    if d.get("last_resort"):
        out.append("  Last resort ONLY, after the steps above, and only if you accept the consequence:")
        for item in d["last_resort"]:
            out += ["    " + item["command"], "      WARNING: " + item["warning"]]
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Say why a docker pull or build failed, from its output.")
    ap.add_argument("logfile", help="A file with docker's output ('-' for standard input).")
    ap.add_argument("--environment", choices=ENVIRONMENTS, default=None)
    ap.add_argument("--image", default=None)
    ap.add_argument("--format", choices=("text", "json"), default="text")
    args = ap.parse_args(argv)
    text = sys.stdin.read() if args.logfile == "-" else open(args.logfile, encoding="utf-8", errors="replace").read()
    ctx = {"environment": args.environment, "image": args.image}
    d = diagnose(text, ctx)
    print(json.dumps(d, indent=2) if args.format == "json" else render(d))
    return 0


if __name__ == "__main__":
    sys.exit(main())
