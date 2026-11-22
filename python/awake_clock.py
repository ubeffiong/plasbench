#!/usr/bin/env python3
"""Computer sleep (suspend) bookkeeping: find the time a computer was asleep during a run and take it out of every "how long did this take" figure.

Why: on a laptop the run can be paused by Windows or the lid. The clock keeps counting, so a 4-minute fastp step showed 10,096 s, "slow step" warnings fired and
annotation callers were killed by their wall-clock time limits. A pause is not slowness. Everything here works on wall-clock epochs, which keep counting during sleep,
so it does not matter whether the operating system's monotonic clock does (on WSL2 that varies; the detector uses whichever of the two clocks shows the jump).

  python3 awake_clock.py record  GAPS_FILE START END [--events FILE] [--source NAME]   append one gap (and a system_suspend event unless it was already recorded)
  python3 awake_clock.py sum     GAPS_FILE START [END]                                  seconds of sleep inside START..END (END defaults to now), overlaps merged
  python3 awake_clock.py format  SECONDS                                                "2 h 47 min"

The gaps file holds one line per gap: "<start_epoch> <end_epoch> <source>". Overlapping lines (two watchers saw the same sleep) count once.
"""
from __future__ import annotations

import json
import os
import sys
import time

# A pause shorter than this is not called a sleep: a loaded computer or a stopped process can stall for a while without any suspend.
MIN_SUSPEND_SECONDS = 60.0


def human(seconds):
    seconds = int(max(0, round(float(seconds))))
    if seconds < 90:
        return f"{seconds} s"
    if seconds < 5400:
        return f"{seconds // 60} min"
    return f"{seconds // 3600} h {seconds % 3600 // 60:02d} min"


def clock_time(epoch):
    return time.strftime("%H:%M", time.localtime(epoch))


def describe(start, end):
    """The plain sentence shown by `plasbench status` and the window."""
    return (f"The computer was asleep from {clock_time(start)} to {clock_time(end)} ({human(end - start)}); the run was paused, not slow.")


def detect_gap(wall_delta, mono_delta, expected, threshold=MIN_SUSPEND_SECONDS):
    """Seconds of suspend between two polls, or 0.0. `wall_delta` and `mono_delta` are how far the wall and the monotonic clock moved between the two polls and
    `expected` is how long the poll meant to wait. Either clock showing a jump larger than `threshold` over the expected wait is a suspend: if the monotonic clock
    stops during sleep (some Linux kernels, some WSL2 versions) the wall clock shows it; if the monotonic clock counts the sleep the overshoot of the wait shows it."""
    gap = wall_delta - min(max(mono_delta, 0.0), max(expected, 0.0))
    return float(gap) if gap > threshold else 0.0


def merge(intervals):
    out = []
    for start, end in sorted((s, e) for s, e in intervals if e > s):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def read_gaps(path):
    gaps = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        gaps.append((float(parts[0]), float(parts[1])))
                    except ValueError:
                        continue
    except OSError:
        pass
    return merge(gaps)


def overlap_seconds(gaps, start, end):
    """Seconds of `gaps` (merged) that lie inside start..end."""
    total = 0.0
    for gap_start, gap_end in merge(gaps):
        total += max(0.0, min(end, gap_end) - max(start, gap_start))
    return total


def awake_seconds(gaps, start, end):
    return max(0.0, (end - start) - overlap_seconds(gaps, start, end))


def already_recorded(gaps, start, end):
    """True when an existing gap covers at least half of this one (two watchers saw the same sleep)."""
    return overlap_seconds(gaps, start, end) >= 0.5 * (end - start)


def write_event(events_file, event, **fields):
    row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "epoch": int(time.time()), "pid": os.getpid(), "event": event}
    row.update({key: str(value) for key, value in fields.items()})
    try:
        with open(events_file, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
    except OSError:
        pass


def record_gap(gaps_file, start, end, events_file=None, source="clock"):
    """Append one gap unless it was already recorded; returns True when it was new. Never raises."""
    if end - start <= 0:
        return False
    if already_recorded(read_gaps(gaps_file), start, end):
        return False
    try:
        with open(gaps_file, "a", encoding="utf-8") as handle:
            handle.write(f"{start:.0f} {end:.0f} {source}\n")
    except OSError:
        return False
    if events_file:
        write_event(events_file, "system_suspend", start_epoch=int(start), end_epoch=int(end), gap_seconds=int(end - start), source=source,
                    message=describe(start, end))
    return True


class AwakeTimer:
    """Elapsed time with the computer's sleep taken out. Call tick() at least every few seconds while waiting; elapsed() then excludes (a) gaps this timer saw itself
    and (b) gaps another watcher (the run's sentinel) wrote to the gaps file (default RESULTS_DIR/.suspend_gaps), whichever is larger. The clocks are injectable for tests."""

    def __init__(self, gaps_file=None, threshold=None, expected=5.0, wall=time.time, mono=time.monotonic):
        self.wall, self.mono, self.expected = wall, mono, float(expected)
        self.threshold = float(os.environ.get("SUSPEND_MIN_SECONDS") or MIN_SUSPEND_SECONDS) if threshold is None else float(threshold)
        if gaps_file is None and os.environ.get("RESULTS_DIR"):
            gaps_file = os.path.join(os.environ["RESULTS_DIR"], ".suspend_gaps")
        self.gaps_file = gaps_file
        self.start = self.last_wall = wall()
        self.last_mono = mono()
        self.local = []

    def tick(self):
        """Look at the clocks; returns the seconds of sleep found since the last tick (0.0 when none)."""
        now_wall, now_mono = self.wall(), self.mono()
        gap = detect_gap(now_wall - self.last_wall, now_mono - self.last_mono, self.expected, self.threshold)
        if gap:
            self.local.append((now_wall - gap, now_wall))
        self.last_wall, self.last_mono = now_wall, now_mono
        return gap

    def suspended(self, now=None):
        now = self.wall() if now is None else now
        local = overlap_seconds(self.local, self.start, now)
        filed = overlap_seconds(read_gaps(self.gaps_file), self.start, now) if self.gaps_file else 0.0
        return max(local, filed)

    def elapsed(self, now=None):
        now = self.wall() if now is None else now
        return max(0.0, now - self.start - self.suspended(now))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 2
    command = argv.pop(0)
    if command == "format" and argv:
        print(human(float(argv[0])))
        return 0
    if command == "sum" and len(argv) >= 2:
        start = float(argv[1])
        end = float(argv[2]) if len(argv) > 2 else time.time()
        print(int(round(overlap_seconds(read_gaps(argv[0]), start, end))))
        return 0
    if command == "record" and len(argv) >= 3:
        events, source = None, "clock"
        rest = argv[3:]
        while rest:
            flag = rest.pop(0)
            if flag == "--events" and rest:
                events = rest.pop(0)
            elif flag == "--source" and rest:
                source = rest.pop(0)
        record_gap(argv[0], float(argv[1]), float(argv[2]), events, source)
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
