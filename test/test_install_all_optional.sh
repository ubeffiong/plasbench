#!/usr/bin/env bash
# `install-tools all`: an optional tool that cannot install (the Trycycler solve killed for memory on a small PC)
# is reported with how to retry and does not fail the whole install; a failing base profile still does.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin" "$TMP/conda/envs/plasbench"

# A fake conda: `info --base` answers, `install` of a package named like FAKE_FAIL exits 137 (killed), the rest succeed.
cat > "$TMP/bin/conda" <<EOF
#!/usr/bin/env bash
if [[ "\$1" == "info" ]]; then echo "$TMP/conda"; exit 0; fi
if [[ "\$1" == "install" ]]; then
    for arg in "\$@"; do
        [[ -n "\${FAKE_FAIL:-}" && "\$arg" == "\$FAKE_FAIL" ]] && exit 137
    done
fi
exit 0
EOF
chmod +x "$TMP/bin/conda"

run_all() {
    [[ -n "${DEBUG_OUT:-}" && -f "$TMP/out" ]] && { echo "--- previous output:"; cat "$TMP/out"; }
    PATH="$TMP/bin:/usr/bin:/bin" CONDA_PREFIX="$TMP/conda/envs/plasbench" HEARTBEAT_DELAY_SECONDS=999 \
        PLASBENCH_ALL_PROFILES="$1" FAKE_FAIL="$2" bash "$ROOT/env/install_tools.sh" --env plasbench all > "$TMP/out" 2>&1
}

ok=1
check() { if [[ "$2" == "yes" ]]; then echo "  ok    $1"; else echo "  FAIL  $1"; ok=0; fi; }

run_all "core fakeoptional" "fakeoptional"; code=$?
check "an optional profile that is killed does not fail the install (exit 0)" "$([[ $code -eq 0 ]] && echo yes || echo no)"
check "the skipped optional tool is named, with how to retry" \
      "$(grep -q 'these optional tools were not installed: fakeoptional' "$TMP/out" && grep -q 'plasbench install-tools <name>' "$TMP/out" && echo yes || echo no)"
check "a kill (137) explains how to give WSL more memory" "$(grep -q 'wsl --shutdown' "$TMP/out" && grep -q 'memory=8GB' "$TMP/out" && echo yes || echo no)"

run_all "core fakeoptional" ""; code=$?
check "with nothing failing there is no warning and exit 0" "$([[ $code -eq 0 ]] && ! grep -q 'were not installed' "$TMP/out" && echo yes || echo no)"

run_all "core assembly" "spades"; code=$?
check "a failing base profile still fails the install" "$([[ $code -ne 0 ]] && echo yes || echo no)"

[[ "$ok" -eq 1 ]] && echo "ALL INSTALL-ALL OPTIONAL PROFILE TESTS PASSED" || { echo "INSTALL-ALL OPTIONAL PROFILE TESTS FAILED"; cat "$TMP/out"; exit 1; }
