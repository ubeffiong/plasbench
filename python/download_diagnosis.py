#!/usr/bin/env python3
"""Say, in plain words, why the SRA Toolkit's `prefetch` failed, from what it printed. Never guesses; promises no cure.

  python3 -I python/download_diagnosis.py LOGFILE [--format text|json]

`diagnose(text)` returns None when no rule matches, otherwise a dict: cause (a stable id), title, plain (what it means and what is used instead), check (what to look at), evidence
(the matching line). Rules are tried in order. Stage 1 prints the text ONCE per run (scripts/01_download.sh), then ENA is used.

The table is here and not in config/resource_signatures.tsv because that table maps memory and thread failures of assemblers to resource adjustments; a network failure of a
download client has no such adjustment, only an explanation. Standard library only; Python 3.9 compatible.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

RULES = [
    dict(cause="sra_tls_stream", title="the SRA Toolkit could not open a secure (TLS) connection to NCBI",
         patterns=[r"Failed to create TLS stream", r"connection failed while opening file within cryptographic module"],
         plain="The SRA Toolkit's prefetch could not open a TLS (secure HTTPS) connection to NCBI (www.ncbi.nlm.nih.gov). That is a problem of the toolkit's own network set-up on this "
               "computer, not of the isolate; ENA (a European mirror of the same sequencing runs) and the NCBI Datasets service are separate connections and can still work. "
               "PlasBench fetches the reads from ENA first anyway, checks them against ENA's checksums, and a prefetch that keeps failing is not retried on every isolate for the next 24 hours.",
         check="A proxy the toolkit does not know about (set HTTPS_PROXY, or `vdb-config --proxy host:port`); the system's CA certificates (on Ubuntu and WSL: `sudo apt install ca-certificates` "
               "then `sudo update-ca-certificates`); a VPN or firewall that inspects HTTPS; and `vdb-config -i` to look at the toolkit's own network settings. Running `prefetch SRR...` by hand "
               "shows the same message. A newer SRA Toolkit may behave differently; none of this is guaranteed to cure it."),
    dict(cause="sra_certificate", title="the SRA Toolkit does not trust the certificate NCBI presented",
         patterns=[r"certificate verify failed", r"unable to get local issuer certificate", r"self[- ]signed certificate"],
         plain="The SRA Toolkit refused the certificate it was shown when it connected to NCBI. This usually means a proxy or firewall that re-signs HTTPS traffic, or missing system CA "
               "certificates. PlasBench fetches the reads from ENA instead.",
         check="The system CA certificates (`ca-certificates`), a company or school proxy that needs its certificate installed, and the date and time of this computer."),
    dict(cause="sra_name_resolution", title="the SRA Toolkit could not look up NCBI's address",
         patterns=[r"[Cc]ould not resolve host", r"Name or service not known", r"[Tt]emporary failure in name resolution", r"cannot resolve"],
         plain="The SRA Toolkit could not turn NCBI's name into an address (a DNS failure). PlasBench fetches the reads from ENA instead; if ENA fails the same way, the internet connection "
               "or its name lookup is the problem.",
         check="`plasbench net` shows which services this computer can reach; check a VPN, a proxy or the DNS server."),
    dict(cause="sra_disk_full", title="the SRA Toolkit ran out of disk space",
         patterns=[r"No space left on device", r"disk quota exceeded", r"not enough (free )?(disk )?space"],
         plain="prefetch stopped because the disk it writes to is full. This is not a network problem.",
         check="Free space in the data folder (a run set needs about three times its compressed size while the SRA file is converted); `df -h` shows it."),
]


def diagnose(text):
    for rule in RULES:
        for pattern in rule["patterns"]:
            match = re.search(pattern, text or "")
            if match:
                line = next((ln.strip() for ln in text.splitlines() if re.search(pattern, ln)), match.group(0))
                return {"cause": rule["cause"], "title": rule["title"], "plain": rule["plain"], "check": rule["check"], "evidence": line[:300]}
    return None


def render(found):
    return f"{found['title'][0].upper() + found['title'][1:]}. {found['plain']} What to check: {found['check']}"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("logfile")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    args = ap.parse_args(argv)
    try:
        with open(args.logfile, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return 1
    found = diagnose(text)
    if not found:
        return 1
    print(json.dumps(found) if args.format == "json" else render(found))
    return 0


if __name__ == "__main__":
    sys.exit(main())
