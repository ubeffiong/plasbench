#!/usr/bin/env python3
"""Checks for how a run's recorded tool versions reach the report.

Versions come from two places. The executable map covers the adapters that ship
here, whose report label differs from the command they invoke. A run may also
record ``method_versions`` keyed by report label, which is the only route for a
method outside that fixed list -- a new adapter, or the synthetic demo methods.
Without the second route every such method reads "not recorded" forever.
"""

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "python"))

from build_html_report import read_tool_versions  # noqa: E402


def write(path, payload):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    return path


def main():
    with tempfile.TemporaryDirectory(prefix="tool_versions_") as tmp:
        # A missing or unreadable manifest is not an error; nothing is claimed.
        assert read_tool_versions(os.path.join(tmp, "absent.json")) == {}
        broken = os.path.join(tmp, "broken.json")
        open(broken, "w", encoding="utf-8").write("{not json")
        assert read_tool_versions(broken) == {}

        # Route one: an installed executable, mapped to its report label.
        path = write(os.path.join(tmp, "exe.json"), {
            "tools": {"mob_recon": {"available": True, "version": "3.1.0"},
                      "platon": {"available": False}}})
        versions = read_tool_versions(path)
        assert versions["mob_recon"] == "3.1.0"
        assert "platon" not in versions, "an unavailable executable must claim no version"

        # An available executable that would not report its version.
        path = write(os.path.join(tmp, "unreported.json"), {
            "tools": {"gplas": {"available": True}}})
        assert read_tool_versions(path)["gplas"] == "unreported"

        # Route two: methods outside the fixed executable list.
        path = write(os.path.join(tmp, "declared.json"), {
            "method_versions": {"mob_like": "0.0-synthetic", "custom_adapter": "2.4"}})
        versions = read_tool_versions(path)
        assert versions == {"mob_like": "0.0-synthetic", "custom_adapter": "2.4"}, \
            "methods outside the executable map must still be able to report a version"

        # Declared versions win: they name the method that actually ran, while
        # the executable probe only says what was installed.
        path = write(os.path.join(tmp, "both.json"), {
            "tools": {"mob_recon": {"available": True, "version": "3.1.0"}},
            "method_versions": {"mob_recon": "3.1.0-patched"}})
        assert read_tool_versions(path)["mob_recon"] == "3.1.0-patched", \
            "a declared method version must take precedence over the executable probe"

        # A malformed or empty block must not crash or invent entries.
        for bad in ({"method_versions": None}, {"method_versions": []},
                    {"method_versions": {"x": ""}}):
            assert read_tool_versions(write(os.path.join(tmp, "bad.json"), bad)) == {}

    # The demo must produce a manifest that actually resolves its methods, and
    # must record the real checkout version rather than a fabricated one.
    with tempfile.TemporaryDirectory(prefix="demo_manifest_") as tmp:
        subprocess.run([sys.executable, os.path.join(HERE, "demo_dataset.py"),
                        "--out-dir", tmp], check=True, capture_output=True)
        manifest = os.path.join(tmp, "run_manifest.json")
        assert os.path.isfile(manifest), "the demo did not write a run manifest"
        body = json.load(open(manifest, encoding="utf-8"))
        assert body["synthetic"] is True, "the demo manifest must declare itself synthetic"

        init = os.path.join(ROOT, "plasbench", "__init__.py")
        expected = None
        for line in open(init, encoding="utf-8"):
            if line.startswith("__version__"):
                expected = line.split("=", 1)[1].strip().strip("\"'")
        assert body["tool_version"] == expected, (
            "the demo must record the checkout version that produced it, not a "
            f"placeholder: {body['tool_version']!r} != {expected!r}")

        resolved = read_tool_versions(manifest)
        for tool in ("mob_like", "platon_like", "spades_like", "gplas_like", "weak_like"):
            assert resolved.get(tool), f"demo method has no resolvable version: {tool}"

    print("ALL TOOL VERSION TESTS PASSED")


if __name__ == "__main__":
    main()
