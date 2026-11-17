#!/usr/bin/env python3
"""Download checksum registry (audit AU-026): config/download_checksums.tsv and the mechanism that reads it.

  - the registry parses, labels are unique, a row marked pinned has a 64-hex sha256, and every label the installers pass to
    verify_or_record_download (and PLSDB) has a row;
  - verify_or_record_download takes the pin from the registry when no explicit pin is given: a wrong registry pin fails, a right one is
    recorded as verified, an explicit pin overrides the registry, a custom URL gets no registry pin;
  - PLASBENCH_REQUIRE_CHECKSUMS=1 refuses a download that has no pin at all;
  - the Dockerfile verifies the gplas2 archive when GPLAS2_SHA256 is given.
Only the gplas2 archive is pinned (fetched and hashed on 2026-11-17); every other row says status=unpinned because its file was over ~300 MB and was not fetched.
Needs bash (skipped when none is usable).
"""
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OK = True


def check(label, good, detail=""):
    global OK
    print(f"  {label}: {'PASS' if good else 'FAIL'}" + ("" if good else f"  [{detail}]"))
    OK &= bool(good)


registry = os.path.join(ROOT, "config", "download_checksums.tsv")
check("registry file exists", os.path.isfile(registry))
rows = list(csv.DictReader(open(registry, newline="", encoding="utf-8"), delimiter="\t")) if os.path.isfile(registry) else []
check("registry columns", rows and list(rows[0]) == ["label", "url", "sha256", "bytes", "status", "note"], str(list(rows[0]) if rows else ""))
labels = [r["label"] for r in rows]
check("labels are unique", len(labels) == len(set(labels)))
check("a pinned row has a 64-hex sha256, an unpinned row none",
      all((r["status"] == "pinned") == bool(re.fullmatch(r"[0-9a-fA-F]{64}", r["sha256"])) for r in rows) and all(r["status"] in ("pinned", "unpinned") for r in rows))
wanted = ["Platon database", "PlaScope E. coli database", "PlaScope Klebsiella database", "MOB-suite database", "PLSDB sequences", "gplas2 source tarball"]
check("every installer download has a row", all(w in labels for w in wanted), str([w for w in wanted if w not in labels]))
text = {n: open(os.path.join(ROOT, "env", n), encoding="utf-8").read() for n in ("download_platon_db.sh", "download_plsdb.sh")}
check("the PLSDB installer reads the registry", "download_pin" in text["download_plsdb.sh"] and "PLASBENCH_REQUIRE_CHECKSUMS" in text["download_plsdb.sh"])
docker = open(os.path.join(ROOT, "Dockerfile"), encoding="utf-8").read()
check("the Dockerfile verifies the gplas2 archive when GPLAS2_SHA256 is given", "ARG GPLAS2_SHA256" in docker and "sha256sum -c" in docker)

bash = next((b for b in (r"C:\Program Files\Git\bin\bash.exe", "/bin/bash", "/usr/bin/bash") if os.path.exists(b)), None) or shutil.which("bash")
if not bash or (os.name == "nt" and "system32" in bash.lower()):
    print("  SKIP: no usable bash for the checksum helper")
else:
    with tempfile.TemporaryDirectory() as tmp:
        f = os.path.join(tmp, "db.tar.gz")
        open(f, "wb").write(b"database")
        good = hashlib.sha256(b"database").hexdigest()
        prov = os.path.join(tmp, "prov.jsonl")
        lib = os.path.join(ROOT, "scripts", "lib.sh").replace("\\", "/")

        def reg(status, sha, url=""):
            path = os.path.join(tmp, "reg.tsv")
            with open(path, "w", newline="", encoding="utf-8") as h:
                h.write("label\turl\tsha256\tbytes\tstatus\tnote\n" + f"Test DB\t{url}\t{sha}\t\t{status}\tx\n")
            return path.replace("\\", "/")

        def sh(want="", registry_path=None, require="0", url="http://x/db"):
            env = dict(os.environ, PLASBENCH_REQUIRE_CHECKSUMS=require)
            if registry_path:
                env["PLASBENCH_DOWNLOAD_CHECKSUMS"] = registry_path
            return subprocess.run([bash, "-c", f'source "{lib}"; verify_or_record_download "{f.replace(chr(92), "/")}" {url} "Test DB" "{want}" "{prov.replace(chr(92), "/")}"'],
                                  capture_output=True, text=True, env=env)

        r = sh(registry_path=reg("pinned", "0" * 64))
        check("a wrong registry pin fails", r.returncode != 0 and "does not match" in r.stderr, r.stderr)
        r = sh(registry_path=reg("pinned", good))
        check("a right registry pin passes and is recorded as verified", r.returncode == 0 and json.loads(open(prov).read().splitlines()[-1])["sha256_verified"] is True, r.stderr)
        r = sh(want=good, registry_path=reg("pinned", "0" * 64))
        check("an explicit pin overrides the registry", r.returncode == 0, r.stderr)
        r = sh(registry_path=reg("pinned", "0" * 64, url="http://other/db"))
        check("a registry pin for another URL does not apply to a custom URL", r.returncode == 0 and "NOTICE" in r.stderr, r.stderr)
        r = sh(registry_path=reg("unpinned", ""))
        check("an unpinned row gives no pin (notice, success)", r.returncode == 0 and "NOTICE" in r.stderr, r.stderr)
        r = sh(registry_path=reg("unpinned", ""), require="1")
        check("PLASBENCH_REQUIRE_CHECKSUMS=1 refuses a download with no pin", r.returncode != 0 and "refusing" in r.stderr, r.stderr)
        r = sh(want=good, registry_path=reg("unpinned", ""), require="1")
        check("PLASBENCH_REQUIRE_CHECKSUMS=1 accepts an explicit pin", r.returncode == 0, r.stderr)

print("ALL DOWNLOAD CHECKSUM REGISTRY TESTS PASSED" if OK else "DOWNLOAD CHECKSUM REGISTRY TESTS FAILED")
sys.exit(0 if OK else 1)
