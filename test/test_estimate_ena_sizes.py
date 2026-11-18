#!/usr/bin/env python3
"""The pre-download estimate asks ENA for each run's exact size when the cohort has no base counts (a first-N copy, your own isolates).

Before, a 20-isolate sheet without a lock printed 'size unknown' for every read set, so a single 9.5 GB run could hide inside a quick test. ENA's file report gives
each file's exact compressed bytes. The lookup is faked here; nothing touches the network.
"""
import contextlib
import io
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import estimate_download as ed  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


SIZES = {"SRR1": (3_000_000_000, 3_100_000_000), "SRR2": ("2000000", "2100000"), "SRRBIG": (4_700_000_000, 4_800_000_000)}


def fake_report(run, timeout=15):
    if run == "SRRDOWN":
        raise OSError("connection refused")
    if run == "SRRNONE":
        return {"fastq_bytes": ""}
    a, b = SIZES[run]
    return {"fastq_bytes": f"{a};{b}"}


# --- the lookup -------------------------------------------------------------------------------------------------------------------------
found, missing = ed.ena_sizes({"a": "SRR1", "b": "SRR2", "c": "SRRDOWN", "d": "SRRNONE"}, report=fake_report)
check("each run's total is the sum of its files' bytes", found.get("a") == 6_100_000_000 and found.get("b") == 4_100_000, found)
check("a run ENA cannot answer, or answers without sizes, is reported missing (never counted as 0)", missing == ["c", "d"] and "c" not in found and "d" not in found, (found, missing))

# --- through the command: no lock, so the sizes come from ENA ------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    sheet = tmp / "quick.tsv"
    sheet.write_text("sample_id\tassembly_accession\tsra_run\nsmall\tGCF_1.1\tSRR2\nbig\tGCF_2.1\tSRRBIG\nodd\tGCF_3.1\tSRRDOWN\n")
    (tmp / "data").mkdir()
    real = ed.ena_sizes
    ed.ena_sizes = lambda runs, **kw: real(runs, report=fake_report)
    argv = sys.argv
    sys.argv = ["estimate_download.py", "--samples", str(sheet), "--data-dir", str(tmp / "data")]
    os.environ.pop("ENA_SIZE_LOOKUP", None)
    os.environ["READ_SOURCE"] = "auto"
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        status = ed.main()
    sys.argv = argv
    ed.ena_sizes = real
    text = out.getvalue()
    check("the command succeeds", status == 0, text)
    check("the read sets show a total, not 'size unknown'", "size unknown" not in text and "ESTIMATED TOTAL" in text, text)
    check("it says the sizes are exact ENA sizes", "exact sizes from ENA" in text, text)
    check("it names the largest read set and its size", "LARGEST READ SET" in text and "SRRBIG" in text and "9.5 GB" in text, text)
    check("a read set above 5 GB is flagged as very large, with the way to skip such isolates", "very large" in text and "MAX_RUN_DOWNLOAD_GB" in text, text)
    check("the run ENA could not answer is listed as not included in the total", "no size for 1 sample(s) (odd)" in text and "NOT included" in text, text)

# --- when the lookup is switched off or not applicable ---------------------------------------------------------------------------------------
os.environ["ENA_SIZE_LOOKUP"] = "0"
check("ENA_SIZE_LOOKUP=0 turns the lookup off", ed.lookup_enabled() is False)
os.environ["ENA_SIZE_LOOKUP"] = "1"
os.environ["READ_SOURCE"] = "sra"
check("READ_SOURCE=sra never uses ENA, so it does no ENA lookup either", ed.lookup_enabled() is False)
os.environ["READ_SOURCE"] = "ena"
check("READ_SOURCE=ena looks sizes up", ed.lookup_enabled() is True)

print("ALL ESTIMATE ENA SIZE TESTS PASSED" if ok else "ESTIMATE ENA SIZE TESTS FAILED")
sys.exit(0 if ok else 1)
