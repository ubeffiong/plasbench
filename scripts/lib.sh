#!/usr/bin/env bash
# Shared helpers sourced by every stage script.

# Pretty logging with timestamps.
log()  { echo -e "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
warn() { echo -e "[$(date '+%Y-%m-%d %H:%M:%S')] WARNING: $*" >&2; }
die()  { echo -e "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2; exit 1; }

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
    ' "$sheet" || die "fix sample-sheet errors in $sheet"
}
