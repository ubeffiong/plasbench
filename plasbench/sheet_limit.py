"""Run only the first N isolates of a cohort or sample sheet (`plasbench run --max-isolates N`).

N isolates are written to a copy of the sheet next to the run's results, and the run is pointed at the copy. The
cohort file itself is never changed, so its lock still matches it and the next run can use the full cohort again.

Which N: by default a *balanced* N (order="balanced"): spread across species, across studies, and across the
recent / older arms, so a small run is a fair miniature of the cohort instead of the first species in the file.
order="file" takes the first N rows exactly as they appear. A sheet with no organism column has nothing to balance
on and is read in file order. The balanced order depends only on the rows' own values, so it is the same on every
computer, and a sheet that is already in balanced order (public-v4 is written that way) gives the same rows either way.

`#` comment lines and blank lines are skipped when counting; the header and each kept row are copied exactly as
written. A leading comment records where the copy came from.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))


class Limited(NamedTuple):
    path: Path | None    # the limited copy, or None when the sheet has N rows or fewer (nothing to cut)
    total: int           # data rows in the sheet
    kept: int            # data rows the run will use


def limit_sheet(source, limit: int, dest_dir, order: str = "balanced") -> Limited:
    source = Path(source)
    if order not in ("balanced", "file"):
        raise ValueError("the isolate order must be 'balanced' or 'file'")
    if limit < 1:
        raise ValueError("--max-isolates must be a positive number")
    try:
        lines = source.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError as exc:
        raise ValueError(f"cannot read the sample sheet {source}: {exc}") from exc
    header, data = None, []
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if header is None:
            header = line
        else:
            data.append(line)
    if header is None:
        raise ValueError(f"the sample sheet {source} has no header row")
    total = len(data)
    if total <= limit:
        return Limited(None, total, total)
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    columns = next(csv.reader([header.rstrip("\r\n")], delimiter="\t"))
    balanced = order == "balanced" and "organism" in columns
    chosen = data[:limit]
    if balanced:
        from plasbench_common import balanced_order
        parsed = [dict(zip(columns, next(csv.reader([row.rstrip("\r\n")], delimiter="\t")))) for row in data]
        chosen = [data[i] for i in balanced_order(parsed)[:limit]]
    out = dest_dir / f"{source.stem}.{'balanced' if balanced else 'first'}_{limit}{source.suffix or '.tsv'}"
    what = ("a balanced selection (spread across species, studies and recent / older)" if balanced else "the first rows, in file order")
    note = f"# PlasBench --max-isolates {limit}: {limit} of {total} isolates of {source.name}, {what}.\n"
    body = [header if header.endswith("\n") else header + "\n"] + [row if row.endswith("\n") else row + "\n" for row in chosen]
    out.write_text(note + "".join(body), encoding="utf-8", newline="")
    return Limited(out, total, limit)


def independent_truth_only(source, dest_dir) -> Limited:
    """A copy of the sheet with only the isolates whose truth is independent of the benchmark's reads (`plasbench run --independent-truth-only`).

    Independent means what truth_provenance.independence() says: a long-read-only or long-read-first assembly whose polishing reads are `none` or `independent`.
    Needs the sheet's truth_assembly_strategy and truth_polish_reads columns (public-v4 has them). The cohort file is not changed, so its lock still matches;
    the copy is written next to the results. A sheet with none of these isolates is an error, not an empty run.
    """
    source = Path(source)
    try:
        lines = source.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError as exc:
        raise ValueError(f"cannot read the sample sheet {source}: {exc}") from exc
    header, data = None, []
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if header is None:
            header = line
        else:
            data.append(line)
    if header is None:
        raise ValueError(f"the sample sheet {source} has no header row")
    columns = next(csv.reader([header.rstrip("\r\n")], delimiter="\t"))
    if "truth_assembly_strategy" not in columns or "truth_polish_reads" not in columns:
        raise ValueError(f"{source.name} has no truth_assembly_strategy and truth_polish_reads columns, so independent truth cannot be selected; "
                         "run `plasbench collect-truth-provenance` or use a cohort that records them (public-v4 does)")
    from truth_provenance import independence
    kept = []
    for row in data:
        record = dict(zip(columns, next(csv.reader([row.rstrip("\r\n")], delimiter="\t"))))
        if independence((record.get("truth_assembly_strategy") or "").strip(), (record.get("truth_polish_reads") or "").strip())[0] == "independent":
            kept.append(row if row.endswith("\n") else row + "\n")
    if not kept:
        raise ValueError(f"{source.name} has no isolate whose truth is independent of the benchmark's reads")
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"{source.stem}.independent{source.suffix or '.tsv'}"
    note = f"# PlasBench --independent-truth-only: {len(kept)} of {len(data)} isolates of {source.name} whose truth is independent of the benchmark's reads.\n"
    out.write_text(note + (header if header.endswith("\n") else header + "\n") + "".join(kept), encoding="utf-8", newline="")
    return Limited(out, len(data), len(kept))
