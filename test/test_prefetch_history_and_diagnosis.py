#!/usr/bin/env python3
"""The SRA Toolkit failure history kept across runs (python/prefetch_history.py) and the plain-words diagnosis of its failures (python/download_diagnosis.py).

History: persisted as JSON under the state folder; counts only entries under 24 hours old and written by the same PlasBench / sra-tools version; PREFETCH_FAIL_LIMIT decides when prefetch
is known-broken and 0 turns that off; a damaged file means no history. Diagnosis: the TLS message from a real run (21 Nov 2026) is explained in words with what to check, without promising a cure;
other recognisable failures too; text that matches nothing gives nothing.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import download_diagnosis as dd  # noqa: E402
import prefetch_history as ph  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(f"  {'PASS' if good else 'FAIL'}: {label}{'' if good else ' -> ' + str(detail)}")
    ok &= bool(good)


TLS = "2026-11-21T17:46:40 sys: connection failed while opening file within cryptographic module - Failed to create TLS stream for 'www.ncbi.nlm.nih.gov'"


def main():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["PLASBENCH_STATE_DIR"] = tmp
        V1, V2 = "0.5.6|3.0.0", "0.5.7|3.0.0"
        now = 1_000_000.0
        check("no file means no history and prefetch is not disabled", ph.load(V1, now) == [] and ph.disabled(2, V1, now) == (False, ""))
        ph.record(False, "tls", V1, now)
        check("one failure does not disable prefetch (limit 2)", not ph.disabled(2, V1, now + 1)[0])
        ph.record(False, "Failed to create TLS stream", V1, now + 60)
        off, why = ph.disabled(2, V1, now + 120)
        check("two failures in a row disable it, and the reason says why", off and "Failed to create TLS stream" in why and "2 tries" in why, why)
        check("the history is a JSON file in the state folder (~/.plasbench) with version and entries", json.load(open(os.path.join(tmp, "prefetch_history.json")))["version"] == V1)
        check("PREFETCH_FAIL_LIMIT=0 never disables", not ph.disabled(0, V1, now + 120)[0])
        check("entries expire after 24 hours", not ph.disabled(2, V1, now + 60 + 24 * 3600 + 1)[0] and ph.load(V1, now + 60 + 24 * 3600 + 1) == [])
        check("a history written by another PlasBench/sra-tools version is ignored", ph.load(V2, now + 120) == [] and not ph.disabled(2, V2, now + 120)[0])
        ph.record(True, "", V1, now + 200)
        check("a success breaks the run of failures", not ph.disabled(2, V1, now + 210)[0])
        for i in range(30):
            ph.record(False, "x", V1, now + 300 + i)
        check("the file is kept small (at most 20 entries)", len(json.load(open(os.path.join(tmp, "prefetch_history.json")))["entries"]) <= 20)
        Path(tmp, "prefetch_history.json").write_text("{ not json")
        check("a damaged file means no history, never an error", ph.load(V1, now) == [] and not ph.disabled(2, V1, now)[0])
        env = dict(os.environ, PLASBENCH_STATE_DIR=tmp, PLASBENCH_FORCE_VERSION="T|1")
        cli = [sys.executable, "-I", str(ROOT / "python" / "prefetch_history.py")]
        os.remove(os.path.join(tmp, "prefetch_history.json"))
        subprocess.run(cli + ["record", "fail", "--reason", "a"], env=env)
        subprocess.run(cli + ["record", "fail", "--reason", "b"], env=env)
        r = subprocess.run(cli + ["disabled", "--limit", "2"], env=env, capture_output=True, text=True)
        r0 = subprocess.run(cli + ["disabled", "--limit", "0"], env=env, capture_output=True, text=True)
        check("the command line: `disabled` exits 0 with the reason when prefetch is known-broken, 1 otherwise", r.returncode == 0 and "b" in r.stdout and r0.returncode == 1, (r.returncode, r.stdout, r0.returncode))

    found = dd.diagnose("[prefetch] " + TLS)
    check("the TLS error of the real run is recognised", found and found["cause"] == "sra_tls_stream", found)
    text = dd.render(found)
    check("it says what the error means: the toolkit could not open a TLS connection to NCBI", "could not open a TLS" in text and "www.ncbi.nlm.nih.gov" in text, text)
    check("it says what is used instead (ENA, checksum-verified)", "ENA" in text and "checksum" in text, text)
    check("it says what to check: proxy, system CA certificates, vdb-config", "proxy" in text and "CA certificates" in text and "vdb-config" in text, text)
    check("it does not promise a cure", "not guaranteed" in text and "will fix" not in text.lower() and "this fixes" not in text.lower(), text)
    check("the evidence line is the matching log line", "Failed to create TLS stream" in found["evidence"])
    check("a certificate failure, a name lookup failure and a full disk are told apart",
          dd.diagnose("certificate verify failed")["cause"] == "sra_certificate" and dd.diagnose("Name or service not known")["cause"] == "sra_name_resolution"
          and dd.diagnose("No space left on device")["cause"] == "sra_disk_full")
    check("text that matches nothing gives no diagnosis (never a guess)", dd.diagnose("err: something unrelated happened") is None and dd.diagnose("") is None)
    with tempfile.TemporaryDirectory() as tmp:
        log = os.path.join(tmp, "x.prefetch.log")
        Path(log).write_text(TLS + "\n")
        r = subprocess.run([sys.executable, "-I", str(ROOT / "python" / "download_diagnosis.py"), log], capture_output=True, text=True)
        r2 = subprocess.run([sys.executable, "-I", str(ROOT / "python" / "download_diagnosis.py"), os.path.join(tmp, "missing")], capture_output=True, text=True)
        check("the command prints the explanation for a log file, and nothing (exit 1) for an unknown or missing one", r.returncode == 0 and "TLS" in r.stdout and r2.returncode == 1 and r2.stdout == "")
    print("ALL PREFETCH HISTORY AND DIAGNOSIS TESTS PASSED" if ok else "SOME PREFETCH HISTORY AND DIAGNOSIS TESTS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
