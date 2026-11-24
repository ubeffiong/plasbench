#!/usr/bin/env python3
"""A tiny fake ENA for the download-stage tests (test/test_download_gate_and_prefetch.sh): the portal file report and the FASTQ files, over plain HTTP.

  python ena_fake_server.py PORT_FILE [DELAY_SECONDS]

Writes the port it listens on to PORT_FILE and serves until killed. Runs named SRR1..SRR9 return a small paired read set (each file is a few hundred bytes, the MD5
and size in the report are true). A run named SRRBIG reports 12 GB per file without serving anything, to exercise the size gate. DELAY_SECONDS holds each FASTQ
response back, so a download lasts long enough for the progress lines. Runs named SRRNOFQ* have no FASTQ in ENA (empty file report: the SRA Toolkit is the only way);
runs named SRRFAIL* list files whose download always answers 500 (ENA fails after its retries).
"""
import hashlib
import http.server
import sys
import threading
import time
import urllib.parse

DELAY = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0


def content(run, mate):
    return (f"@{run}_{mate}\nACGTACGTAC\n+\nIIIIIIIIII\n" * 40).encode()


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.endswith("/filereport"):
            run = urllib.parse.parse_qs(parsed.query).get("accession", [""])[0]
            host = f"127.0.0.1:{self.server.server_address[1]}"
            if run.startswith("SRRNOFQ"):
                body = ("run_accession\tfastq_ftp\tfastq_md5\tfastq_bytes\tlibrary_layout\n"
                        f"{run}\t\t\t\tPAIRED\n")
            elif run == "SRRBIG":
                big = 12_000_000_000
                body = ("run_accession\tfastq_ftp\tfastq_md5\tfastq_bytes\tlibrary_layout\n"
                        f"{run}\t{host}/f/{run}_1.fastq.gz;{host}/f/{run}_2.fastq.gz\t{'0' * 32};{'0' * 32}\t{big};{big}\tPAIRED\n")
            else:
                d1, d2 = content(run, 1), content(run, 2)
                body = ("run_accession\tfastq_ftp\tfastq_md5\tfastq_bytes\tlibrary_layout\n"
                        f"{run}\thttp://{host}/f/{run}_1.fastq.gz;http://{host}/f/{run}_2.fastq.gz\t"
                        f"{hashlib.md5(d1).hexdigest()};{hashlib.md5(d2).hexdigest()}\t{len(d1)};{len(d2)}\tPAIRED\n")
            data = body.encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if "/f/" in parsed.path:
            name = parsed.path.rsplit("/", 1)[1]
            run, mate = name.split("_")[0], name.split("_")[1][0]
            if run.startswith("SRRFAIL"):
                self.send_response(500)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            data = content(run, mate)
            time.sleep(DELAY)
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_response(404)
        self.end_headers()


def main():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    with open(sys.argv[1], "w", encoding="utf-8") as handle:
        handle.write(str(server.server_address[1]))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
