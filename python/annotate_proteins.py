#!/usr/bin/env python3
"""Create provenance-aware bacterial protein annotations for a FASTA file.

The normalized TSV is deliberately independent of a reconstruction method. It
can therefore annotate truth and every predicted FASTA with the same engine,
database and parameters. Raw FASTA has no protein names; absent annotation is
reported as ``not_evaluated`` and never interpreted as missing proteins.
"""
import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


FIELDS = ("sequence_id", "start", "end", "strand", "feature_id", "gene", "product",
          "category", "dbxref", "source", "version", "confidence")


def fasta_digest(path):
    """Hash normalized identifiers and bases, insensitive to line wrapping."""
    digest, name, sequence = hashlib.sha256(), None, []
    with path.open(encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if line.startswith(">"):
                if name is not None:
                    digest.update((name + "\n" + "".join(sequence).upper() + "\n").encode())
                name, sequence = line[1:].split()[0], []
            elif name is not None:
                sequence.append(line)
    if name is not None:
        digest.update((name + "\n" + "".join(sequence).upper() + "\n").encode())
    return digest.hexdigest()


def version(executable):
    for flag in ("--version", "-v", "version"):
        try:
            result = subprocess.run([executable, flag], text=True, capture_output=True, timeout=20)
        except OSError:
            continue
        text = (result.stdout or result.stderr).strip()
        if text:
            return text.splitlines()[0]
    return "unreported"


def attributes(text):
    values = {}
    for item in text.split(";"):
        if "=" in item:
            key, value = item.split("=", 1)
            values[key] = value.replace("%2C", ",")
    return values


def category(gene, product):
    text = f"{gene} {product}".lower()
    if any(word in text for word in ("beta-lactam", "antibiotic", "resistance", "bla", "mcr", "qnr")):
        return "amr"
    if any(word in text for word in ("replication", "repa", "repb", "rep_")):
        return "replication"
    if any(word in text for word in ("relaxase", "conjug", "transfer", "mobilization", "trai", "moba")):
        return "mobility"
    if any(word in text for word in ("transpos", "integrase", "insertion sequence")):
        return "mobile_element"
    if any(word in text for word in ("partition", "toxin", "antitoxin", "maintenance", "para", "parb")):
        return "maintenance"
    if "hypothetical" in text:
        return "hypothetical"
    return "other"


def parse_gff(path, source, tool_version, minimum_bp):
    rows = []
    with path.open(encoding="utf-8") as handle:
        for raw in handle:
            if not raw or raw.startswith("#"):
                continue
            fields = raw.rstrip("\n").split("\t")
            if len(fields) != 9 or fields[2] != "CDS":
                continue
            try:
                start, end = int(fields[3]) - 1, int(fields[4])
            except ValueError:
                continue
            if end - start < minimum_bp:
                continue
            info = attributes(fields[8])
            gene = info.get("gene") or info.get("Name") or ""
            product = info.get("product") or info.get("Name") or "hypothetical protein"
            rows.append({"sequence_id": fields[0].split()[0], "start": start, "end": end,
                         "strand": fields[6] if fields[6] in ("+", "-") else ".",
                         "feature_id": info.get("ID") or info.get("locus_tag") or f"{fields[0]}:{start}-{end}",
                         "gene": gene, "product": product, "category": category(gene, product),
                         "dbxref": info.get("Dbxref") or info.get("db_xref") or "",
                         "source": source, "version": tool_version,
                         "confidence": "named" if product.lower() != "hypothetical protein" else "hypothetical"})
    return rows


def database_identity(path):
    if not path:
        return "default"
    path = Path(path)
    for candidate in (path / "version.json", path / "VERSION", path / "version.txt"):
        if candidate.is_file():
            return hashlib.sha256(candidate.read_bytes()).hexdigest()[:16]
    return f"path:{path.resolve()}"


def run_engine(engine, fasta, workdir, threads, database=None):
    executable = shutil.which(engine)
    if not executable:
        return None, {"status": "not_evaluated", "reason": f"{engine} is not installed"}
    out = workdir / "output"
    out.mkdir()
    if engine == "bakta":
        command = [executable, "--output", str(out), "--prefix", "plasbench", "--threads", str(threads)]
        if database:
            command.extend(["--db", str(database)])
        command.append(str(fasta))
        expected = out / "plasbench.gff3"
    else:
        command = [executable, "--outdir", str(out), "--prefix", "plasbench", "--cpus", str(threads), "--force", str(fasta)]
        expected = out / "plasbench.gff"
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode != 0 or not expected.is_file():
        message = (result.stderr or result.stdout or "annotation output was not produced").strip().splitlines()[0]
        return None, {"status": "failed", "reason": message, "version": version(executable)}
    return expected, {"status": "ok", "version": version(executable), "command": command}


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fasta", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--provenance", required=True, type=Path)
    parser.add_argument("--engine", choices=("bakta", "prokka", "none"), default="bakta")
    parser.add_argument("--reuse-gff", type=Path, help="Compatible GFF3/GFF to normalize instead of re-annotating.")
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--database", type=Path, help="Pinned Bakta database directory, when required by the local installation.")
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--minimum-bp", type=int, default=90)
    args = parser.parse_args()
    if not args.fasta.is_file():
        raise SystemExit(f"ERROR: FASTA not found: {args.fasta}")
    digest = fasta_digest(args.fasta)
    engine_version = "provided" if args.reuse_gff else (version(shutil.which(args.engine)) if args.engine != "none" and shutil.which(args.engine) else "not-installed")
    database_id = database_identity(args.database)
    # A Bakta default database can change outside PlasBench's control. Do not
    # persist/reuse it unless the caller supplies a versioned database path.
    cacheable = bool(args.cache_dir) and (args.engine != "bakta" or args.database is not None)
    cache_tsv = cache_meta = None
    if cacheable:
        key = f"{digest}.{args.engine}.{engine_version}.{database_id}.min{args.minimum_bp}"
        key = hashlib.sha256(key.encode()).hexdigest()
        cache_tsv, cache_meta = args.cache_dir / f"{key}.tsv", args.cache_dir / f"{key}.json"
        if cache_tsv.is_file() and cache_meta.is_file():
            record = json.loads(cache_meta.read_text(encoding="utf-8"))
            if record.get("engine_version") == engine_version and record.get("database_identity") == database_id:
                shutil.copyfile(cache_tsv, args.out)
                record.update({"cache": "reused", "output": str(args.out)})
                args.provenance.parent.mkdir(parents=True, exist_ok=True)
                args.provenance.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                print(f"Reused cached protein annotation: {args.out}")
                return
    provenance = {"schema_version": "1.0", "fasta": str(args.fasta), "sequence_sha256": digest,
                  "engine": args.engine, "engine_version": engine_version, "database": str(args.database or "default"),
                  "database_identity": database_id, "minimum_bp": args.minimum_bp,
                  "cache": "miss" if cacheable else "disabled_unpinned_database"}
    gff = args.reuse_gff if args.reuse_gff and args.reuse_gff.is_file() else None
    if gff:
        provenance.update({"status": "ok", "source": "reused_gff", "gff": str(gff), "version": "provided"})
    elif args.engine == "none":
        provenance.update({"status": "not_evaluated", "reason": "protein annotation disabled"})
    else:
        with tempfile.TemporaryDirectory(prefix="plasbench_annotation_") as temp:
            gff, status = run_engine(args.engine, args.fasta, Path(temp), max(1, args.threads), args.database)
            provenance.update(status)
            rows = parse_gff(gff, args.engine, status.get("version", "unreported"), args.minimum_bp) if gff else []
    if gff and 'rows' not in locals():
        rows = parse_gff(gff, "reused_gff", "provided", args.minimum_bp)
    write_rows(args.out, rows if provenance.get("status") == "ok" else [])
    provenance["features_written"] = len(rows if provenance.get("status") == "ok" else [])
    provenance["meaning"] = "No rows means no evaluated CDS calls, not that the sequence contains no proteins."
    args.provenance.parent.mkdir(parents=True, exist_ok=True)
    args.provenance.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if cache_tsv and provenance.get("status") == "ok":
        args.cache_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.out, cache_tsv)
        cache_meta.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Protein annotation {provenance['status']}: {args.out} ({provenance['features_written']} CDS feature(s))")


if __name__ == "__main__":
    main()
