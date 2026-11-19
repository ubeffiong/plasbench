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
# The installers write to the database store; keep it in this test's scratch data/db.
export PLASBENCH_DB_DIR="$TMP/data/db"
trap 'rm -rf "$TMP"' EXIT

# This suite's whole premise is simulating which tools are present or absent
# -- but a real machine running this (e.g. this project's own Docker image,
# which bundles working mob_recon/platon/mob_init/gplas shims and the core
# datasets/prefetch/.../spades.py toolchain for real) already has every one
# of these on PATH. Appending ":$PATH" would let those real binaries leak
# through and override what a scenario intends to simulate as missing.
# Build a clean base PATH instead: every real command EXCEPT the ones this
# suite fakes, so each scenario's PATH prefix is the only place those names
# can be found. Restrict this to standard POSIX command directories: scanning
# an inherited WSL PATH can traverse mounted Windows locations and make this
# otherwise offline fixture appear hung.
CLEAN_BIN="$TMP/clean_bin"
mkdir -p "$CLEAN_BIN"
for dir in /usr/bin /bin; do
    [[ -d "$dir" ]] || continue
    for exe in "$dir"/*; do
        name="$(basename "$exe")"
        case "$name" in
            datasets|prefetch|fasterq-dump|fastp|minimap2|unzip|conda|mamba|micromamba|spades.py|plasmidspades.py|mob_recon|mob_init|mob_typer|mob_cluster|platon|gplas|mash|samtools|barrnap|abricate|amrfinder|isescan.py) continue ;;
        esac
        # `|| true`: some directories on a real machine's PATH (e.g. a
        # protected Windows system directory under Git Bash) refuse symlink
        # creation without elevated privileges. That single miss must not
        # abort this whole script under `set -e` -- it just means whatever
        # lived there isn't available under CLEAN_BIN, harmless unless this
        # suite specifically needed it.
        [[ -x "$exe" && ! -e "$CLEAN_BIN/$name" ]] && { ln -s "$exe" "$CLEAN_BIN/$name" 2>/dev/null || true; }
    done
done

# the installer scripts call python3; make sure the clean PATH has one (a machine whose python3 is not in /usr/bin, such as Git Bash)
[[ -e "$CLEAN_BIN/python3" ]] || ln -s "$(command -v python3)" "$CLEAN_BIN/python3" 2>/dev/null || cp "$(command -v python3)" "$CLEAN_BIN/python3" 2>/dev/null || true

mkdir -p "$TMP/bin_full" "$TMP/bin_partial" "$TMP/data/db/platon/db" "$TMP/results" "$TMP/logs" "$TMP/tmp"
touch "$TMP/data/db/platon/db/marker"

for t in datasets prefetch fasterq-dump fastp minimap2 unzip python3 conda spades.py plasmidspades.py mob_recon platon mash samtools barrnap abricate amrfinder isescan.py mob_typer; do
    printf '#!/usr/bin/env bash\ntrue\n' > "$TMP/bin_full/$t"; chmod +x "$TMP/bin_full/$t"
done
for t in datasets prefetch fasterq-dump fastp minimap2 unzip python3 conda spades.py plasmidspades.py; do
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
    # HOME is the scratch dir, so install_tools.sh cannot find (and write wrappers
    # into) a real conda environment on the machine running the test.
    HOME="$TMP" PATH="$1:$CLEAN_BIN" DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
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
# platon goes into the main environment; mob_suite into its own pinned one (create).
grep -q "install .*platon" "$TMP/conda_calls.log" && grep -q "create .*mob_suite=3.1.9" "$TMP/conda_calls.log" || {
    echo "FAIL: install_tools.sh did not install platon and create the pinned mob_suite env" >&2; cat "$TMP/conda_calls.log" >&2; exit 1; }
if grep -q "install .*mob_suite" "$TMP/conda_calls.log"; then
    echo "FAIL: mob_suite was installed into the main environment" >&2; cat "$TMP/conda_calls.log" >&2; exit 1; fi
echo "missing reconstruction tools + --yes triggers install-tools -> conda end to end -> PASS"

# --- same gap, declining consent: must not touch conda at all. ---
: > "$TMP/conda_calls.log"
if HOME="$TMP" PATH="$TMP/bin_partial:$CLEAN_BIN" DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
    bash "$ROOT/scripts/00_setup.sh" < /dev/null > "$TMP/run.log" 2>&1; then
    echo "FAIL: declining should exit non-zero" >&2; cat "$TMP/run.log" >&2; exit 1
fi
[[ ! -s "$TMP/conda_calls.log" ]] || { echo "FAIL: declining must never invoke conda" >&2; cat "$TMP/conda_calls.log" >&2; exit 1; }
grep -q "Skipped" "$TMP/run.log" || { echo "FAIL: expected a Skipped message" >&2; cat "$TMP/run.log" >&2; exit 1; }
# A run with no terminal fails fast (before any sample work) with the exact command, naming what is missing.
grep -q "plasbench install-tools reconstruction --yes" "$TMP/run.log" && grep -q "INSTALL_MISSING_TOOLS=1" "$TMP/run.log" || { echo "FAIL: the non-interactive stop must name the exact install command and INSTALL_MISSING_TOOLS" >&2; cat "$TMP/run.log" >&2; exit 1; }
echo "declining consent never touches conda, and a run without a terminal stops naming the command -> PASS"

# --- INSTALL_MISSING_TOOLS=1 is consent: a run with no terminal installs what is missing instead of stopping. ---
: > "$TMP/conda_calls.log"
HOME="$TMP" PATH="$TMP/bin_partial:$CLEAN_BIN" DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" INSTALL_MISSING_TOOLS=1     bash "$ROOT/scripts/00_setup.sh" < /dev/null > "$TMP/run.log" 2>&1 || true
grep -q "create .*mob_suite=3.1.9" "$TMP/conda_calls.log" || { echo "FAIL: INSTALL_MISSING_TOOLS=1 did not install the missing tools" >&2; cat "$TMP/run.log" >&2; exit 1; }
grep -q "Checking again now that the installation has run" "$TMP/run.log" || { echo "FAIL: setup must re-check after installing (so a run can carry on)" >&2; exit 1; }
echo "INSTALL_MISSING_TOOLS=1 installs without a terminal and then re-checks -> PASS"

# --- missing gplas (needed only when a gplas2_* mode is enabled), conda
# present, --yes: offers and actually invokes install-tools gplas, which
# actually invokes conda. gplas is otherwise not needed, so bin_full (which
# lacks it) plus a logging conda is enough to isolate this one gap. ---
mkdir -p "$TMP/bin_gplas"
for t in datasets prefetch fasterq-dump fastp minimap2 unzip spades.py plasmidspades.py mob_recon platon mash samtools barrnap abricate amrfinder isescan.py mob_typer; do
    printf '#!/usr/bin/env bash\ntrue\n' > "$TMP/bin_gplas/$t"; chmod +x "$TMP/bin_gplas/$t"
done
cat > "$TMP/bin_gplas/conda" <<EOF
#!/usr/bin/env bash
echo "conda \$*" >> "$TMP/conda_calls.log"
true
EOF
chmod +x "$TMP/bin_gplas/conda"

mkdir -p "$TMP/conda/envs/plasbench"
: > "$TMP/conda_calls.log"
if PATH="$TMP/bin_gplas:$CLEAN_BIN" DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
    CONDA_PREFIX="$TMP/conda/envs/plasbench" PLASBENCH_SOURCE_TEST_OVERRIDES=1 PLASBENCH_SOURCE_URL_GPLAS2="$TMP/no-such-upstream.git" PLASBENCH_ASSUME_ONLINE=1     RUN_GPLAS2_MOB=1 bash "$ROOT/scripts/00_setup.sh" --yes > "$TMP/run.log" 2>&1; then
    echo "FAIL: this run should exit non-zero (a freshly-attempted install is never a passing check)" >&2
    cat "$TMP/run.log" >&2; exit 1
fi
grep -q "install-tools profile: gplas" "$TMP/run.log" || { echo "FAIL: gplas profile not offered" >&2; cat "$TMP/run.log" >&2; exit 1; }
# gplas2 is a source-built tool (config/source_tools.json): the plan with the pinned commit is shown, and the installer starts by cloning that repository (here redirected
# to a folder that does not exist so nothing is downloaded; the clone fails and leaves nothing behind).
grep -q "9ec35cf6674c41ad91afc582dcbe9b2eee9161b0" "$TMP/run.log" && grep -q "cloning https://gitlab.com/mmb-umcu/gplas2.git" "$TMP/run.log" || { echo "FAIL: install_tools.sh did not show the gplas2 plan and start its pinned install" >&2; cat "$TMP/run.log" >&2; exit 1; }
if grep -q "install .*[ ]gplas" "$TMP/conda_calls.log"; then echo "FAIL: the old gplas 0.6.1 conda package (no -P option) must not be installed" >&2; exit 1; fi
echo "missing gplas (RUN_GPLAS2_MOB=1) + --yes triggers the pinned gplas2 install (not bioconda's gplas 0.6.1) -> PASS"

# --- MOB-suite database: offered and actually invoked once mob_recon/mob_init exist. ---
mkdir -p "$TMP/bin_mobdb"
for t in datasets prefetch fasterq-dump fastp minimap2 unzip conda spades.py plasmidspades.py mob_recon mob_init platon; do
    printf '#!/usr/bin/env bash\ntrue\n' > "$TMP/bin_mobdb/$t"; chmod +x "$TMP/bin_mobdb/$t"
done
cat > "$TMP/bin_mobdb/mob_init" <<EOF
#!/usr/bin/env bash
echo "mob_init ran" >> "$TMP/mobinit_calls.log"
EOF
chmod +x "$TMP/bin_mobdb/mob_init"
if PATH="$TMP/bin_mobdb:$CLEAN_BIN" DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
    bash "$ROOT/scripts/00_setup.sh" --yes > "$TMP/run.log" 2>&1; then :; fi
grep -q "MOB-suite database" "$TMP/run.log" || { echo "FAIL: MOB-suite database gap not offered" >&2; cat "$TMP/run.log" >&2; exit 1; }
[[ -s "$TMP/mobinit_calls.log" ]] || { echo "FAIL: mob_init was not actually invoked" >&2; cat "$TMP/run.log" >&2; exit 1; }
echo "MOB-suite database gap is offered and mob_init actually runs -> PASS"

echo "ALL SETUP INTERACTIVE TESTS PASSED"
