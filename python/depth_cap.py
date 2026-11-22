#!/usr/bin/env python3
"""The read-depth cap: fetch only the first N read pairs of a very deep short-read run (READ_DEPTH_CAP_X, default 150; 0 or `off` = whole files).

Why. A 9.5 GB Streptomyces read set (about 8.8 Mb genome, several hundred x) took 4 hours to download and would cost hours and more than 7 GB of memory in trimming and SPAdes,
for no benefit beyond roughly 100-150x. Stage 1 knows the reference size (reference.fna is downloaded before the reads) and ENA's file report gives read_count and base_count, so the
number of read pairs that gives the cap is computed, and only a prefix of each mate's .fastq.gz is fetched (HTTP Range).

Method. target_pairs = ceil(cap_x * reference_bases / mean_bases_per_pair), where mean_bases_per_pair = base_count / read_count (ENA counts a paired run's read_count in spots, i.e. pairs,
and base_count over both mates). A prefix of a gzip stream decompresses up to the cut, so the prefix of each mate (a little longer than the share of the file the pairs need, plus
a margin) is fetched, stream-decompressed, cut after exactly target_pairs complete 4-line records in BOTH mates, and recompressed deterministically (gzip level 5, no timestamp or
name, like `gzip -n`) to the final names. If the prefix holds fewer records than needed it is extended and the cut repeated.

What is checked (a prefix has no whole-file MD5, and a gzip CRC32 sits in the last 8 bytes of the file, so neither can apply): every record has 4 lines, '@' and '+' markers and a
sequence and quality of equal length; both mates have exactly target_pairs records; the first and last read names of the two mates pair up; the deflate stream decodes without error.
The provenance JSON says so plainly ("prefix of the file, whole-file md5 not checked").

Assumptions. Reads in an ENA FASTQ are in sequencer output order, so the first reads are an unbiased-enough sample for a bacterial isolate (no tile or lane is over-represented in the
first millions of reads of a run). It is NOT a random sample; READ_DEPTH_CAP_X=off fetches whole files. The cap applies only to short paired Illumina runs (mean mate length at most
1000 bases); long-read and unpaired runs are always fetched whole. Depth here is total bases (both mates) over the reference's total bases.

Standard library only; Python 3.9 compatible.
"""
from __future__ import annotations

import gzip
import math
import os
import zlib

DEFAULT_CAP_X = 150.0
SAFETY = float(os.environ.get("PLASBENCH_CAP_SAFETY", "1.05") or 1.05)   # (the environment variable exists for the tests) the prefix is this much longer than the proportional share of the file (reads early in a file are not exactly average)
MARGIN = int(os.environ.get("PLASBENCH_CAP_MARGIN", str(1 << 20)) or (1 << 20))   # (also an environment variable for the tests)
WORTH_IT = 0.85                # a prefix of more than this share of the whole files is not worth it: fetch the whole files (and check their MD5)
SHORT_READ_MAX = 1000


class NeedMore(Exception):
    """The prefix ended before target_pairs complete records."""

    def __init__(self, records):
        super().__init__(f"the prefix holds only {records} complete records")
        self.records = records


def parse_cap(value):
    """READ_DEPTH_CAP_X -> a number (0 = off). Empty means the default; 'off', 'none', 'no', '0' mean off; an unreadable value is treated as the default."""
    text = str(value if value is not None else "").strip().lower()
    if text == "":
        return DEFAULT_CAP_X
    if text in ("off", "none", "no", "false", "whole"):
        return 0.0
    try:
        return max(0.0, float(text))
    except ValueError:
        return DEFAULT_CAP_X


def _num(value):
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def plan(cap_x, ref_bases, report, file_bytes):
    """What to fetch for one run. `report` is the ENA file-report row (read_count, base_count, library_layout, instrument_platform); `file_bytes` the two mates' sizes.

    Returns a dict that always has `capped` (bool) and `reason` (plain words). When capped it also has target_pairs, prefix_bytes (per mate), fetch_bytes, full_bytes, depth (before),
    est_depth (after), mean_pair_bases, read_count, base_count, ref_bases, cap_x.
    """
    out = {"capped": False, "cap_x": cap_x, "ref_bases": int(ref_bases or 0), "full_bytes": int(sum(file_bytes))}
    if not cap_x:
        out["reason"] = "READ_DEPTH_CAP_X is off: whole files"
        return out
    if report.get("library_layout") != "PAIRED":
        out["reason"] = "not a paired run: whole files"
        return out
    platform = (report.get("instrument_platform") or "").upper()
    if platform and platform != "ILLUMINA":
        out["reason"] = f"{platform.title()} reads are not capped: whole files"
        return out
    if not ref_bases:
        out["reason"] = "the reference size is not known (no assembly for this isolate yet), so the depth cannot be computed: whole files"
        return out
    pairs, bases = _num(report.get("read_count")), _num(report.get("base_count"))
    if pairs <= 0 or bases <= 0:
        out["reason"] = "ENA gives no read or base count for this run, so the depth cannot be computed: whole files"
        return out
    per_pair = bases / pairs
    if per_pair / 2 > SHORT_READ_MAX:
        out["reason"] = "the reads are long (mean over %d bases per mate): whole files" % SHORT_READ_MAX
        return out
    depth = bases / float(ref_bases)
    out.update(read_count=pairs, base_count=bases, mean_pair_bases=per_pair, depth=depth)
    if depth <= cap_x:
        out["reason"] = f"about {depth:.0f}x, within the {cap_x:g}x cap: whole files"
        return out
    target = int(math.ceil(cap_x * ref_bases / per_pair))
    prefix = [min(int(b), int(math.ceil(int(b) * target / float(pairs) * SAFETY)) + MARGIN) for b in file_bytes]
    if sum(prefix) >= WORTH_IT * sum(file_bytes):
        out["reason"] = f"about {depth:.0f}x, but a prefix would be most of the files: whole files"
        return out
    out.update(capped=True, target_pairs=target, prefix_bytes=prefix, fetch_bytes=int(sum(prefix)), est_depth=target * per_pair / float(ref_bases),
               reason=f"about {depth:.0f}x, above the {cap_x:g}x cap")
    return out


