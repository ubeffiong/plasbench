#!/usr/bin/env bash
# OPT-IN, benchmark-only download of a PLSDB plasmid FASTA into
# $DATA_DIR/db/plsdb/sequences.fasta.
#
# PLSDB is used here ONLY as (a) a tool's own database for the leakage screen
# (TOOL_DATABASE_FASTAS) and (b) a reference for the trivial reference baseline
# (PLASMID_REFERENCE_FASTA). It is never a search feature and never a truth source.
#
# No URL is trusted by default: you must supply PLSDB_URL. For example, the
# plsMD Dockerfile uses
#     https://ccb-microbe.cs.uni-saarland.de/plsdb2025/download_fasta
# (an example only; it was NOT verified here -- confirm the release and licence).
#
#     PLSDB_URL=<url> [PLSDB_SHA256=<sha256>] bash env/download_plsdb.sh
#
# Pin PLSDB_SHA256 so a truncated, stale or tampered download is detected.
# Writes sequences.fasta and sequences.provenance.json (url, utc date, sha256,
# bytes, record count). Tests never download.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../config/config.sh"
source "$HERE/../scripts/lib.sh"

[[ -n "${PLSDB_URL:-}" ]] || die "PLSDB_URL is required (no default is trusted). See the header of env/download_plsdb.sh."

DEST_DIR="$DATA_DIR/db/plsdb"
DEST="$DEST_DIR/sequences.fasta"
PROV="$DEST_DIR/sequences.provenance.json"
mkdir -p "$DEST_DIR"

if [[ -s "$DEST" ]]; then
    echo "[plsdb] already present at $DEST -- nothing to do (delete it to re-download)."
    exit 0
fi

TMP="$DEST.part"
rm -f "$TMP"
echo "[plsdb] downloading from $PLSDB_URL ..."
if command -v wget >/dev/null 2>&1; then
    wget -O "$TMP" "$PLSDB_URL"
else
    curl -fL -o "$TMP" "$PLSDB_URL"
fi

case "$PLSDB_URL" in
    *.gz) mv "$TMP" "$TMP.gz"; gunzip -f "$TMP.gz" ;;
esac
[[ -s "$TMP" ]] || die "download is empty"

SHA="$(sha256sum "$TMP" | awk '{print $1}')"
if [[ -n "${PLSDB_SHA256:-}" ]]; then
    if [[ "$SHA" != "${PLSDB_SHA256,,}" ]]; then
        rm -f "$TMP"
        die "downloaded file sha256 $SHA did not match PLSDB_SHA256; refusing to use it"
    fi
else
    warn "PLSDB_SHA256 not set; recording the observed checksum ($SHA) without verifying it"
fi

head -c 1 "$TMP" | grep -q '>' || { rm -f "$TMP"; die "download is not FASTA (does not start with '>')"; }
RECORDS="$(grep -c '^>' "$TMP" || true)"
BYTES="$(wc -c < "$TMP" | tr -d ' ')"
mv "$TMP" "$DEST"

printf '{\n  "url": "%s",\n  "downloaded_utc": "%s",\n  "sha256": "%s",\n  "bytes": %s,\n  "records": %s,\n  "sha256_verified": %s\n}\n' \
    "$PLSDB_URL" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$SHA" "$BYTES" "$RECORDS" \
    "$([[ -n "${PLSDB_SHA256:-}" ]] && echo true || echo false)" > "$PROV"

echo "[plsdb] $RECORDS records, $BYTES bytes -> $DEST"
echo "[plsdb] provenance: $PROV"
echo
echo "Use it (benchmark-only):"
echo "    TOOL_DATABASE_FASTAS=\"plsmd=$DEST\"          # leakage screen: plsMD's own database"
echo "    PLASMID_REFERENCE_FASTA=\"$DEST\"             # optional: reference for baseline_reference"
echo "PLSDB is used only as a tool's database for the leakage screen and as a reference for"
echo "the trivial baseline, never as a search feature."
