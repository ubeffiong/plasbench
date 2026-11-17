#!/usr/bin/env python3
"""Is this run made of synthetic (demo) data, real data, or a mix? A mix is refused, and a synthetic run says so inside its report.

The bundled demo (test/demo_dataset.py) fabricates sequences and scores. Its sample sheet marks every sample `sample_origin = synthetic`. Two rules follow:

  * A run that contains synthetic samples AND real ones is refused (aggregate_results.py and build_html_report.py): the ranking, the intervals and the report
    would blend invented numbers with measured ones, and nothing on the page would say which was which.
  * A run made only of synthetic samples is allowed, and its report carries a banner at the top: demonstration data, not a result.

Real means everything else, including a sample with no row in the sample sheet (an unknown is never assumed synthetic). Samples whose reads were simulated from a
real assembly (truth_source = simulated) are a supported, separately badged kind and are not treated as synthetic here.
"""
import csv

SYNTHETIC_ORIGINS = {"synthetic", "demo", "demonstration"}
SYNTHETIC_TRUTH_SOURCES = {"demo_synthetic"}

BANNER = ("<div class='insight caution demo-banner' id='demo-banner' role='note'><p><strong>Demonstration data.</strong> Every sample in this report is "
          "synthetic: the sequences, the tool outputs and the scores were fabricated to show how the engine works. Nothing here is a biological result, "
          "a tool comparison or evidence about any tool. Run PlasBench on a real cohort to obtain one.</p></div>")


def read_sheet(path):
    """sample id -> row for a sample sheet or cohort file (comment lines starting with # are skipped); {} when absent or unreadable."""
    if not path:
        return {}
    try:
        with open(path, newline="", encoding="utf-8") as handle:
            lines = [line for line in handle if not line.startswith("#")]
    except OSError:
        return {}
    rows = {}
    for row in csv.DictReader(lines, delimiter="\t"):
        key = row.get("sample_id") or row.get("sample")
        if key:
            rows[key] = row
    return rows


def is_synthetic(row):
    """True when the sample sheet row marks the sample as synthetic."""
    if not row:
        return False
    return ((row.get("sample_origin") or "").strip().lower() in SYNTHETIC_ORIGINS
            or (row.get("truth_source") or "").strip().lower() in SYNTHETIC_TRUTH_SOURCES)


def classify(samples, sheet):
    """(synthetic samples, real samples), each sorted, for the sample ids actually scored."""
    synthetic = sorted(s for s in samples if is_synthetic(sheet.get(s)))
    real = sorted(s for s in samples if not is_synthetic(sheet.get(s)))
    return synthetic, real


def refuse_mixed(samples, sheet, allow=False):
    """Raise SystemExit when synthetic and real samples are in one run; return (synthetic, real) otherwise."""
    synthetic, real = classify(samples, sheet)
    if synthetic and real and not allow:
        raise SystemExit(
            "ERROR: this run mixes synthetic (demo) samples with real ones, so its ranking and report would blend invented numbers with measured ones.\n"
            f"  synthetic: {', '.join(synthetic[:6])}{' ...' if len(synthetic) > 6 else ''}\n"
            f"  real: {', '.join(real[:6])}{' ...' if len(real) > 6 else ''}\n"
            "Score the demo and the real cohort in separate results folders. ALLOW_SYNTHETIC_WITH_REAL=1 overrides this for a test of the engine only.")
    return synthetic, real


def all_synthetic(samples, sheet):
    synthetic, real = classify(samples, sheet)
    return bool(synthetic) and not real
