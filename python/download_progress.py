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
import os
import struct


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


def describe(data_dir, run, total_bytes=None):
    """One line for the run log, e.g. 'SRR123: mate 1 74.7%, mate 2 66.2% (7.1 of 9.5 GB)'."""
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
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--total-bytes", type=int, help="the run's total FASTQ bytes when known (fetch_ena_reads.py --size-only)")
    args = ap.parse_args()
    try:
        print(describe(args.data_dir, args.run, args.total_bytes))
    except Exception as exc:  # noqa: BLE001 - a progress line must never stop a download
        print(f"{args.run}: progress unavailable ({exc})")


if __name__ == "__main__":
    main()
