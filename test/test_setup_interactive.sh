#!/usr/bin/env bash
# Regression for scripts/00_setup.sh's interactive dependency check: it must
# still just pass cleanly when everything is present, must correctly detect
# and offer to fix each class of gap (a missing conda-family manager, a
# missing tool that an install-tools profile provides -- including gplas,
# needed only for the optional gplas2_mob/gplas2_external modes -- a missing
# database), must never prompt when nothing is fixable, and must never
# auto-proceed without consent. Runs fully offline with fake tool binaries on
# PATH; the REAL env/*.sh orchestration scripts run unmodified so this also
# exercises their real argument-passing.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin_full" "$TMP/bin_partial" "$TMP/data/db/platon/db" "$TMP/results" "$TMP/logs" "$TMP/tmp"
touch "$TMP/data/db/platon/db/marker"

for t in datasets prefetch fasterq-dump fastp minimap2 conda spades.py plasmidspades.py mob_recon platon; do
    printf '#!/usr/bin/env bash\ntrue\n' > "$TMP/bin_full/$t"; chmod +x "$TMP/bin_full/$t"
done
for t in datasets prefetch fasterq-dump fastp minimap2 conda spades.py plasmidspades.py; do
    printf '#!/usr/bin/env bash\ntrue\n' > "$TMP/bin_partial/$t"; chmod +x "$TMP/bin_partial/$t"
done
# Fake conda logs what install_tools.sh actually asks it to install, so the
# chain 00_setup.sh -> install_tools.sh -> conda can be verified end to end.
cat > "$TMP/bin_partial/conda" <<EOF
#!/usr/bin/env bash
echo "conda \$*" >> "$TMP/conda_calls.log"
true
EOF
chmod +x "$TMP/bin_partial/conda"

run_setup() {
    PATH="$1:$PATH" DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
        bash "$ROOT/scripts/00_setup.sh" "${@:2}" > "$TMP/run.log" 2>&1
}

# --- everything present: pass cleanly, no prompt, exit 0. ---
if run_setup "$TMP/bin_full"; then :; else echo "FAIL: fully-present run should pass" >&2; cat "$TMP/run.log" >&2; exit 1; fi
grep -q "Core dependency check PASSED" "$TMP/run.log" || { echo "FAIL: expected a PASSED message" >&2; cat "$TMP/run.log" >&2; exit 1; }
echo "everything present passes cleanly with no prompt -> PASS"

# --- missing mob_recon/platon, conda present, --yes: offers and actually
# invokes install-tools reconstruction, which actually invokes conda. ---
: > "$TMP/conda_calls.log"
if run_setup "$TMP/bin_partial" --yes; then
    echo "FAIL: this run should exit non-zero (a freshly-attempted install is never a passing check)" >&2
    cat "$TMP/run.log" >&2; exit 1
fi
grep -q "install-tools profile: reconstruction" "$TMP/run.log" || { echo "FAIL: reconstruction profile not offered" >&2; cat "$TMP/run.log" >&2; exit 1; }
grep -q "mob_suite" "$TMP/conda_calls.log" && grep -q "platon" "$TMP/conda_calls.log" || {
    echo "FAIL: install_tools.sh did not actually ask conda to install mob_suite/platon" >&2; cat "$TMP/conda_calls.log" >&2; exit 1; }
echo "missing reconstruction tools + --yes triggers install-tools -> conda end to end -> PASS"

# --- same gap, declining consent: must not touch conda at all. ---
: > "$TMP/conda_calls.log"
if PATH="$TMP/bin_partial:$PATH" DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
    bash "$ROOT/scripts/00_setup.sh" < /dev/null > "$TMP/run.log" 2>&1; then
    echo "FAIL: declining should exit non-zero" >&2; cat "$TMP/run.log" >&2; exit 1
fi
[[ ! -s "$TMP/conda_calls.log" ]] || { echo "FAIL: declining must never invoke conda" >&2; cat "$TMP/conda_calls.log" >&2; exit 1; }
grep -q "Skipped" "$TMP/run.log" || { echo "FAIL: expected a Skipped message" >&2; cat "$TMP/run.log" >&2; exit 1; }
echo "declining consent never touches conda -> PASS"

# --- missing gplas (needed only when a gplas2_* mode is enabled), conda
# present, --yes: offers and actually invokes install-tools gplas, which
# actually invokes conda. gplas is otherwise not needed, so bin_full (which
# lacks it) plus a logging conda is enough to isolate this one gap. ---
mkdir -p "$TMP/bin_gplas"
for t in datasets prefetch fasterq-dump fastp minimap2 spades.py plasmidspades.py mob_recon platon; do
    printf '#!/usr/bin/env bash\ntrue\n' > "$TMP/bin_gplas/$t"; chmod +x "$TMP/bin_gplas/$t"
done
cat > "$TMP/bin_gplas/conda" <<EOF
#!/usr/bin/env bash
echo "conda \$*" >> "$TMP/conda_calls.log"
true
EOF
chmod +x "$TMP/bin_gplas/conda"

: > "$TMP/conda_calls.log"
if PATH="$TMP/bin_gplas:$PATH" DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
    RUN_GPLAS2_MOB=1 bash "$ROOT/scripts/00_setup.sh" --yes > "$TMP/run.log" 2>&1; then
    echo "FAIL: this run should exit non-zero (a freshly-attempted install is never a passing check)" >&2
    cat "$TMP/run.log" >&2; exit 1
fi
grep -q "install-tools profile: gplas" "$TMP/run.log" || { echo "FAIL: gplas profile not offered" >&2; cat "$TMP/run.log" >&2; exit 1; }
grep -q "gplas" "$TMP/conda_calls.log" || { echo "FAIL: install_tools.sh did not actually ask conda to install gplas" >&2; cat "$TMP/conda_calls.log" >&2; exit 1; }
echo "missing gplas (RUN_GPLAS2_MOB=1) + --yes triggers install-tools -> conda end to end -> PASS"

# --- MOB-suite database: offered and actually invoked once mob_recon/mob_init exist. ---
mkdir -p "$TMP/bin_mobdb"
for t in datasets prefetch fasterq-dump fastp minimap2 conda spades.py plasmidspades.py mob_recon mob_init platon; do
    printf '#!/usr/bin/env bash\ntrue\n' > "$TMP/bin_mobdb/$t"; chmod +x "$TMP/bin_mobdb/$t"
done
cat > "$TMP/bin_mobdb/mob_init" <<EOF
#!/usr/bin/env bash
echo "mob_init ran" >> "$TMP/mobinit_calls.log"
EOF
chmod +x "$TMP/bin_mobdb/mob_init"
if PATH="$TMP/bin_mobdb:$PATH" DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
    bash "$ROOT/scripts/00_setup.sh" --yes > "$TMP/run.log" 2>&1; then :; fi
grep -q "MOB-suite database" "$TMP/run.log" || { echo "FAIL: MOB-suite database gap not offered" >&2; cat "$TMP/run.log" >&2; exit 1; }
[[ -s "$TMP/mobinit_calls.log" ]] || { echo "FAIL: mob_init was not actually invoked" >&2; cat "$TMP/run.log" >&2; exit 1; }
echo "MOB-suite database gap is offered and mob_init actually runs -> PASS"

echo "ALL SETUP INTERACTIVE TESTS PASSED"
