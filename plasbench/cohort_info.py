"""What is inside each cohort that ships with PlasBench: the window's Cohorts page.

For one cohort sample sheet (cohorts/<name>.tsv) this gathers:
  * its description: the sheet's own `#` header lines and its section in cohorts/README.md;
  * a summary: isolates, species, truth technology and quality tier, origin, country, read depth, plasmids in the
    truth, BioProjects and studies. Metagenomic sheets get communities, regimes, truth status and environments;
  * every row, joined with the verification lock (cohorts/<name>.lock.json) when there is one. The lock adds the
    sequencing behind the reference, the assembly method, the country, host, isolation source, collection date and
    the Illumina run's size;
  * whether the lock still matches the sheet (sha256), and the download estimate the lock allows. That estimate uses
    the same factors as python/estimate_download.py: 0.615 bytes per base of gzipped FASTQ, 12.1 MB of reference
    files per isolate.
Nothing is fetched from the network.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import statistics
from collections import Counter
from pathlib import Path

BYTES_PER_BASE = 0.615
REFERENCE_BYTES = 12.1e6
MAX_ROWS = 3000


def _sheet(path: Path):
    comments, lines = [], []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("#"):
            comments.append(line.lstrip("#").strip())
        elif line.strip():
            lines.append(line)
    rows = list(csv.DictReader(lines, delimiter="\t"))
    return comments, (rows[0].keys() if rows else []), rows


def _readme_section(root: Path, name: str) -> str:
    readme = root / "cohorts" / "README.md"
    try:
        text = readme.read_text(encoding="utf-8")
    except OSError:
        return ""
    m = re.search(rf"^## {re.escape(name)}\b.*?$(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(0).strip() if m else ""


def _counts(rows, key, top=12):
    c = Counter((r.get(key) or "").strip() or "not recorded" for r in rows)
    return [{"value": k, "n": v} for k, v in c.most_common(top)] + (
        [{"value": f"{len(c) - top} more", "n": sum(v for _, v in c.most_common()[top:])}] if len(c) > top else [])


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _country(geo: str) -> str:
    return (geo or "").split(":")[0].strip()


def kind_of(name: str, columns) -> str:
    if name.startswith("metagenomics") or "community_id" in columns:
        return "example" if ".example" in name else "metagenomic"
    return "isolate"


def info(root, name: str) -> dict:
    root = Path(root)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name or ""):
        raise ValueError("not a cohort name")
    path = root / "cohorts" / f"{name}.tsv"
    if not path.is_file():
        raise FileNotFoundError(f"no cohort {name}")
    comments, columns, rows = _sheet(path)
    columns = list(columns)
    kind = kind_of(name, columns)
    out = {"name": name, "path": str(path), "kind": kind, "comments": comments,
           "readme": _readme_section(root, name), "columns": columns, "n": len(rows)}

    # ---- the verification lock
    lock_path = path.with_name(f"{name}.lock.json")
    lock = None
    if lock_path.is_file():
        try:
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
        except ValueError:
            lock = None
    evidence = {e.get("sample_id"): e for e in (lock or {}).get("evidence", [])}
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    out["lock"] = {"present": lock is not None, "path": str(lock_path) if lock else "",
                   "matches_sheet": bool(lock) and lock.get("sample_sheet_sha256") == sha,
                   "samples": len(evidence),
                   "errors": sum(len(e.get("errors") or []) for e in evidence.values())}

    # ---- rows, joined with the lock
    extra_cols = []
    if evidence:
        extra_cols = ["country", "host", "isolation_source", "collection_date", "reference_sequencing",
                      "assembly_method", "read_gbases"]
        for r in rows:
            e = evidence.get(r.get("sample_id"), {})
            a, run = e.get("assembly") or {}, e.get("run") or {}
            bases = _num(run.get("bases"))
            r.update({"country": _country(a.get("geo_loc_name", "")), "host": a.get("host", ""),
                      "isolation_source": a.get("isolation_source", ""), "collection_date": a.get("collection_date", ""),
                      "reference_sequencing": a.get("sequencing_tech", ""), "assembly_method": a.get("assembly_method", ""),
                      "read_gbases": round(bases / 1e9, 2) if bases else ""})
    out["columns"] = columns + [c for c in extra_cols if c not in columns]
    out["rows"] = rows[:MAX_ROWS]
    out["truncated"] = len(rows) > MAX_ROWS

    # ---- summary
    s: dict = {}
    if kind == "isolate":
        depth = [d for d in (_num(r.get("read_depth_x")) for r in rows) if d]
        plas = [int(p) for p in (_num(r.get("assembly_plasmid_count")) for r in rows) if p is not None]
        s = {"isolates": len(rows),
             "species": len({(r.get("organism") or "").strip() for r in rows if r.get("organism")}),
             "organism": _counts(rows, "organism"),
             "truth_technology": _counts(rows, "truth_technology"),
             "truth_quality_tier": _counts(rows, "truth_quality_tier"),
             "sample_origin": _counts(rows, "sample_origin"),
             "bioprojects": len({r.get("bioproject") for r in rows if r.get("bioproject")}),
             "studies": len({r.get("source_study") for r in rows if r.get("source_study")}),
             "plasmids_total": sum(plas) if plas else None, "plasmids_recorded": len(plas),
             "plasmids_per_isolate": _counts([{"p": ("3 or more" if p >= 3 else str(p))} for p in plas], "p"),
             "depth": ({"min": min(depth), "median": statistics.median(depth), "max": max(depth), "n": len(depth)}
                       if depth else None)}
        if "truth_assembly_strategy" in columns:
            s["truth_assembly_strategy"] = _counts(rows, "truth_assembly_strategy")
        if evidence:
            s["country"] = _counts(rows, "country")
            gb = [_num(r.get("read_gbases")) for r in rows]
            gb = [g for g in gb if g]
            if gb:
                total_bases = sum(gb) * 1e9
                s["read_gbases_total"] = round(sum(gb), 1)
                s["download_estimate_gb"] = round((total_bases * BYTES_PER_BASE + REFERENCE_BYTES * len(rows)) / 1e9, 1)
    elif kind in ("metagenomic", "example"):
        s = {"samples": len(rows),
             "communities": len({r.get("community_id") for r in rows if r.get("community_id")})}
        for key in ("information_regime", "truth_status", "source_environment", "source_country", "dataset_class",
                    "input_read_technology", "comparability_group"):
            if key in columns:
                s[key] = _counts(rows, key)
    out["summary"] = s
    return out
