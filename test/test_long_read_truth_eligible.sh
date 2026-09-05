#!/usr/bin/env bash
# Direct unit test for scripts/lib.sh's long_read_truth_eligible(), the
# generic circularity-guard function shared by every long-read/hybrid tool.
# Tested here in isolation (sourced, not through a full stage script) so its
# three-state logic (registry-not-applicable / declared-independent /
# override / circular) is verified directly against the function itself.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

source "$ROOT/config/config.sh"
source "$ROOT/scripts/lib.sh"

printf 'sample_id\tassembly_accession\tsra_run\ttruth_technology\ttruth_independent_of_long_reads\n' > "$TMP/sheet.tsv"
printf 's1\tGCF_1\tSRR1\tlong_read\t\n' >> "$TMP/sheet.tsv"
printf 's2\tGCF_2\tSRR2\thybrid\tyes\n' >> "$TMP/sheet.tsv"
SAMPLE_SHEET="$TMP/sheet.tsv"

# A tool the registry does not require this for is always eligible,
# regardless of the sample sheet.
reason="$(long_read_truth_eligible mob_recon s1)"
[[ "$reason" == "not-applicable" ]] || { echo "FAIL: mob_recon should be not-applicable, got: $reason" >&2; exit 1; }
echo "a tool with requires_independent_long_read_truth=no is always eligible -> PASS"

# A registry-gated tool, no declaration, no override: ineligible, reason is
# the sample's truth_technology.
if reason="$(long_read_truth_eligible flye_mob_recon s1)"; then
    echo "FAIL: s1 should be ineligible for flye_mob_recon" >&2; exit 1
fi
[[ "$reason" == "long_read" ]] || { echo "FAIL: expected reason=long_read, got: $reason" >&2; exit 1; }
echo "no declaration, no override -> ineligible, reason is the sample's truth_technology -> PASS"

# An explicit declaration makes it eligible.
reason="$(long_read_truth_eligible flye_mob_recon s2)"
[[ "$reason" == "independent" ]] || { echo "FAIL: s2 should be eligible (declared independent), got: $reason" >&2; exit 1; }
echo "truth_independent_of_long_reads=yes -> eligible ('independent') -> PASS"

# The per-tool override, via bash indirect expansion, makes an otherwise
# ineligible sample eligible -- and only for that tool's own variable name.
reason="$(FLYE_MOB_RECON_ALLOW_CIRCULAR_TRUTH=1 bash -c "source '$ROOT/config/config.sh'; source '$ROOT/scripts/lib.sh'; SAMPLE_SHEET='$TMP/sheet.tsv' long_read_truth_eligible flye_mob_recon s1")"
[[ "$reason" == "override" ]] || { echo "FAIL: expected override, got: $reason" >&2; exit 1; }
if reason="$(PLASSEMBLER_ALLOW_CIRCULAR_TRUTH=1 bash -c "source '$ROOT/config/config.sh'; source '$ROOT/scripts/lib.sh'; SAMPLE_SHEET='$TMP/sheet.tsv' long_read_truth_eligible flye_mob_recon s1")"; then
    echo "FAIL: PLASSEMBLER's override must not affect flye_mob_recon's eligibility" >&2; exit 1
fi
echo "the per-tool override variable (bash indirect expansion) works, and only for its own tool -> PASS"

echo "ALL LONG_READ_TRUTH_ELIGIBLE TESTS PASSED"
