#!/usr/bin/env python3
"""annotate_reference.py keeps finished annotations in a shared cache keyed by the reference's checksum and the callers' versions: a second study of the same isolate
reuses them, the reused table is byte-identical to a fresh one, any change to the reference or a tool version invalidates it, and a failed caller is never cached."""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))
import annotate_reference as ar  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


REAL_FINGERPRINT = ar.caller_fingerprint
CALLS = []
STATE = {"fail": False, "versions": {"abricate": "1.0.1"}}


def fake(name):
    def call(*args, **kwargs):
        CALLS.append(name)
        if STATE["fail"] and name == "isescan":
            return [], {"status": "failed", "reason": "boom"}
        feature = {"sequence_id": "p1", "start": 0, "end": 5, "feature_type": "amr" if name == "amrfinder" else "replicon", "label": name, "source": name, "version": "1"}
        return ([feature] if name in ("amrfinder", "mob_typer") else []), {"status": "ok", "features": 1}
    return call


def run(tmp, ref, out_name, cache=True):
    del CALLS[:]
    argv = ["annotate_reference.py", "--reference", str(ref), "--out", str(tmp / out_name), "--provenance", str(tmp / (out_name + ".json")), "--threads", "4"]
    if cache:
        argv += ["--cache-dir", str(tmp / "cache")]
    sys.argv = argv
    ar.main()
    return (tmp / out_name).read_bytes(), json.loads((tmp / (out_name + ".json")).read_text(encoding="utf-8"))


def main():
    tmp = Path(tempfile.mkdtemp())
    ref = tmp / "reference.fna"
    ref.write_text(">chr\nACGTACGTACGT\n>p1\nACGTAC\n", encoding="utf-8")
    for name in ("call_mob_typer", "call_abricate", "call_amrfinder", "call_isescan", "call_isfinder", "call_barrnap"):
        setattr(ar, name, fake(name.replace("call_", "")))
    ar.caller_fingerprint = lambda *a: dict(STATE["versions"], amr_database="ncbi")

    fresh, _ = run(tmp, ref, "nocache.tsv", cache=False)
    n_fresh = len(CALLS)
    check("without a cache every caller runs", n_fresh >= 6, CALLS)
    first, rec1 = run(tmp, ref, "first.tsv")
    check("first run with a cache: a miss, every caller runs, the result is stored", len(CALLS) == n_fresh and rec1["annotation_cache"]["hit"] is False and rec1["annotation_cache"]["stored"] is True, rec1.get("annotation_cache"))
    check("the table is byte-identical to one computed without a cache", first == fresh)
    second, rec2 = run(tmp, ref, "second.tsv")
    check("second run (same reference, same versions): a hit, NO caller runs", CALLS == [] and rec2["annotation_cache"]["hit"] is True, (CALLS, rec2.get("annotation_cache")))
    check("the reused table is byte-identical to the fresh one", second == fresh)
    check("provenance of a hit says it was reused, with the key and the tool fingerprint", rec2["annotation_cache"]["key"] == rec1["annotation_cache"]["key"] and rec2["annotation_cache"]["fingerprint"]["abricate"] == "1.0.1", rec2["annotation_cache"])
    check("the callers' statuses are carried over in the provenance", sorted(rec2["callers"]) == sorted(rec1["callers"]), rec2.get("callers"))

    # a copy of the same reference in another study folder (same bytes) reuses it
    other = tmp / "study2"
    other.mkdir()
    ref2 = other / "reference.fna"
    ref2.write_bytes(ref.read_bytes())
    del CALLS[:]
    sys.argv = ["annotate_reference.py", "--reference", str(ref2), "--out", str(other / "t.tsv"), "--cache-dir", str(tmp / "cache")]
    ar.main()
    check("the same reference bytes in another folder (another study) hit the same entry", CALLS == [] and (other / "t.tsv").read_bytes() == fresh, CALLS)

    # invalidation
    STATE["versions"] = {"abricate": "1.0.2"}
    _, rec4 = run(tmp, ref, "v2.tsv")
    check("a changed tool version is a miss (and a new entry)", rec4["annotation_cache"]["hit"] is False and rec4["annotation_cache"]["key"] != rec1["annotation_cache"]["key"] and CALLS, rec4.get("annotation_cache"))
    ref.write_text(">chr\nACGTACGTACGA\n>p1\nACGTAC\n", encoding="utf-8")
    _, rec5 = run(tmp, ref, "ref2.tsv")
    check("a changed reference is a miss", rec5["annotation_cache"]["hit"] is False and CALLS)

    # failures are not cached
    STATE["versions"] = {"abricate": "9.9"}
    STATE["fail"] = True
    _, rec6 = run(tmp, ref, "failed.tsv")
    check("a run in which a caller failed is not stored", rec6["annotation_cache"]["stored"] is False, rec6.get("annotation_cache"))
    STATE["fail"] = False
    _, rec7 = run(tmp, ref, "afterfail.tsv")
    check("so the next run computes again instead of reusing the failure", rec7["annotation_cache"]["hit"] is False and CALLS)

    # a broken cache entry is ignored
    key = rec7["annotation_cache"]["key"]
    (tmp / "cache" / f"{key}.json").write_text("{not json", encoding="utf-8")
    _, rec8 = run(tmp, ref, "corrupt.tsv")
    check("a corrupt cache entry is ignored and recomputed", rec8["annotation_cache"]["hit"] is False and CALLS)
    # an unwritable cache never fails the annotation
    blocked = tmp / "blocked"
    blocked.write_text("a file, not a folder", encoding="utf-8")
    del CALLS[:]
    sys.argv = ["annotate_reference.py", "--reference", str(ref), "--out", str(tmp / "b.tsv"), "--cache-dir", str(blocked / "x")]
    check("an unusable cache folder does not stop the annotation", ar.main() == 0 and (tmp / "b.tsv").exists())
    # the real fingerprint works with no tools installed
    fp = REAL_FINGERPRINT("ncbi", "plasmidfinder", "")
    check("the real fingerprint lists every caller (or 'absent') and the database names", {"abricate", "amrfinder", "isescan", "barrnap", "amr_database", "replicon_database", "isfinder_fasta"} <= set(fp), fp)
    print(f"\n{'FAILED: ' + ', '.join(FAILED) if FAILED else 'all annotation-cache checks passed'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
