#!/usr/bin/env python3
"""
fetch_ena_reads.py -- download a paired-end run's FASTQ from ENA, the European
mirror of the same INSDC record (stage 1: the first choice for READ_SOURCE=auto,
and the fallback when the SRA Toolkit cannot connect).

The run accession (SRR/ERR/DRR) is looked up in the ENA portal file report; the
two published FASTQ files are fetched over HTTPS and each is checked against the
MD5 that ENA publishes for it. A run that is not PAIRED, has no FASTQ, or fails
the checksum is an error; nothing partial is ever left under the final names.

Writes <out-dir>/<run>_1.fastq.gz and <run>_2.fastq.gz, and a provenance JSON
(<out-dir>/<run>.ena_provenance.json) with the URLs, sizes, MD5s and transfer figures.
Standard library only.

How it downloads (python/ena_download.py has the details): fixed-size chunks (ENA_CHUNK_MIB,
default 32) fetched with HTTP Range by a bounded worker pool, each retried on its own, the
finished chunks recorded in <file>.part.state so a later attempt or a later run resumes
instead of starting again. The total number of connections is one budget (ENA_MAX_CONNECTIONS,
default 16, never above 24) shared by the two mates; ENA_DOWNLOAD_CONNECTIONS caps each file.
When the data folder is on a slow mount (a Windows drive seen from WSL, a network share) the
.part files and the MD5 check live in a local scratch folder (DOWNLOAD_TMP_DIR, python/download_scratch.py)
and the verified file is moved into place. aria2c is used only when ENA_USE_ARIA2=1.
Progress is bytes actually received, printed every ENA_PROGRESS_SECONDS (default 30) and written
to --progress-file (results/download_progress.json).
"""

import argparse
import json
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ena_download  # noqa: E402
import download_scratch  # noqa: E402
import depth_cap  # noqa: E402
from plasbench_common import net_explain, net_require  # noqa: E402

RETRY_DELAY_SECONDS = float(os.environ.get("ENA_RETRY_DELAY_SECONDS", "15") or 15)   # wait before attempt n+1 is n times this (15 s, 30 s, ...); tests set 0
SEGMENT_MIN_BYTES = int(os.environ.get("ENA_SEGMENT_MIN_BYTES", str(16 << 20)) or (16 << 20))   # below this a file is read as one stream

# ENA_PORTAL_URL points the file-report lookup at a mirror (or, in the tests, at a local fake server). The default is ENA itself.
PORTAL = os.environ.get("ENA_PORTAL_URL") or "https://www.ebi.ac.uk/ena/portal/api/filereport"
FIELDS = "run_accession,fastq_ftp,fastq_md5,fastq_bytes,library_layout,read_count,base_count,instrument_platform"


def file_report(run, timeout=60):
    query = urllib.parse.urlencode({"accession": run, "result": "read_run", "fields": FIELDS, "format": "tsv"})
    with urllib.request.urlopen(f"{PORTAL}?{query}", timeout=timeout) as response:
        lines = response.read().decode("utf-8").strip().splitlines()
    if len(lines) < 2:
        raise ValueError(f"ENA has no read_run record for {run}")
    header, values = lines[0].split("\t"), lines[1].split("\t")
    return dict(zip(header, values))


def download(url, path, expected_md5, expected_bytes=None, budget=None, progress=None, scratch_dir=None, retries=5):
    """Fetch url to `path` (the final name), MD5-verified, through a `.part` file in `scratch_dir` (default: next to `path`); the verified file is then moved into place."""
    budget = budget or ena_download.Budget(memo_path=os.environ.get("ENA_BUDGET_FILE") or None)
    name = os.path.basename(path)
    progress = progress or ena_download.Progress(name)
    tmp = os.path.join(scratch_dir or os.path.dirname(os.path.abspath(path)), name + ".part")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    ena_download.fetch(url, tmp, expected_md5, expected_bytes, budget, progress, name, min_bytes=SEGMENT_MIN_BYTES, attempts=retries, retry_delay=RETRY_DELAY_SECONDS)
    progress.set_state(name, "moving")
    how = download_scratch.move_into_place(tmp, path, expected_bytes)
    progress.set_state(name, "done")
    if how == "copied":
        ena_download.log(f"{name}: moved from the scratch folder into {os.path.dirname(os.path.abspath(path))}")


