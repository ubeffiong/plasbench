#!/usr/bin/env python3
"""READ_DEPTH_CAP_X as a setting the person controls: parsing (off, 0, none, false or a number), the `--read-depth-cap` flag, the study's record, `off` behaving exactly like a download
with no cap logic at all, and the three transitions between runs: capped -> off, off -> capped, capped -> higher cap (and the harmless capped -> same or lower cap).

Whole files on disk are never deleted or shrunk; a capped prefix is not valid for a run that wants the whole file or deeper reads, and is fetched again with one plain line saying so.
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "test"))
import depth_cap as dc  # noqa: E402
from ena_range_server import FakeENA  # noqa: E402
from plasbench import cli, studies  # noqa: E402

ok = True
MIB = 1 << 20


def check(label, good, detail=""):
    global ok
    print(f"  {'PASS' if good else 'FAIL'}: {label}{'' if good else ' -> ' + str(detail)}")
    ok &= bool(good)


def fetch(server, run, out, cap, ref):
    env = dict(os.environ, ENA_PORTAL_URL=server.portal(), ENA_CHUNK_MIB="1", ENA_SEGMENT_MIN_BYTES=str(MIB), ENA_CHUNK_BACKOFF_SECONDS="0", ENA_RETRY_DELAY_SECONDS="0",
               DOWNLOAD_TMP_DIR="data", ENA_USE_ARIA2="0", READ_DEPTH_CAP_X=cap)
    return subprocess.run([sys.executable, "-I", str(ROOT / "python" / "fetch_ena_reads.py"), "--run", run, "--out-dir", out, "--reference", ref], env=env, capture_output=True, text=True)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    # parsing and the flag
    check("off, 0, none, false, no and whole all mean whole files; a number is a cap", [studies.parse_depth_cap(x) for x in ("off", "OFF", "0", "none", "False", "no", "whole")] == ["off"] * 7
          and studies.parse_depth_cap("150") == "150" and studies.parse_depth_cap("99.5") == "99.5" and studies.parse_depth_cap("-3") == "off")
    check("the pipeline-side parser agrees (depth_cap.parse_cap)", [dc.parse_cap(x) for x in ("off", "none", "false", "0", "")] == [0, 0, 0, 0, 150.0] and dc.parse_cap("75") == 75)
    try:
        studies.parse_depth_cap("lots")
        good = False
    except ValueError as exc:
        good = "off or a number" in str(exc)
    check("anything else is refused with a plain message", good)
    parser = cli.build_parser()
    check("`plasbench run --read-depth-cap off|N` exists and is described", parser.parse_args(["run", "--cohort", "public-v4", "--read-depth-cap", "off"]).read_depth_cap == "off"
          and "whole files" in " ".join(a.help or "" for a in parser._subparsers._group_actions[0].choices["run"]._actions if "--read-depth-cap" in a.option_strings))
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "study"
        folder.mkdir()
        value, message = studies.resolve_depth_cap(folder, "off")
        record = json.loads((folder / "study.json").read_text())
        check("the choice is recorded in the study's study.json like the data folder", value == "off" and record["read_depth_cap"] == "off" and "recorded for this study" in message, (value, record))
        value, message = studies.resolve_depth_cap(folder, None)
        check("a later run without the flag reuses the study's choice and says how to change it", value == "off" and "--read-depth-cap" in message, (value, message))
        value, _ = studies.resolve_depth_cap(folder, "200")
        check("an explicit flag overrides and updates the record", value == "200" and json.loads((folder / "study.json").read_text())["read_depth_cap"] == "200")
        fresh = Path(tmp) / "fresh"
        fresh.mkdir()
        check("a study with no record and no flag leaves the default alone", studies.resolve_depth_cap(fresh, None) == (None, ""))
    ai = {line.split(chr(9))[0]: line.split(chr(9)) for line in (ROOT / "config" / "ai_settable.tsv").read_text().splitlines() if line and not line.startswith("#")}
    check("the AI assistant may offer it: listed with off and the numbers 50 to 1000", "READ_DEPTH_CAP_X" in ai and "off" in ai["READ_DEPTH_CAP_X"][2].split("|") and "50" in ai["READ_DEPTH_CAP_X"][2].split("|")
          and "1000" in ai["READ_DEPTH_CAP_X"][2].split("|"), ai.get("READ_DEPTH_CAP_X"))
    config = (ROOT / "config" / "config.sh").read_text()
    check("it is a normal config/config.sh setting with a comment", 'export READ_DEPTH_CAP_X="${READ_DEPTH_CAP_X:-150}"' in config and "Read-depth cap" in config)

    # off is exactly today's behaviour: the same requests as a run with nothing to cap
    s = FakeENA()
    s.add_fastq_run("SRRC", pairs=80000)
    s.start()
    plain = FakeENA()
    plain.add_fastq_run("SRRC", pairs=80000)
    plain.meta.clear()                                                    # no read_count/base_count: the cap logic has nothing to work with
    plain.start()
    with tempfile.TemporaryDirectory() as tmp:
        ref = os.path.join(tmp, "reference.fna")
        Path(ref).write_text(">c" + chr(10) + "ACGT" * 2500 + chr(10))
        r1 = fetch(s, "SRRC", os.path.join(tmp, "a"), "off", ref)
        r2 = fetch(plain, "SRRC", os.path.join(tmp, "b"), "", ref)
        req_off = sorted(s.stats()["requests"])
        req_plain = sorted(plain.stats()["requests"])
        check("with the cap off both mates are whole files, MD5-verified", r1.returncode == 0 and "verified (md5" in r1.stderr and sha(os.path.join(tmp, "a", "SRRC_1.fastq.gz")) == sha(os.path.join(tmp, "b", "SRRC_1.fastq.gz"))
              and os.path.getsize(os.path.join(tmp, "a", "SRRC_2.fastq.gz")) == s.files["/f/SRRC_2.fastq.gz"].size, r1.stderr[-400:])
        strip = lambda rows: [(p, a, b, st) for p, a, b, st in rows]  # noqa: E731
        check("off sends exactly the requests of a run that has no cap logic to apply (same ranges, same statuses)", strip(req_off) == strip(req_plain) and r2.returncode == 0, (len(req_off), len(req_plain)))
        prov = json.load(open(os.path.join(tmp, "a", "SRRC.ena_provenance.json")))
        check("the provenance says the cap was off, not applied", prov["read_depth_cap"]["applied"] is False and "off" in prov["read_depth_cap"]["reason"])

    # transitions
    with tempfile.TemporaryDirectory() as tmp:
        ref = os.path.join(tmp, "reference.fna")
        Path(ref).write_text(">c" + chr(10) + "ACGT" * 2500 + chr(10))          # 10 kb: 80000 pairs x 200 = 1600x
        d = os.path.join(tmp, "data")
        r = fetch(s, "SRRC", d, "100", ref)
        check("a capped download first (100x of a 1600x run)", r.returncode == 0 and json.load(open(os.path.join(d, "SRRC.ena_provenance.json")))["read_depth_cap"]["applied"], r.stderr[-300:])
        capped_size = os.path.getsize(os.path.join(d, "SRRC_1.fastq.gz"))
        action, message = dc.decide(d, "SRRC", "off")
        check("capped -> off: the prefix is not valid, and the line says so in one plain sentence", action == "refetch" and message == "SRRC: reads on disk are a 100x prefix; READ_DEPTH_CAP_X is now off, fetching the whole file", (action, message))
        action, message = dc.decide(d, "SRRC", "300")
        check("capped -> a higher cap: not valid either (the deeper read set is wanted)", action == "refetch" and "100x prefix" in message and "300" in message, (action, message))
        check("capped -> the same cap, or a lower one: kept (already deep enough)", dc.decide(d, "SRRC", "100")[0] == "keep" and dc.decide(d, "SRRC", "50")[0] == "keep")
        Path(d, "downloads.sha256").write_text(f"x  SRRC_1.fastq.gz{chr(10)}y  SRRC_2.fastq.gz{chr(10)}z  SRRC.ena_provenance.json{chr(10)}w  reference.fna{chr(10)}")
        dc.discard_capped(d, "SRRC")
        check("discarding removes the capped files, the provenance and their lines of downloads.sha256 (the manifest stays consistent), nothing else",
              not any(os.path.exists(os.path.join(d, f)) for f in ("SRRC_1.fastq.gz", "SRRC_2.fastq.gz", "SRRC.ena_provenance.json")) and Path(d, "downloads.sha256").read_text().strip() == "w  reference.fna")
        s.reset_stats()
        r = fetch(s, "SRRC", d, "off", ref)
        whole = os.path.getsize(os.path.join(d, "SRRC_1.fastq.gz"))
        check("then the whole file is fetched and MD5-verified", r.returncode == 0 and whole == s.files["/f/SRRC_1.fastq.gz"].size and whole > 3 * capped_size and "verified (md5" in r.stderr, (capped_size, whole))
        # off -> capped
        before = {f: sha(os.path.join(d, f)) for f in ("SRRC_1.fastq.gz", "SRRC_2.fastq.gz")}
        action, message = dc.decide(d, "SRRC", "150")
        check("off -> capped: whole files are kept (never deleted or shrunk), and the line says the cap is not applied and the full reads are used", action == "keep" and "whole files" in message and "not applied" in message
              and "full reads" in message, (action, message))
        dc.note_kept(d, "SRRC", "150")
        after = {f: sha(os.path.join(d, f)) for f in ("SRRC_1.fastq.gz", "SRRC_2.fastq.gz")}
        note = json.load(open(os.path.join(d, "SRRC.ena_provenance.json")))["read_depth_cap"].get("note", "")
        check("the files are byte-for-byte unchanged, and the provenance (so the manifest and the report) records the decision", before == after and "kept as they are" in note and "full reads" in note, note)
        check("no provenance at all (SRA Toolkit reads, your own files): kept", dc.decide(os.path.join(tmp, "nowhere"), "SRRX", "off") == ("keep", ""))
    s.stop()
    plain.stop()
    print("ALL READ DEPTH CAP STATE TESTS PASSED" if ok else "SOME READ DEPTH CAP STATE TESTS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
