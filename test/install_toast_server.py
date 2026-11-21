#!/usr/bin/env python3
"""A real `plasbench ui` server whose installs are fake (for test_install_toast_browser.py only): `install-tools NAME` starts a tiny command that prints a step line every half second
until a control file <IT_FAKE_DIR>/NAME.ctl says how to end ("done": exit 0 after printing a version, "fail": exit 1 with an error line, "wait": exit 20, the Docker handoff).
Everything else (the job list, the labels, the polling, the page) is the real code; only the command run by the detached runner is replaced, and the internet gate is bypassed.
Usage: python install_toast_server.py <ui args...>
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from plasbench import cli, netgate, webui  # noqa: E402

FAKE = r'''
import os, sys, time
ctl = sys.argv[1]
n = 0
while True:
    mode = open(ctl).read().strip() if os.path.exists(ctl) else ""
    if mode == "done":
        print("Docker version 27.0.1, build fake"); sys.exit(0)
    if mode == "fail":
        print("ERROR: fake install could not finish"); sys.exit(1)
    if mode == "wait":
        print("Steps: open Docker Desktop and finish the setup"); sys.exit(20)
    n += 1
    print("Step %d: downloading fake package" % n, flush=True)
    time.sleep(0.5)
'''
_orig = webui.Jobs.start


def start(self, argv, label="", env=None):
    if argv and argv[0] == "install-tools" and len(argv) > 1 and argv[1] not in ("plan", "list", "validate", "locked"):
        ctl = Path(os.environ["IT_FAKE_DIR"]) / (argv[1].split(",")[0] + ".ctl")
        shown = "plasbench " + " ".join(argv)
        job = self._launch([sys.executable, "-u", "-c", FAKE, str(ctl)], shown, label, None, list(argv), "plasbench", self.project.root)
        return dict(job, **self.install_fields(job))
    return _orig(self, argv, label, env)


webui.Jobs.start = start
netgate.require_job = lambda *a, **k: None
sys.argv = ["plasbench", "--project-root", str(ROOT)] + sys.argv[1:]
cli.main()
