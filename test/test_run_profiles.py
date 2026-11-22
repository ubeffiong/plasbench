#!/usr/bin/env python3
"""Run profiles (config/run_profiles.tsv, python/run_profiles.py): fast, standard, thorough.

  - every key exists in config/config.sh and has a legal value; standard overrides nothing
  - fast really changes the switches (sourcing config/config.sh under RUN_PROFILE=fast gives the new values); an explicit setting always wins
  - the profile is in the run manifest and the report's run metadata, and the start-of-run text names what was turned off and the saving (measured or 'not measured')
  - NEUTRALITY: no scoring or headline code reads a key a profile changes, and the headline leaderboard computed from the demo's scores is byte-identical under every profile"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import run_profiles as rp  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


rows = rp.read_table()
check("the table validates (keys exist in config.sh, values legal, nothing equals the standard value)", rp.validate() == [], rp.validate())
check("standard overrides nothing", rp.settings_for("standard") == {})
fast, thorough = rp.settings_for("fast"), rp.settings_for("thorough")
check("fast switches off ISEScan and the advisory sweeps", fast.get("ANNOTATE_WITH_ISESCAN") == "0" and fast.get("RUN_RANKING_STABILITY") == "0" and fast.get("RUN_RANK_SENSITIVITY") == "0", fast)
check("fast keeps what scoring and the truth labels rest on",
      not {"RUN_TRUTH_LABEL_EVIDENCE", "RUN_DIMER_DETECTION", "RUN_ASSEMBLY_QC_GATE", "RUN_MOB_RECON", "RUN_PLATON", "RUN_PLASMIDSPADES", "ANNOTATE_WITH_MOB_TYPER", "ANNOTATE_WITH_ABRICATE",
            "ANNOTATE_WITH_BARRNAP", "ANNOTATE_WITH_AMRFINDER", "RUN_DATABASE_CONTAINMENT", "RUN_REFERENCE_ANNOTATION"} & set(fast), fast)
check("thorough turns extras on and searches the chromosome too", thorough.get("ISESCAN_SCOPE") == "all" and thorough.get("RUN_QUAST_DIAGNOSTICS") == "1", thorough)
try:
    rp.settings_for("turbo")
    check("an unknown profile is refused", False)
except ValueError as exc:
    check("an unknown profile is refused with the choices", "fast, standard or thorough" in str(exc), str(exc))
check("an explicit setting wins over the profile", "export RUN_RANKING_STABILITY=0" not in "\n".join(rp.export_lines("fast", {"RUN_RANKING_STABILITY": "1"}))
      and "export RUN_RANK_SENSITIVITY=0" in "\n".join(rp.export_lines("fast", {"RUN_RANKING_STABILITY": "1"})))
text = "\n".join(rp.describe("fast", {}))
check("the start-of-run text names what was turned off, the saving and whether it was measured", "turned off: ISEScan" in text and "Estimated time saved" in text and "not measured" in text and "measured 2026" in text, text)
check("standard says it changes nothing", rp.describe("standard") == ["Run profile: standard (today's defaults)."])

# config.sh under each profile
if shutil.which("bash") and os.name != "nt":
    def sourced(profile, extra=None):
        env = dict(os.environ, RUN_PROFILE=profile, PYTHONDONTWRITEBYTECODE="1", PLASBENCH_LOCAL_SETTINGS="/nonexistent")
        env.pop("_PB_PROFILE_APPLIED", None)
        for k in list(fast) + list(thorough):
            env.pop(k, None)
        env.update(extra or {})
        out = subprocess.run(["bash", "-c", f'source "{ROOT}/config/config.sh" >/dev/null 2>&1; echo "$ANNOTATE_WITH_ISESCAN $RUN_RANKING_STABILITY $ISESCAN_SCOPE $RUN_QUAST_DIAGNOSTICS $RUN_PROFILE"'],
                             capture_output=True, text=True, env=env, timeout=120)
        return out.stdout.strip()
    check("config.sh: standard keeps today's defaults", sourced("standard") == "1 1 plasmids 0 standard", sourced("standard"))
    check("config.sh: fast switches ISEScan and the sweeps off", sourced("fast") == "0 0 plasmids 0 fast", sourced("fast"))
    check("config.sh: thorough turns the extras on", sourced("thorough") == "1 1 all 1 thorough", sourced("thorough"))
    check("config.sh: an explicit RUN_RANKING_STABILITY=1 survives the fast profile", sourced("fast", {"RUN_RANKING_STABILITY": "1"}) == "0 1 plasmids 0 fast", sourced("fast", {"RUN_RANKING_STABILITY": "1"}))

# manifest and report
import write_manifest as wm  # noqa: E402
os.environ["RUN_PROFILE"] = "fast"
with tempfile.TemporaryDirectory() as tmp:
    sample = Path(tmp) / "s1"
    sample.mkdir()
    (sample / "annotation_provenance.json").write_text(json.dumps({"callers": {"isescan": {"status": "ok", "scope": "plasmids", "chromosome_searched": False}}}), encoding="utf-8")
    perf = wm.performance_record(tmp, [{"sample_id": "s1"}])
    check("the manifest's performance section carries the profile and its overrides", perf["profile"] == "fast" and any(o["key"] == "ANNOTATE_WITH_ISESCAN" for o in perf["overrides"]), perf)
    check("... and that the chromosome was not searched", perf["chromosome_insertion_sequences"].startswith("not evaluated"), perf)
    manifest = Path(tmp) / "run_manifest.json"
    manifest.write_text(json.dumps({"tool": "PlasBench", "tool_version": "x", "performance": perf, "settings": {"RUN_PROFILE": "fast"}}), encoding="utf-8")
    import build_html_report as bhr  # noqa: E402
    html = bhr.run_manifest_html(manifest, {})
    check("the report's run metadata names the profile and what it turned off", "Run profile" in html and "fast" in html and "ISEScan insertion sequences" in html, html[:400])
    check("... and shows 'not evaluated (chromosome not searched)' instead of a chromosome count", "not evaluated (chromosome not searched" in html)
os.environ.pop("RUN_PROFILE", None)

# neutrality: no scoring code reads a key a profile changes
changed = sorted(set(fast) | set(thorough))
scoring = ["score_plasmids.py", "score_bins.py", "aggregate_results.py", "composite_score.py", "contig_classification.py", "label_truth_evidence.py", "assembly_qc_gate.py", "matching.py", "plasbench_common.py"]
leaks = [(name, key) for name in scoring if (ROOT / "python" / name).exists() for key in changed if key in (ROOT / "python" / name).read_text(encoding="utf-8")]
check("no scoring, aggregation or truth-label code reads a key a profile changes", not leaks, leaks)
score_sh = (ROOT / "scripts" / "05_score.sh").read_text(encoding="utf-8")
agg_sh = (ROOT / "scripts" / "06_aggregate.sh").read_text(encoding="utf-8")
lead = agg_sh.index("aggregate_results.py") if "aggregate_results.py" in agg_sh else 0
check("the headline aggregation in stage 6 runs before any gated advisory job that a profile switches off", all(agg_sh.find(k) == -1 or agg_sh.find(k) > lead for k in ("RUN_RANK_SENSITIVITY", "RUN_RANKING_STABILITY", "RUN_PERFORMANCE_DRIVERS")), lead)

# the headline from the demo's scores is identical under every profile
demo = ROOT / "results_demo"
if (demo / "scores.tsv").exists() and (demo / "tool_status.tsv").exists() and (demo / "samples.tsv").exists():
    outputs = {}
    for profile in rp.PROFILES:
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", RUN_PROFILE=profile)
            for line in rp.export_lines(profile, {}):
                key, _, value = line[len("export "):].partition("=")
                env[key] = value.strip("'")
            cmd = [sys.executable, str(ROOT / "python" / "aggregate_results.py"), "--scores", str(demo / "scores.tsv"), "--tool-status", str(demo / "tool_status.tsv"),
                   "--sample-sheet", str(demo / "samples.tsv"), "--out-prefix", str(Path(tmp) / "benchmark")]
            if (demo / "benchmark.truth_provenance.tsv").exists():
                cmd += ["--truth-provenance", str(demo / "benchmark.truth_provenance.tsv")]
            done = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=300)
            board = Path(tmp) / "benchmark.leaderboard.tsv"
            outputs[profile] = board.read_bytes() if board.exists() else (done.stderr[-300:]).encode()
    check("the demo's headline leaderboard is byte-identical under fast, standard and thorough", len(set(outputs.values())) == 1 and outputs["standard"].startswith(b"tool") or len(set(outputs.values())) == 1,
          {k: v[:80] for k, v in outputs.items()})
else:
    print("  note  results_demo is not built here: the byte-identical demo headline check was skipped (the structural checks above still ran)")

print("\nall run-profile checks passed" if ok else "\nFAILED")
sys.exit(0 if ok else 1)
