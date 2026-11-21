#!/usr/bin/env bash
# Docker-mode installs (env/install_tools.sh, scripts/lib.sh, scripts/00_setup.sh): everything goes to the persistent extras folder and never into the image's (read-only)
# conda environment; a read-only prefix stops at once with one clear message; a failed profile is not retried; a heartbeat never fails the command it watches;
# MOB-suite's database is never moved out of a read-only folder. A fake micromamba records what it was asked to do. Offline; the real-Docker proof is test_docker_extras_e2e.py.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
export PLASBENCH_DB_DIR="$TMP/data/db"
trap 'chmod -R u+w "$TMP" 2>/dev/null || true; rm -rf "$TMP"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }
ok() { echo "  ok    $*"; }

# A clean PATH: the standard commands, minus every solver / ps, so only what a scenario puts first can be found.
CLEAN_BIN="$TMP/clean_bin"; NOPS_BIN="$TMP/nops_bin"; mkdir -p "$CLEAN_BIN" "$NOPS_BIN"
for dir in /usr/bin /bin; do
    [[ -d "$dir" ]] || continue
    for exe in "$dir"/*; do
        name="$(basename "$exe")"
        case "$name" in conda|mamba|micromamba|mob_recon|mob_init|mob_typer|mash|samtools|barrnap|abricate|amrfinder|isescan.py|platon|gplas) continue;; esac
        [[ -x "$exe" && ! -e "$CLEAN_BIN/$name" ]] || continue
        { ln -s "$exe" "$CLEAN_BIN/$name" 2>/dev/null || true; }
        [[ "$name" == "ps" ]] || { ln -s "$exe" "$NOPS_BIN/$name" 2>/dev/null || true; }
    done
done
# Where symlinks cannot be made (Git Bash on Windows), fall back to the shell's own PATH: the no-ps scenarios then print n/a.
LINKS_OK=1
[[ "$(find "$CLEAN_BIN" -type l 2>/dev/null | wc -l)" -gt 20 ]] || LINKS_OK=0
if [[ "$LINKS_OK" -eq 0 ]]; then
    mkdir -p "$TMP/pyshim"; printf '#!/bin/sh
exec "%s" "$@"
' "$(command -v python)" > "$TMP/pyshim/python3"; chmod +x "$TMP/pyshim/python3"
    CLEAN_BIN="$TMP/pyshim:/usr/bin:/bin"; NOPS_BIN="$CLEAN_BIN"
fi
for d in "$CLEAN_BIN" "$NOPS_BIN"; do
    [[ "$LINKS_OK" -eq 1 ]] || break
    [[ -e "$d/python3" ]] || ln -s "$(command -v python3)" "$d/python3" 2>/dev/null || cp "$(command -v python3)" "$d/python3" 2>/dev/null || true
done

FAKE="$TMP/fake"; LOG="$TMP/solver.log"; mkdir -p "$FAKE"
cat > "$FAKE/micromamba" <<FAKEEOF
#!/usr/bin/env bash
{ echo "ARGV \$*"; echo "ENV MAMBA_ROOT_PREFIX=\${MAMBA_ROOT_PREFIX:-} CONDA_PKGS_DIRS=\${CONDA_PKGS_DIRS:-} CONDA_ENVS_PATH=\${CONDA_ENVS_PATH:-} HOME=\${HOME:-}"; } >> "$LOG"
P=""
for ((i=1; i<=\$#; i++)); do [[ "\${!i}" == "-p" ]] && { j=\$((i+1)); P="\${!j}"; }; done
case "\$1" in
  create|install)
    if [[ -n "\$P" ]]; then
      mkdir -p "\$P/conda-meta" "\$P/bin"
      if [[ "\$1" == install ]]; then : > "\$P/bin/jq"; fi
    fi;;
esac
exit 0
FAKEEOF
chmod +x "$FAKE/micromamba"

# The image's environment: read-only for this user (when this user can be stopped from writing: not root, not a Windows file system).
IMG="$TMP/image/envs/plasbench"; mkdir -p "$IMG/conda-meta" "$IMG/bin"; : > "$IMG/conda-meta/history"
chmod -R a-w "$TMP/image"
RO_OK=1; if { : > "$IMG/conda-meta/probe"; } 2>/dev/null; then RO_OK=0; rm -f "$IMG/conda-meta/probe"; fi
snapshot() { (cd "$1" && find . | sort | tr '\n' ' '); }
EXTRA="$TMP/extras"; HOMEDIR="$TMP/home"; mkdir -p "$HOMEDIR"

run_install() {  # run_install ARGS... (extra variables come from the caller's VARS array)
    env -u MAMBA_ROOT_PREFIX -u CONDA_PKGS_DIRS -u CONDA_ENVS_PATH -u PLASBENCH_EXTRA_HOME -u PLASBENCH_IN_DOCKER -u PLASBENCH_INSTALL_STOP_FILE \
        HOME="$HOMEDIR" PATH="$FAKE:$CLEAN_BIN" PLASBENCH_ASSUME_ONLINE=1 "${VARS[@]}" bash "$ROOT/env/install_tools.sh" "$@"
}

echo "== Docker mode installs into the extras folder"
: > "$LOG"; before="$(snapshot "$TMP/image")"
VARS=(PLASBENCH_IN_DOCKER=1 "PLASBENCH_EXTRA_HOME=$EXTRA" "CONDA_PREFIX=$IMG")
rc=0; run_install --yes jq > "$TMP/out.txt" 2>&1 || rc=$?
[[ "$rc" -eq 0 ]] || { cat "$TMP/out.txt" "$LOG" >&2; fail "docker-mode install exited $rc"; }
ok "exit 0"
grep -q "^ARGV install .*-p $EXTRA/envs/extras .*jq" "$LOG" || { cat "$LOG" >&2; fail "the install did not target the extras environment"; }
ok "install -p <extras>/envs/extras"
if grep -- "-p " "$LOG" | grep -v -- "-p $EXTRA/" >/dev/null; then cat "$LOG" >&2; fail "a solver call used a prefix outside the extras folder"; fi
ok "every -p prefix is inside the extras folder"
grep -q "ENV MAMBA_ROOT_PREFIX=$EXTRA/mamba CONDA_PKGS_DIRS=$EXTRA/pkgs CONDA_ENVS_PATH=$EXTRA/envs " "$LOG" || { cat "$LOG" >&2; fail "root prefix / package cache / env path do not point into extras"; }
ok "MAMBA_ROOT_PREFIX, CONDA_PKGS_DIRS, CONDA_ENVS_PATH point into extras"
grep -q "^ARGV create .*-p $EXTRA/envs/extras" "$LOG" || fail "the extras environment was not created fresh (own solve)"
[[ ! -e "$EXTRA/envs/extras/conda-meta/pinned" ]] || fail "the image's pinned packages were copied into the extras environment"
ok "the extras environment is created fresh, with no inherited pins"
[[ -e "$EXTRA/envs/extras/bin/jq" ]] || fail "the installed tool is not in the extras environment"
[[ "$(snapshot "$TMP/image")" == "$before" ]] || fail "the image environment changed"
if grep -qF "$IMG" "$LOG"; then fail "the solver was pointed at the image environment"; fi
ok "the image environment is untouched and never named to the solver"

echo "== Outside Docker nothing changes"
OWN="$TMP/own/envs/plasbench"; mkdir -p "$OWN/conda-meta" "$OWN/bin"; : > "$LOG"
VARS=("CONDA_PREFIX=$OWN")
run_install --yes jq > "$TMP/out.txt" 2>&1 || { cat "$TMP/out.txt" >&2; fail "outside Docker the install failed"; }
grep -q "^ARGV install .*-p $OWN " "$LOG" || { cat "$LOG" >&2; fail "outside Docker the active environment was not the target"; }
grep -q "ENV MAMBA_ROOT_PREFIX= CONDA_PKGS_DIRS= CONDA_ENVS_PATH= " "$LOG" || { cat "$LOG" >&2; fail "outside Docker the solver variables were changed"; }
ok "the active environment is the target and no solver variable is set"

if [[ "$RO_OK" -eq 1 ]]; then
    echo "== A read-only prefix stops at once"
    : > "$LOG"; before="$(snapshot "$TMP/image")"
    VARS=(PLASBENCH_IN_DOCKER=1 "CONDA_PREFIX=$IMG")      # no extras folder: the old behaviour would have solved into the image
    start=$SECONDS; rc=0; run_install --yes jq > "$TMP/out.txt" 2>&1 || rc=$?
    [[ "$rc" -eq 1 ]] || { cat "$TMP/out.txt" >&2; fail "a read-only prefix must exit 1, got $rc"; }
    (( SECONDS - start < 15 )) || fail "the read-only check took too long"
    grep -q "read-only for your user ($IMG" "$TMP/out.txt" || { cat "$TMP/out.txt" >&2; fail "no clear read-only message"; }
    grep -q "PlasBench installs into" "$TMP/out.txt" || fail "the message does not say where extras go"
    if grep -q "^ARGV \(install\|create\)" "$LOG"; then cat "$LOG" >&2; fail "the solver ran against a read-only prefix"; fi
    [[ "$(snapshot "$TMP/image")" == "$before" ]] || fail "the image environment changed"
    ok "exit 1 within seconds, one message naming the path and the extras folder, the solver never started"

    echo "== One failed profile does not cascade"
    : > "$LOG"
    rc=0; run_install --yes utilities,reference-annotation > "$TMP/out.txt" 2>&1 || rc=$?
    [[ "$rc" -eq 1 ]] || { cat "$TMP/out.txt" >&2; fail "the profile list must exit 1, got $rc"; }
    [[ "$(grep -c 'read-only for your user' "$TMP/out.txt")" -eq 1 ]] || { cat "$TMP/out.txt" >&2; fail "the read-only diagnosis must appear exactly once"; }
    if grep -q "install-tools reference-annotation =====" "$TMP/out.txt"; then fail "the second profile was attempted against the same read-only prefix"; fi
    if grep -q "^ARGV" "$LOG"; then fail "the solver ran"; fi
    ok "the second profile is not attempted; one diagnosis; exit 1"

    echo "== MOB-suite's database in a read-only folder"
    MOBENV="$TMP/mobenv"; PKG="$MOBENV/lib/python3.10/site-packages/mob_suite"
    mkdir -p "$MOBENV/bin" "$PKG/databases" "$PLASBENCH_DB_DIR/mob_suite/databases"
    : > "$PKG/__init__.py"
    printf '#!/bin/sh\nexec %s/bin/mob_recon "$@"\n' "$MOBENV" > "$MOBENV/bin/mob_recon"; chmod +x "$MOBENV/bin/mob_recon"
    for f in status.txt ncbi_plasmid_full_seqs.fas ncbi_plasmid_full_seqs.fas.msh repetitive.dna.fas; do echo x > "$PLASBENCH_DB_DIR/mob_suite/databases/$f"; done
    chmod a-w "$PKG" "$MOBENV/lib/python3.10/site-packages"
    out="$(PATH="$MOBENV/bin:$CLEAN_BIN" PLASBENCH_IN_DOCKER=1 bash -c "source '$ROOT/scripts/lib.sh'; mobsuite_db_preserve; echo DIR=\$(mobsuite_db_dir); echo ARGS=\$(mobsuite_db_args | tr '\n' ' ')" 2>&1)" || fail "mobsuite_db_preserve failed: $out"
    if grep -q "Permission denied" <<< "$out"; then fail "an mv was attempted on the read-only folder: $out"; fi
    if ls "$PKG"/databases.pre-store.* >/dev/null 2>&1; then fail "the read-only database folder was set aside"; fi
    grep -q "DIR=$PLASBENCH_DB_DIR/mob_suite/databases" <<< "$out" || fail "the container does not use the stored database: $out"
    grep -q "ARGS=-d $PLASBENCH_DB_DIR/mob_suite/databases" <<< "$out" || fail "mob_recon is not pointed at the stored database (-d): $out"
    ok "no mv of a read-only folder, the stored database is used through -d"
    # an incomplete store and an empty image folder: nothing is complete, so the check reports a miss, never ok
    rm -f "$PLASBENCH_DB_DIR/mob_suite/databases/status.txt"
    out="$(PATH="$MOBENV/bin:$CLEAN_BIN" PLASBENCH_IN_DOCKER=1 bash -c "source '$ROOT/scripts/lib.sh'; mobsuite_db_preserve; if mobsuite_db_complete \"\$(mobsuite_db_dir)\"; then echo COMPLETE; else echo INCOMPLETE; fi" 2>&1)"
    grep -q "INCOMPLETE" <<< "$out" || fail "an incomplete database was reported complete: $out"
    ok "an incomplete database is reported incomplete"
else
    echo "  n/a   read-only prefix scenarios: this user can write to a read-only folder here (root or a Windows file system)"
fi

echo "== A heartbeat never fails the command it watches (no ps)"
if [[ "$LINKS_OK" -eq 0 ]]; then
    echo "  n/a   no-ps scenarios: this system cannot build a PATH without ps (no symlinks)"
else
rc=0; out="$(env PATH="$NOPS_BIN" HEARTBEAT_DELAY_SECONDS=0 HEARTBEAT_INTERVAL_SECONDS=1 bash -c "set -euo pipefail; source '$ROOT/scripts/lib.sh'; r=0; run_with_heartbeat 'a quiet step' sh -c 'sleep 3; exit 7' || r=\$?; echo RC=\$r" 2>&1)" || rc=$?
if [[ "$rc" -ne 0 ]] || ! grep -q "RC=7" <<< "$out"; then echo "$out" >&2; fail "the wrapped command's own exit status (7) was lost without ps: rc=$rc"; fi
grep -q "still working: a quiet step" <<< "$out" || { echo "$out" >&2; fail "no heartbeat line was printed"; }
ok "without ps: the watched command's status 7 comes back and a heartbeat line is printed"
out="$(env PATH="$NOPS_BIN" bash -c "set -euo pipefail; source '$ROOT/scripts/lib.sh'; proc_stats \$\$; echo ' rc='\$?" 2>&1)"
grep -q "rc=0" <<< "$out" || fail "proc_stats failed without ps: $out"
if [[ -r /proc/self/stat && "$(uname -s)" == "Linux" ]]; then
    grep -q "procs=" <<< "$out" || fail "no /proc fallback figures: $out"
    ok "proc_stats falls back to /proc"
fi
out="$(env PATH="$NOPS_BIN" bash -c "set -euo pipefail; source '$ROOT/scripts/lib.sh'; proc_stats(){ :; }; heartbeat_report \$\$ 'x' 5" 2>&1)"
grep -q "process figures unavailable" <<< "$out" || fail "the heartbeat does not say the figures are unavailable: $out"
ok "the heartbeat says 'process figures unavailable' when there are none"
fi

echo "== plasbench check --yes does not retry a profile that failed"
FAILBIN="$TMP/failbin"; mkdir -p "$FAILBIN"
for t in datasets prefetch fasterq-dump fastp minimap2 unzip spades.py plasmidspades.py; do printf '#!/usr/bin/env bash\ntrue\n' > "$FAILBIN/$t"; chmod +x "$FAILBIN/$t"; done
printf '#!/usr/bin/env bash\necho "conda $*" >> "%s/conda_calls.log"\nexit 1\n' "$TMP" > "$FAILBIN/conda"; chmod +x "$FAILBIN/conda"
: > "$TMP/conda_calls.log"
rc=0
HOME="$HOMEDIR" PATH="$FAILBIN:$CLEAN_BIN" DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" PLASBENCH_ASSUME_ONLINE=1 \
    bash "$ROOT/scripts/00_setup.sh" --yes < /dev/null > "$TMP/run.log" 2>&1 || rc=$?
[[ "$rc" -ne 0 ]] || { cat "$TMP/run.log" >&2; fail "check --yes exited 0 although requested installs failed"; }
ok "exit code is not 0 when requested installs failed (exit $rc)"
grep -q "Checking again now that the installation has run" "$TMP/run.log" || { cat "$TMP/run.log" >&2; fail "the re-check did not happen"; }
[[ "$(grep -c "Installing 'install-tools reconstruction'" "$TMP/run.log")" -eq 1 ]] || { cat "$TMP/run.log" >&2; fail "the failed profile was installed more than once"; }
grep -q "not retrying reconstruction" "$TMP/run.log" || { cat "$TMP/run.log" >&2; fail "no 'not retrying' notice"; }
grep -q "^  FAILED reconstruction: " "$TMP/run.log" || { cat "$TMP/run.log" >&2; fail "no summary line for the failed profile"; }
if grep -q 'return "\$rc"' "$TMP/run.log"; then fail "the useless shell-line ERR message is back"; fi
grep -q "install-tools reconstruction failed" "$TMP/run.log" || { cat "$TMP/run.log" >&2; fail "the failure does not name the profile"; }
ok "one install attempt per profile, a 'not retrying' notice, a summary, and the failure names the profile"

echo "ALL DOCKER EXTRAS SHELL TESTS PASSED"