def describe(run, plan_):
    """The one plain line printed per isolate."""
    def human(n):
        return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"
    if not plan_.get("capped"):
        return f"{run}: {human(plan_['full_bytes'])} available, {plan_['reason']}"
    return (f"{run}: {human(plan_['full_bytes'])} available, {plan_['cap_x']:g}x cap needs about {human(plan_['fetch_bytes'])}, "
            f"fetching the first {plan_['target_pairs'] / 1e6:.1f} M pairs (the full set stays on ENA)")


def reference_bases(path):
    """Total bases of a FASTA (0 when it cannot be read)."""
    total = 0
    try:
        with open(path, "rb") as handle:
            for line in handle:
                if not line.startswith(b">"):
                    total += len(line.strip())
    except OSError:
        return 0
    return total


def _read_name(line):
    name = line[1:].split(None, 1)[0] if len(line) > 1 else b""
    return name[:-2] if name.endswith((b"/1", b"/2")) else name


def cut_prefix(src, dst, target_pairs):
    """Decompress the gzip prefix `src`, keep the first `target_pairs` complete FASTQ records, write them gzip-compressed (deterministic) to `dst`.

    Returns {"records", "first_name", "last_name", "compressed_in"}. Raises NeedMore when the prefix ends first and ValueError for a malformed record or a damaged stream.
    """
    decoder = zlib.decompressobj(31)
    pending = b""
    records = 0
    first = last = b""
    consumed = 0
    raw = open(dst, "wb")
    out = None
    try:
        out = gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=5, mtime=0)
        with open(src, "rb") as handle:
            while records < target_pairs:
                block = handle.read(1 << 20)
                if not block:
                    break
                consumed += len(block)
                while block:
                    try:
                        data = decoder.decompress(block)
                    except zlib.error as exc:
                        raise ValueError(f"the compressed reads are damaged near byte {consumed}: {exc}")
                    block = b""
                    if decoder.eof and decoder.unused_data:       # another gzip member follows (a file written in several parts)
                        block = decoder.unused_data
                        decoder = zlib.decompressobj(31)
                    pending += data
                    lines = pending.split(b"\n")
                    tail = lines.pop()
                    usable = min(len(lines) // 4, target_pairs - records)
                    for i in range(usable):
                        a, b, c, d = lines[4 * i:4 * i + 4]
                        if not a.startswith(b"@") or not c.startswith(b"+") or len(b) != len(d) or not b:
                            raise ValueError(f"record {records + i + 1} is not a valid FASTQ record (4 lines, '@' and '+' markers, equal sequence and quality length)")
                        if records + i == 0:
                            first = _read_name(a)
                        last = _read_name(a)
                    if usable:
                        out.write(b"\n".join(lines[:4 * usable]) + b"\n")
                        records += usable
                    leftover = lines[4 * usable:]
                    pending = b"\n".join(leftover + [tail]) if leftover else tail
                    if records >= target_pairs:
                        break
        out.close()
        raw.flush()
        os.fsync(raw.fileno())
    finally:
        try:
            if out is not None:
                out.close()
        except (OSError, ValueError):
            pass
        raw.close()
    if records < target_pairs:
        raise NeedMore(records)
    return {"records": records, "first_name": first.decode("ascii", "replace"), "last_name": last.decode("ascii", "replace"), "compressed_in": consumed}


def check_pair(a, b, target_pairs):
    """Both cut mates must hold target_pairs records, and the first and last read names must pair. Raises ValueError otherwise."""
    if a["records"] != target_pairs or b["records"] != target_pairs:
        raise ValueError(f"the two mates have {a['records']} and {b['records']} reads, expected {target_pairs} in both")
    if a["first_name"] != b["first_name"] or a["last_name"] != b["last_name"]:
        raise ValueError(f"the mates do not pair: first reads {a['first_name']} / {b['first_name']}, last reads {a['last_name']} / {b['last_name']}")
