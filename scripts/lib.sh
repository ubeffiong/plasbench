#!/usr/bin/env bash
# Shared helpers sourced by every stage script.

# Pretty logging with timestamps.
log()  { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
warn() { printf '[%s] WARNING: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2; }
die()  { printf '[%s] ERROR: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2; exit 1; }

# Check a command exists; die if not.
need() {
    command -v "$1" >/dev/null 2>&1 || die "required command '$1' not found in PATH. Did you activate the conda env?"
}

# Check a command exists; warn + return 1 if not (for optional tools).
have() { command -v "$1" >/dev/null 2>&1; }

# Iterate real rows of the sample sheet (skip blank lines, comments, header).
# Prints: sample_id <TAB> assembly_accession <TAB> sra_run
read_samples() {
    local sheet="$1"
    # skip header (first non-comment line), comments, blanks
    awk -F'\t' '
        /^[[:space:]]*#/ {next}
        /^[[:space:]]*$/ {next}
        {
            if (!seen_header) { seen_header=1; next }  # drop header row
            print $1"\t"$2"\t"$3
        }
    ' "$sheet"
}

# Fail before expensive stages when the template sheet has not been populated,
# or when identifiers would collide in the per-sample output directories.
validate_sample_sheet() {
    local sheet="$1"
    [[ -f "$sheet" ]] || die "sample sheet not found: $sheet"
    awk -F'\t' '
        /^[[:space:]]*#/ {next}
        /^[[:space:]]*$/ {next}
        !seen_header {seen_header=1; next}
        NF < 3 || $1 == "" || $2 == "" || $3 == "" {
            print "ERROR: invalid sample-sheet row " NR "; expected sample_id, assembly_accession, sra_run" > "/dev/stderr"
            bad=1; next
        }
        curated && (NF < 8 || $4 == "" || $5 == "" || $6 !~ /^[ABC]$/ || $7 == "" || $8 == "") {
            print "ERROR: uncurated sample-sheet row " NR "; require organism, truth_technology, truth_quality_tier (A/B/C), biosample, bioproject" > "/dev/stderr"
            bad=1; next
        }
        seen_sample[$1]++ {
            print "ERROR: duplicate sample_id '" $1 "' in sample sheet" > "/dev/stderr"
            bad=1; next
        }
        {count++}
        END {
            if (bad) exit 2
            if (count == 0) {
                print "ERROR: sample sheet has no data rows; add samples to config/accessions.tsv" > "/dev/stderr"
                exit 3
            }
        }
    ' curated="${REQUIRE_CURATED_METADATA:-1}" "$sheet" || die "fix sample-sheet errors in $sheet"
}