def make_plan(args, report, pairs):
    """The read-depth cap plan (python/depth_cap.py) for this run: reference size from --ref-bases or --reference, cap from --depth-cap / READ_DEPTH_CAP_X."""
    sizes = [str(b) for _, _, b in pairs]
    ref = int(args.ref_bases or 0) or (depth_cap.reference_bases(args.reference) if args.reference else 0)
    cap_x = depth_cap.parse_cap(args.depth_cap)
    if not all(x.strip().isdigit() for x in sizes):
        return {"capped": False, "cap_x": cap_x, "ref_bases": ref, "full_bytes": 0, "reason": "ENA reports no file sizes: whole files"}
    return depth_cap.plan(cap_x, ref, report, [int(x) for x in sizes])


def capped_record(dplan, files):
    """What the provenance JSON (and through it the run manifest and report) says about the cap, applied or not."""
    record = {"applied": bool(dplan.get("capped")), "cap_x": dplan.get("cap_x"), "reason": dplan.get("reason", ""), "reference_bases": dplan.get("ref_bases", 0)}
    if dplan.get("capped"):
        record.update(
            target_pairs=dplan["target_pairs"], read_pairs_available=dplan["read_count"], depth_available=round(dplan["depth"], 1), estimated_depth=round(dplan["est_depth"], 1),
            bytes_available=dplan["full_bytes"], bytes_fetched=sum(f["bytes_fetched"] for f in files), source_urls=[f["url"] for f in files],
            method="prefix of each file (the first read pairs, in sequencer output order; not a random sample), cut at a complete 4-line record, recompressed (gzip -n style)",
            integrity="prefix of the file, whole-file md5 not checked. Checked instead: 4-line records with equal sequence and quality lengths, equal pair counts in both mates, "
                      "first and last read names pair up, the deflate stream decodes without error",
            scoring_note=f"read depth was capped to about {dplan['est_depth']:.0f}x (cap {dplan['cap_x']:g}x); truth and scoring do not use read depth")
    return record


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True, help="SRR/ERR/DRR run accession")
    ap.add_argument("--out-dir", help="where to write the FASTQ files (required unless --size-only)")
    ap.add_argument("--size-only", action="store_true",
                    help="download nothing: print the run's total FASTQ bytes from ENA, then each file's bytes, tab-separated, on one line. "
                         "Exit 3 when ENA cannot be reached or reports no sizes (the download stage then goes ahead without a size check).")
    ap.add_argument("--progress-file", default=os.environ.get("DOWNLOAD_PROGRESS_FILE", ""), help="merge this run's progress into this JSON file (results/download_progress.json)")
    ap.add_argument("--reference", default="", help="the isolate's reference.fna: its size sets the read-depth cap (READ_DEPTH_CAP_X)")
    ap.add_argument("--ref-bases", type=int, default=0, help="the reference's total bases, when already known")
    ap.add_argument("--depth-cap", default=os.environ.get("READ_DEPTH_CAP_X", ""), help="read-depth cap in x (default 150; 0 or off = whole files)")
    ap.add_argument("--plan", action="store_true", help="download nothing: print capped_bytes, full_bytes, capped (0/1) and a plain line, tab-separated (exit 3 when ENA cannot be asked)")
    ap.add_argument("--study", default=os.environ.get("PLASBENCH_STUDY", ""), help="the study's name (the scratch folder is ~/.plasbench/downloads/<study>)")
    ap.add_argument("--sample", default="", help="the sample the run belongs to (shown in the progress file)")
    args = ap.parse_args()
    lookup = args.size_only or args.plan
    if not lookup and not args.out_dir:
        ap.error("--out-dir is required unless --size-only is given")
    if not os.environ.get("ENA_PORTAL_URL"):       # a mirror or a local test server is not "the internet"
        net_require(["ena"], action=f"Looking up {args.run} at ENA" if lookup else f"Downloading {args.run} from ENA",
                    code=3 if lookup else 1, probe=False)
    try:
        # A size lookup is only advice for the download stage, so it must not hold a run up: a short timeout (ENA_SIZE_TIMEOUT, seconds).
        report = file_report(args.run, timeout=max(1, int(os.environ.get("ENA_SIZE_TIMEOUT", "20") or 20))) if lookup else file_report(args.run)
    except (OSError, ValueError) as exc:
        if lookup:
            sys.stderr.write(f"[fetch_ena_reads] size lookup failed for {args.run}: {net_explain(exc, 'ena', 'The ENA size lookup')}" + chr(10))
            raise SystemExit(3)
        raise SystemExit(f"ERROR: ENA lookup failed for {args.run}: {net_explain(exc, 'ena', 'The ENA lookup')}")
    if lookup:
        sizes = [x for x in (report.get("fastq_bytes") or "").split(";") if x.strip()]
        if not sizes or not all(x.strip().isdigit() for x in sizes):
            sys.stderr.write(f"[fetch_ena_reads] ENA reports no FASTQ sizes for {args.run}" + chr(10))
            raise SystemExit(3)
        if args.plan:
            urls_ = [u for u in (report.get("fastq_ftp") or "").split(";") if u]
            pairs_ = sorted((u, "", b) for u, b in zip(urls_, sizes) if u.endswith("_1.fastq.gz") or u.endswith("_2.fastq.gz"))
            if report.get("library_layout") != "PAIRED" or len(pairs_) != 2:
                print(chr(9).join([str(sum(int(x) for x in sizes)), str(sum(int(x) for x in sizes)), "0", f"{args.run}: ENA has no usable paired FASTQ"]))
                return
            dp = make_plan(args, report, pairs_)
            print(chr(9).join([str(dp["fetch_bytes"] if dp.get("capped") else dp["full_bytes"]), str(dp["full_bytes"]), "1" if dp.get("capped") else "0", depth_cap.describe(args.run, dp)]))
            return
        print(chr(9).join([str(sum(int(x) for x in sizes))] + [x.strip() for x in sizes]))
        return
    urls = [u for u in (report.get("fastq_ftp") or "").split(";") if u]
    md5s = (report.get("fastq_md5") or "").split(";")
    sizes = (report.get("fastq_bytes") or "").split(";")
    pairs = [(u, m, b) for u, m, b in zip(urls, md5s, sizes + [""] * len(urls))
             if u.endswith("_1.fastq.gz") or u.endswith("_2.fastq.gz")]
    if report.get("library_layout") != "PAIRED" or len(pairs) != 2:
        sys.stderr.write(f"ERROR: {args.run} is not a paired run with _1/_2 FASTQ in ENA (layout {report.get('library_layout')}, files {len(urls)})" + chr(10))
        raise SystemExit(4)    # 4 = ENA has no usable paired FASTQ for this run (stage 1 then uses the SRA Toolkit)
    os.makedirs(args.out_dir, exist_ok=True)
    pairs = sorted(pairs)
    dplan = make_plan(args, report, pairs)
    total_bytes = dplan["fetch_bytes"] if dplan.get("capped") else sum(int(b) for _, _, b in pairs if str(b).isdigit())
    ena_download.log(depth_cap.describe(args.run, dplan))
    # Where the .part files and the MD5 check live: a fast local folder when the data folder is on a slow mount (DOWNLOAD_TMP_DIR).
    place = download_scratch.resolve(os.environ.get("DOWNLOAD_TMP_DIR", "auto"), args.out_dir, args.study, total_bytes)
    scratch_dir = place["dir"] if place["scratch"] else args.out_dir
    ena_download.log(f"{args.run}: {place['reason']}" if place["reason"] else f"{args.run}: downloading into {scratch_dir}")
    if place["scratch"]:
        os.makedirs(scratch_dir, exist_ok=True)

    budget = ena_download.Budget(memo_path=os.environ.get("ENA_BUDGET_FILE") or None)
    if os.environ.get("ENA_BUDGET_SHARE"):          # this process is one of several parallel downloads: it gets its share of the total budget
        budget.limit = max(1, min(budget.limit, int(os.environ["ENA_BUDGET_SHARE"])))
    progress = ena_download.Progress(args.run)
    ena_download.log(f"{args.run}: {len(pairs)} files, {ena_download.human_bytes(total_bytes)}, at most {budget.limit} connections in total"
                     + (f" ({ena_download.settings()['per_file']} per file)" if ena_download.settings()["per_file"] else ""))
    started = time.time()
    interval = max(1.0, float(os.environ.get("ENA_PROGRESS_SECONDS", "30") or 30))
    json_every = min(5.0, interval)
    stop = threading.Event()

    def publish(force_line=False):
        snap = progress.snapshot()
        ena_download.write_progress_file(args.progress_file, args.run, snap, progress.line(snap), args.sample)
        return snap

    def reporter():
        last_line = 0.0
        while not stop.wait(json_every):
            snap = publish()
            if time.time() - last_line >= interval and snap["total_bytes"]:
                last_line = time.time()
                sys.stderr.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {progress.line(snap)}" + chr(10))
                sys.stderr.flush()

    thread = threading.Thread(target=reporter, daemon=True)
    thread.start()
    provenance = {"run": args.run, "source": "ENA", "files": []}

    def fetch_mate(entry):
        url, md5, size = entry
        mate = "1" if url.endswith("_1.fastq.gz") else "2"
        path = os.path.join(args.out_dir, f"{args.run}_{mate}.fastq.gz")
        download("https://" + url if not url.startswith("http") else url, path, md5, size, budget=budget, progress=progress, scratch_dir=scratch_dir)
        sys.stderr.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [fetch_ena_reads] {args.run}_{mate}.fastq.gz verified (md5 {md5})" + chr(10))
        return {"url": url, "md5": md5, "bytes": size, "path": os.path.basename(path)}

    def fetch_mate_capped(index):
        """The first target_pairs reads of one mate: fetch a prefix, cut it at a record boundary, recompress to a .cap.part file (not yet under its final name)."""
        url, md5, size = pairs[index]
        url = "https://" + url if not url.startswith("http") else url
        mate = "1" if url.endswith("_1.fastq.gz") else "2"
        name = f"{args.run}_{mate}.fastq.gz"
        prefix_tmp, cap_tmp = os.path.join(scratch_dir, name + ".prefix.part"), os.path.join(scratch_dir, name + ".cap.part")
        length = dplan["prefix_bytes"][index]
        size = int(size)
        while True:
            ena_download.fetch(url, prefix_tmp, md5, size, budget, progress, name, attempts=5, retry_delay=RETRY_DELAY_SECONDS, prefix_bytes=length)
            try:
                info = depth_cap.cut_prefix(prefix_tmp, cap_tmp, dplan["target_pairs"])
                break
            except depth_cap.NeedMore as exc:
                if length >= size:
                    raise ValueError(f"{name}: the whole file holds fewer than {dplan['target_pairs']} reads ({exc.records}); ENA's read count does not match the file")
                longer = min(size, int(length * 1.3) + (1 << 20))
                ena_download.log(f"{name}: the first {ena_download.human_bytes(length)} hold {exc.records} of the {dplan['target_pairs']} reads needed; fetching a longer prefix ({ena_download.human_bytes(longer)})")
                length = longer
        info.update(url=url, name=name, remote_md5=md5, prefix_bytes=length, remote_bytes=size, prefix_tmp=prefix_tmp, cap_tmp=cap_tmp)
        ena_download.log(f"{name}: kept the first {info['records']} read pairs ({ena_download.human_bytes(os.path.getsize(cap_tmp))} compressed) from a {ena_download.human_bytes(length)} prefix")
        return info

    def finish_capped(infos):
        depth_cap.check_pair(infos[0], infos[1], dplan["target_pairs"])
        for info in infos:
            progress.set_state(info["name"], "moving")
            download_scratch.move_into_place(info["cap_tmp"], os.path.join(args.out_dir, info["name"]))
            for extra in (info["prefix_tmp"], info["prefix_tmp"] + ".state"):
                try:
                    os.remove(extra)
                except OSError:
                    pass
            progress.set_state(info["name"], "done")
        return [{"url": i["url"], "remote_md5": i["remote_md5"], "remote_bytes": i["remote_bytes"], "bytes_fetched": i["prefix_bytes"], "records": i["records"],
                 "first_read": i["first_name"], "last_read": i["last_name"], "path": i["name"], "prefix": True} for i in infos]

    # Both files go at once and share the budget; the first failure is raised after the other transfer finishes or fails.
    ok = False
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            if dplan.get("capped"):
                provenance["files"] = finish_capped(list(pool.map(fetch_mate_capped, range(len(pairs)))))
            else:
                provenance["files"] = list(pool.map(fetch_mate, pairs))
        provenance["read_depth_cap"] = capped_record(dplan, provenance["files"])
        ok = True
    finally:
        stop.set()
        thread.join(2)
        snap = progress.snapshot()
        if not ok:
            snap["state"] = "failed"
        ena_download.write_progress_file(args.progress_file, args.run, snap, progress.line(snap) if ok else progress.line(snap) + " (failed: the finished chunks are kept for the next attempt)", args.sample)
    seconds = time.time() - started
    provenance["transfer"] = {"seconds": round(seconds, 1), "bytes_received": progress.received, "retries": progress.retries, "resumed_bytes": progress.resumed_bytes,
                              "peak_connections": budget.peak, "connection_budget": budget.limit}
    sys.stderr.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {args.run}: done, {ena_download.human_bytes(progress.received)} received in {ena_download.human_duration(seconds)} "
                     f"({progress.received / max(seconds, 1e-6) / 1e6:.1f} MB/s), {progress.retries} chunk retries, {ena_download.human_bytes(progress.resumed_bytes)} resumed from an earlier attempt" + chr(10))
    with open(os.path.join(args.out_dir, f"{args.run}.ena_provenance.json"), "w", encoding="utf-8") as handle:
        json.dump(provenance, handle, indent=2)


if __name__ == "__main__":
    main()
