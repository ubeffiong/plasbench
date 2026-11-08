#!/usr/bin/env python3
"""Adapt a pre-computed PlasBin-flow output TSV to PlasBench's standard form.

PlasBin-flow writes `#Pls_ID<TAB>Flow<TAB>GC_bin<TAB>Contigs`, one bin per
line, Contigs = comma-separated `contig:multiplicity`. A contig may be listed
in several bins; PlasBench needs each contig exactly once, so it is assigned to
the first bin (file order) that lists it; the other bins are recorded in the
provenance JSON under `contigs_in_multiple_bins`.
"""
import argparse
import hashlib
import json
import sys


def read_fasta(path):
    recs = {}
    order = []
    cur = None
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.rstrip("\r\n")
            if line.startswith(">"):
                toks = line[1:].split()
                cur = toks[0] if toks else ""
                if cur in recs:
                    raise ValueError("duplicate contig id in assembly FASTA: %s" % cur)
                recs[cur] = []
                order.append(cur)
            elif cur is not None and line.strip():
                recs[cur].append(line.strip())
    return {k: "".join(v) for k, v in recs.items()}


def parse_bins(path):
    """Return list of dicts: id, flow, gc_bin, contigs [(id, mult)]."""
    bins = []
    seen = set()
    nonblank = 0
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.rstrip("\r\n")
            if not line.strip():
                continue
            nonblank += 1
            if line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 4:
                parts = line.split()
            if len(parts) < 4:
                raise ValueError("unparsable PlasBin-flow line (need 4 columns): %r" % line)
            pid, flow, gcb = parts[0].strip(), parts[1].strip(), parts[2].strip()
            contigs_field = parts[3].strip()
            if pid in seen:
                raise ValueError("duplicated plasmid id in PlasBin-flow output: %s" % pid)
            seen.add(pid)
            contigs = []
            for item in contigs_field.split(","):
                item = item.strip()
                if not item:
                    continue
                cid, mult = item, 1
                if ":" in item:
                    head, _, tail = item.rpartition(":")
                    try:
                        mult = int(float(tail))
                        cid = head
                    except ValueError:
                        cid, mult = item, 1
                contigs.append((cid, mult))
            bins.append({"id": pid, "flow": flow, "gc_bin": gcb, "contigs": contigs})
    header_only = nonblank > 0 and not bins and all(
        l.lstrip().startswith("#") for l in open(path, encoding="utf-8", errors="replace") if l.strip())
    if nonblank and not bins and not header_only:
        raise ValueError("no parsable bin line in non-empty PlasBin-flow output")
    return bins


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--plasbin-output", required=True)
    ap.add_argument("--contigs", required=True)
    ap.add_argument("--out-fasta", required=True)
    ap.add_argument("--provenance")
    a = ap.parse_args(argv)
    try:
        with open(a.plasbin_output, "rb") as fh:
            sha = hashlib.sha256(fh.read()).hexdigest()
        bins = parse_bins(a.plasbin_output)
        seqs = read_fasta(a.contigs)
        missing = sorted({c for b in bins for c, _ in b["contigs"] if c not in seqs})
        if missing:
            raise ValueError(
                "contig id(s) in PlasBin-flow output absent from the assembly FASTA "
                "(different assembly?): %s" % ", ".join(missing))
    except (ValueError, OSError) as e:
        print("[plasbin_flow_adapter] ERROR: %s" % e, file=sys.stderr)
        return 1

    assigned = {}
    rows = []
    multi = {}
    n_mult = 0
    for b in bins:
        for cid, mult in b["contigs"]:
            if mult > 1:
                n_mult += 1
            if cid in assigned:
                lst = multi.setdefault(cid, [assigned[cid]])
                if b["id"] not in lst:
                    lst.append(b["id"])
                continue
            assigned[cid] = b["id"]
            rows.append((b["id"], cid))

    with open(a.out_fasta, "w", encoding="utf-8", newline="\n") as fh:
        for _, cid in rows:
            fh.write(">%s\n" % cid)
            s = seqs[cid]
            for i in range(0, len(s), 80):
                fh.write(s[i:i + 80] + "\n")
    stem = a.out_fasta[:-len(".plasmid.fasta")] if a.out_fasta.endswith(".plasmid.fasta") else a.out_fasta
    with open(stem + ".bins.tsv", "w", encoding="utf-8", newline="\n") as fh:
        fh.write("bin_id\tsequence_id\n")
        for bid, cid in rows:
            fh.write("%s\t%s\n" % (bid, cid))

    if a.provenance:
        prov = {
            "tool": "plasbin_flow",
            "plasbin_output_sha256": sha,
            "bin_count": len(bins),
            "contig_count": len(rows),
            "contigs_with_multiplicity_gt1": n_mult,
            "bins": [{"id": b["id"], "flow": b["flow"], "gc_bin": b["gc_bin"],
                      "n_contigs": len(b["contigs"])} for b in bins],
            "contigs_in_multiple_bins": multi,
        }
        with open(a.provenance, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(prov, fh, indent=2, sort_keys=True)
            fh.write("\n")
    print("[plasbin_flow_adapter] %d bins, %d contigs -> %s" % (len(bins), len(rows), a.out_fasta),
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
