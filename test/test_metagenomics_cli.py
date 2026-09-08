#!/usr/bin/env python3
"""The public CLI must route meta mode away from isolate scripts."""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        manifest = temp / "meta.tsv"
        manifest.write_text("community_id\tsample_id\tinformation_regime\ttruth_status\ncommunity\tsample\tsingle_sample\tunavailable\n", encoding="utf-8")
        predictions = temp / "predictions"; predictions.mkdir()
        result = subprocess.run([sys.executable, "-c", "from plasbench.cli import main; main()", "--project-root", str(ROOT), "run", "--mode", "metagenomics", "--samples", str(manifest), "--predictions-dir", str(predictions), "--results-dir", str(temp / "results"), "--no-report-prompt"], cwd=ROOT, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert (temp / "results" / "metagenomics.report.html").is_file()
        assert not (temp / "results" / "benchmark.report.html").exists()
        generated = temp / "meta_run.sh"
        scripted = subprocess.run([sys.executable, "-c", "from plasbench.cli import main; main()", "--project-root", str(ROOT), "run", "-m", "metagenomics", "--samples", str(manifest), "--predictions-dir", str(predictions), "--results-dir", str(temp / "not_run"), "--write-script", str(generated)], cwd=ROOT, capture_output=True, text=True)
        assert scripted.returncode == 0, scripted.stderr
        assert generated.is_file() and "metagenomics.py score" in generated.read_text(encoding="utf-8")
        assert not (temp / "not_run").exists(), "--write-script must not run metagenomic scoring"
        for alias in ("meta", "beta"):
            aliased = subprocess.run([sys.executable, "-c", "from plasbench.cli import main; main()", "--project-root", str(ROOT), alias, "validate", "-s", str(manifest)], cwd=ROOT, capture_output=True, text=True)
            assert aliased.returncode == 0 and "VALID" in aliased.stdout, (alias, aliased.stderr)
        short_run = subprocess.run([sys.executable, "-c", "from plasbench.cli import main; main()", "--project-root", str(ROOT), "run", "-m", "meta", "-s", str(manifest), "-p", str(predictions), "-o", str(temp / "short_results"), "--no-report-prompt"], cwd=ROOT, capture_output=True, text=True)
        assert short_run.returncode == 0, short_run.stderr
        assert (temp / "short_results" / "metagenomics.report.html").is_file()
    print("METAGENOMICS CLI ROUTING TEST PASSED")


if __name__ == "__main__": main()
