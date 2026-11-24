#!/usr/bin/env python3
"""How far a read download has got, for the run log.

Stage 1 can spend an hour on one isolate (a 9.5 GB paired run) and print nothing, because the downloader writes to its own log. The run then
looks stalled. `scripts/01_download.sh` calls this every minute while a download is running and logs one line, so the log shows progress.

ENA downloads are written to `<run>_<mate>.fastq.gz.part`. When aria2c does the transfer it preallocates that file at its FULL size, so the file
size says nothing about progress; aria2c keeps the truth in `<file>.part.aria2`, a control file holding the transfer's piece bitmap. This reads
it (the layout was checked against a real 4.7 GB transfer: the total length it records equals the .part file's size). Without a control file
(the Python downloader, which grows the file) the size of the .part file is the progress, against --total-bytes when it is known.

  python download_progress.py --data-dir DIR --run SRR123 [--total-bytes N]
  -> SRR123: mate 1 74.7%, mate 2 66.2% (7.1 of 9.5 GB)

Standard library only. Exit status is always 0: a progress line must never stop a download.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import struct
import sys
import time


def aria2_progress(control_path):
    """(done_bytes, total_bytes) from an aria2 control file, or None when it cannot be read (not an aria2 file, a partly written one, a version
    this does not know). done_bytes counts completed pieces, so it can be a little under what is on disk (pieces in flight are not counted).

    Layout, big-endian: version(2) extension(4) infoHashLength(4) infoHash piece length(4) total length(8) upload length(8) bitfield length(4) bitfield.
    """
    try:
        with open(control_path, "rb") as handle:
            data = handle.read()
        offset = 6
        (hash_len,) = struct.unpack(">I", data[offset:offset + 4])
        offset += 4 + hash_len
        (piece,) = struct.unpack(">I", data[offset:offset + 4])
        offset += 4
        (total,) = struct.unpack(">Q", data[offset:offset + 8])
        offset += 16
        (bits_len,) = struct.unpack(">I", data[offset:offset + 4])
        offset += 4
        bitfield = data[offset:offset + bits_len]
    except (OSError, struct.error):
        return None
    if piece <= 0 or total <= 0 or len(bitfield) < bits_len:
        return None
    pieces = -(-total // piece)
    if bits_len * 8 < pieces:
        return None
    done = 0
    for index in range(pieces):
        if bitfield[index >> 3] & (0x80 >> (index & 7)):
            done += piece if index < pieces - 1 else total - piece * (pieces - 1)
    return min(done, total), total


def mate_progress(data_dir, run, mate, total_bytes=None):
    """{'mate', 'state', 'done', 'total'} for one mate: 'done' (the final file exists), 'aria2', 'growing' (a .part file, size = progress) or 'waiting'."""
    final = os.path.join(data_dir, f"{run}_{mate}.fastq.gz")
    part = final + ".part"
    if os.path.isfile(final) and os.path.getsize(final) > 0 and not os.path.exists(part):
        size = os.path.getsize(final)
        return {"mate": mate, "state": "done", "done": size, "total": size}
    control = part + ".aria2"
    if os.path.isfile(control):
        progress = aria2_progress(control)
        if progress:
            return {"mate": mate, "state": "aria2", "done": progress[0], "total": progress[1]}
    if os.path.isfile(part):
        return {"mate": mate, "state": "growing", "done": os.path.getsize(part), "total": None}
    return {"mate": mate, "state": "waiting", "done": 0, "total": None}


def read_progress_file(path, run, now=None, max_age=180):
    """The line the downloader wrote for `run` into results/download_progress.json (honest bytes received, not file sizes), or None when it is missing, unreadable or stale."""
    try:
        with open(path, encoding="utf-8") as handle:
            entry = json.load(handle).get("isolates", {}).get(run)
        if entry and (time.time() if now is None else now) - float(entry.get("updated", 0)) <= max_age and entry.get("line"):
            return entry["line"]
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return None


def stage_summary(progress_file, via_dir, seconds):
    """One line for the end of stage 1: bytes, time, MB/s, isolates via ENA and via the SRA Toolkit, retries and resumes."""
    received = retries = resumed = 0
    try:
        with open(progress_file, encoding="utf-8") as handle:
            entries = json.load(handle).get("isolates", {})
        for entry in entries.values():
            received += int(entry.get("received_bytes", 0))
            retries += int(entry.get("retries", 0))
            resumed += int(entry.get("resumed_bytes", 0))
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    via = {"ena": 0, "sra": 0}
    for path in glob.glob(os.path.join(via_dir, "*.via")):
        try:
            with open(path, encoding="utf-8") as handle:
                kind = handle.read().strip()
            via[kind] = via.get(kind, 0) + 1
        except OSError:
            pass
    gb = f"{received / 1e9:.1f} GB" if received >= 1e9 else f"{received / 1e6:.0f} MB"
    rate = f"{received / max(seconds, 1) / 1e6:.1f} MB/s" if received else "no read bytes transferred by ENA"
    mins = f"{seconds / 60:.0f} min" if seconds >= 90 else f"{int(seconds)} s"
    return (f"Download summary: {gb} of reads fetched from ENA in {mins} ({rate} on average); isolates via ENA {via.get('ena', 0)}, via the SRA Toolkit {via.get('sra', 0)}; "
            f"{retries} chunk retries, {resumed / 1e6:.0f} MB resumed from earlier attempts.")


def log_lines(progress_file, run, state_file):
    """Print the lines due for the run log. Prints nothing when there is no fresh entry for the run yet (never a made-up line)."""
    try:
        with open(progress_file, encoding="utf-8") as handle:
            entry = json.load(handle).get("isolates", {}).get(run)
        if not entry or time.time() - float(entry.get("updated", 0)) > 180:
            return
        try:
            with open(state_file, encoding="utf-8") as handle:
                state = json.load(handle)
        except (OSError, ValueError):
            state = {}
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import ena_download
        lines = ena_download.LogGate(state).check(dict(entry, run=run))
        if state_file:
            with open(state_file, "w", encoding="utf-8") as handle:
                json.dump(state, handle)
        for text in lines:
            print(text)
    except Exception:  # noqa: BLE001 - a progress line must never stop a download
        return


def describe(data_dir, run, total_bytes=None, progress_file=None):
    """One line for the run log, e.g. 'SRR123: 3.2 of 9.5 GB (34%), 3.4 MB/s now, 3.1 MB/s average, about 31 min left'."""
    line = read_progress_file(progress_file, run) if progress_file else None
    if line:
        return line
    mates = [mate_progress(data_dir, run, m, total_bytes) for m in ("1", "2")]
    if all(m["state"] == "waiting" for m in mates):
        return f"{run}: starting (nothing written yet)"
    done = sum(m["done"] for m in mates)
    known = [m["total"] for m in mates]
    total = sum(known) if all(t for t in known) else (total_bytes or None)
    parts = []
    for m in mates:
        if m["state"] == "done":
            parts.append(f"mate {m['mate']} complete")
        elif m["total"]:
            parts.append(f"mate {m['mate']} {100 * m['done'] / m['total']:.1f}%")
        elif m["state"] == "growing" and total_bytes:
            parts.append(f"mate {m['mate']} {m['done'] / 1e9:.2f} GB so far")
        else:
            parts.append(f"mate {m['mate']} {m['done'] / 1e9:.2f} GB so far" if m["state"] == "growing" else f"mate {m['mate']} waiting")
    tail = f" ({done / 1e9:.1f} of {total / 1e9:.1f} GB)" if total else f" ({done / 1e9:.1f} GB so far)"
    return f"{run}: " + ", ".join(parts) + tail


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default=".")
    ap.add_argument("--run", default="")
    ap.add_argument("--total-bytes", type=int, help="the run's total FASTQ bytes when known (fetch_ena_reads.py --size-only)")
    ap.add_argument("--progress-file", help="results/download_progress.json, written by python/fetch_ena_reads.py")
    ap.add_argument("--log-line", action="store_true", help="print the progress lines that are DUE for the run log (python/ena_download.py LogGate: the first, one per 10%% and 5 minutes, and changes); needs --progress-file and --state-file")
    ap.add_argument("--state-file", help="where --log-line keeps what it has already printed")
    ap.add_argument("--summary", action="store_true", help="print the end-of-stage summary instead (needs --progress-file, --via-dir, --seconds)")
    ap.add_argument("--via-dir")
    ap.add_argument("--seconds", type=float, default=0)
    args = ap.parse_args()
    if args.log_line:
        log_lines(args.progress_file or "", args.run, args.state_file or "")
        return
    if args.summary:
        print(stage_summary(args.progress_file or "", args.via_dir or ".", args.seconds))
        return
    try:
        print(describe(args.data_dir, args.run, args.total_bytes, args.progress_file))
    except Exception as exc:  # noqa: BLE001 - a progress line must never stop a download
        print(f"{args.run}: progress unavailable ({exc})")


if __name__ == "__main__":
    main()
