#!/usr/bin/env bash
# update.sh and scripts/release_sync.sh: PlasBench lives in ONE folder, PlasBench, updated in place.
#   already up to date                                  -> no download, clean exit
#   from an older plasbench-<version> folder            -> new release in PlasBench/; runs moved to studies/; settings,
#                                                          .ncbi.env, local.tsv and own tools carried; downloads moved to
#                                                          shared storage once; old folder removed (--yes); tools reused
#   an update inside PlasBench                          -> only release files change: a dropped file is removed, a new
#                                                          one added, an edited release file backed up; studies,
#                                                          local.env and own files untouched; update.sh replaced safely
#   a non-PlasBench folder already named PlasBench      -> refused, its contents untouched
#   --keep-old                                          -> the old folder is kept
#   plasbench upgrade                                   -> delegates to update.sh
# Fakes curl (GitHub API and release assets), so it runs offline.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'chmod -R u+w "$TMP" 2>/dev/null || true; rm -rf "$TMP"' EXIT
fail() { echo "FAIL: $*" >&2; [[ -f "$TMP/update.log" ]] && tail -30 "$TMP/update.log" >&2; exit 1; }

# An installed versioned folder (the pre-0.3.1 layout).
make_install_dir() {
    local dir="$1" version="$2"
    mkdir -p "$dir/plasbench" "$dir/config" "$dir/scripts"
    printf '__version__ = "%s"\n' "$version" > "$dir/plasbench/__init__.py"
    cp "$ROOT/update.sh" "$dir/update.sh"
    chmod +x "$dir/update.sh"
}

# A release tarball: plasbench-<v>/ with the real update.sh and release_sync.sh and a stand-in install.sh.
make_release() {
    local version="$1" stage="$TMP/stage-$1/plasbench-$1"
    mkdir -p "$stage/plasbench" "$stage/scripts" "$stage/config"
    printf '__version__ = "%s"\n' "$version" > "$stage/plasbench/__init__.py"
    cp "$ROOT/update.sh" "$stage/update.sh"
    printf '\n# release %s\n' "$version" >> "$stage/update.sh"
    cp "$ROOT/scripts/release_sync.sh" "$stage/scripts/release_sync.sh"
    printf 'export THREADS=%s\n' "${version//./}" > "$stage/config/config.sh"
    cat > "$stage/install.sh" <<EOF
#!/usr/bin/env bash
echo "install.sh \$(pwd) invoked with: \$*" >> "$TMP/install_invocations.log"
EOF
    chmod +x "$stage/install.sh" "$stage/update.sh"
    ( cd "$TMP/stage-$version" && tar -czf "$TMP/plasbench-$version.tar.gz" "plasbench-$version" )
    ( cd "$TMP" && sha256sum "plasbench-$version.tar.gz" > "plasbench-$version.tar.gz.sha256" )
}

fake_curl() {   # fake_curl DIR VERSION: GitHub says VERSION is the latest and serves its tarball
    mkdir -p "$1"
    cat > "$1/curl" <<EOF
#!/usr/bin/env bash
dest="" url=""
args=("\$@")
for ((i=0; i<\${#args[@]}; i++)); do
    case "\${args[i]}" in -o) dest="\${args[i+1]}" ;; http*) url="\${args[i]}" ;; esac
done
if [[ "\$url" == *"/releases/latest" ]]; then echo '{"tag_name": "v$2"}'
elif [[ "\$url" == *.sha256 ]]; then cp "$TMP/plasbench-$2.tar.gz.sha256" "\$dest"
elif [[ "\$url" == *.tar.gz ]]; then cp "$TMP/plasbench-$2.tar.gz" "\$dest"
else echo "FAKE CURL: unexpected URL: \$url" >&2; exit 1; fi
EOF
    chmod +x "$1/curl"
}

# --- already up to date -------------------------------------------------------------------------------------------
OLD="$TMP/plasbench-0.2.1"
make_install_dir "$OLD" "0.2.1"
fake_curl "$TMP/bin_same" "0.2.1"
out="$(PATH="$TMP/bin_same:$PATH" bash "$OLD/update.sh" 2>&1)" || fail "an up-to-date check must exit 0: $out"
grep -q "already up to date" <<< "$out" || fail "expected an already-up-to-date message: $out"
[[ ! -e "$TMP/PlasBench" ]] || fail "nothing may be installed when already up to date"
echo "already on the latest version -> no download, clean exit -> PASS"
rm -rf "$OLD"

# --- from an older versioned folder into PlasBench ----------------------------------------------------------------
make_release "0.3.1"
fake_curl "$TMP/bin_031" "0.3.1"
OLD2="$TMP/plasbench-0.1.0"
make_install_dir "$OLD2" "0.1.0"
mkdir -p "$OLD2/data/db/platon/db" "$OLD2/results/s1" "$OLD2/results_demo" "$OLD2/tools.d/my_tool" "$OLD2/tools.d/examples/x"
echo "fake platon db file" > "$OLD2/data/db/platon/db/marker"
echo "NCBI_API_KEY=secret123" > "$OLD2/.ncbi.env"
printf 'sample_id\tassembly_accession\ns1\tGCF_1\n' > "$OLD2/config/local.tsv"
echo "report" > "$OLD2/results/benchmark.report.html"
echo "demo report" > "$OLD2/results_demo/benchmark.report.html"
echo "[tool]" > "$OLD2/tools.d/my_tool/plasbench-tool.ini"
: > "$TMP/install_invocations.log"
XDG_DATA_HOME="$TMP/xdg" PATH="$TMP/bin_031:$PATH" bash "$OLD2/update.sh" --yes > "$TMP/update.log" 2>&1 \
    || fail "the move into PlasBench should succeed"
PB="$TMP/PlasBench"
[[ -f "$PB/.plasbench-release-files" ]] || fail "PlasBench/ has no release file list"
grep -q '0.3.1' "$PB/plasbench/__init__.py" || fail "PlasBench/ does not hold the new release"
[[ -f "$TMP/xdg/plasbench/data/db/platon/db/marker" ]] || fail "downloads were not moved to shared storage"
grep -Fq "$TMP/xdg/plasbench/data" "$PB/config/local.env" || fail "PlasBench/ does not use the shared downloads"
[[ -f "$PB/.ncbi.env" && -f "$PB/config/local.tsv" ]] || fail ".ncbi.env and config/local.tsv must be carried over"
[[ -f "$PB/studies/results-0.1.0/results/benchmark.report.html" && -f "$PB/studies/results-0.1.0/study.json" ]] \
    || fail "results/ must become the study results-0.1.0"
[[ -f "$PB/studies/demo-0.1.0/results/benchmark.report.html" ]] || fail "results_demo/ must become the study demo-0.1.0"
[[ -f "$PB/tools.d/my_tool/plasbench-tool.ini" && ! -e "$PB/tools.d/examples/x" ]] || fail "own tools (not examples) must be carried"
[[ ! -e "$OLD2" ]] || fail "with --yes the old folder must be removed once its runs and downloads are safe"
grep -q -- "--yes" "$TMP/install_invocations.log" || fail "install.sh was not invoked with --yes"
! grep -q -- "--tools" "$TMP/install_invocations.log" || fail "an ordinary update must reuse tools, not refresh them"
echo "an older versioned folder is carried into PlasBench: runs to studies/, settings, own tools, shared downloads -> PASS"

# --- an update inside PlasBench -------------------------------------------------------------------------------------
echo "obsolete" > "$PB/obsolete.txt"
printf '%s\t%s\n' "$(sha256sum "$PB/obsolete.txt" | cut -d' ' -f1)" "obsolete.txt" >> "$PB/.plasbench-release-files"
echo "# my own edit" >> "$PB/config/config.sh"
mkdir -p "$PB/studies/mine/results" && echo "mine" > "$PB/studies/mine/results/keep.txt"
echo "export THREADS=6" >> "$PB/config/local.env"
make_release "0.3.2"
echo "new in 0.3.2" > "$TMP/stage-0.3.2/plasbench-0.3.2/new.txt"
( cd "$TMP/stage-0.3.2" && tar -czf "$TMP/plasbench-0.3.2.tar.gz" plasbench-0.3.2 )
( cd "$TMP" && sha256sum plasbench-0.3.2.tar.gz > plasbench-0.3.2.tar.gz.sha256 )
fake_curl "$TMP/bin_032" "0.3.2"
: > "$TMP/install_invocations.log"
XDG_DATA_HOME="$TMP/xdg" PATH="$TMP/bin_032:$PATH" bash "$PB/update.sh" --yes > "$TMP/update.log" 2>&1 \
    || fail "an in-place update should succeed"
grep -q '0.3.2' "$PB/plasbench/__init__.py" || fail "the in-place update did not install 0.3.2"
[[ -f "$PB/new.txt" && ! -e "$PB/obsolete.txt" ]] || fail "a dropped release file must go and a new one arrive"
grep -q "release 0.3.2" "$PB/update.sh" || fail "update.sh itself must be replaced by the new release's"
[[ -f "$PB/studies/mine/results/keep.txt" && -f "$PB/studies/results-0.1.0/results/benchmark.report.html" ]] \
    || fail "studies must be untouched"
grep -q "THREADS=6" "$PB/config/local.env" || fail "config/local.env must be untouched"
grep -q "THREADS=032" "$PB/config/config.sh" || fail "config/config.sh must be the new release's"
ls "$PB"/.plasbench-backup/*/config/config.sh >/dev/null 2>&1 || fail "the edited config.sh must be backed up"
grep -q "my own edit" "$PB"/.plasbench-backup/*/config/config.sh || fail "the backup must hold the user's edit"
grep -q "$PB" "$TMP/install_invocations.log" || fail "install.sh must run in PlasBench"
echo "an update inside PlasBench replaces only release files and backs up edited ones -> PASS"

# --- a foreign folder named PlasBench is never overwritten ---------------------------------------------------------
mkdir -p "$TMP/other"
OLD3="$TMP/other/plasbench-0.1.1"
make_install_dir "$OLD3" "0.1.1"
mkdir -p "$TMP/other/PlasBench" && echo "not ours" > "$TMP/other/PlasBench/thesis.docx"
if PATH="$TMP/bin_032:$PATH" bash "$OLD3/update.sh" --yes > "$TMP/update.log" 2>&1; then
    fail "update.sh must refuse a PlasBench folder that is not a PlasBench install"
fi
grep -qi "already exists" "$TMP/update.log" || fail "expected an 'already exists' error"
[[ -f "$TMP/other/PlasBench/thesis.docx" && -d "$OLD3" ]] || fail "nothing may be touched"
echo "a foreign folder named PlasBench is never overwritten -> PASS"

# --- --keep-old --------------------------------------------------------------------------------------------------
mkdir -p "$TMP/keep"
OLD4="$TMP/keep/plasbench-0.1.2"
make_install_dir "$OLD4" "0.1.2"
mkdir -p "$OLD4/results" && echo r > "$OLD4/results/a.txt"
XDG_DATA_HOME="$TMP/xdg" PATH="$TMP/bin_032:$PATH" bash "$OLD4/update.sh" --yes --keep-old > "$TMP/update.log" 2>&1 \
    || fail "--keep-old update should succeed"
[[ -d "$OLD4" && -f "$OLD4/MOVED_TO_PlasBench.txt" && -f "$TMP/keep/PlasBench/studies/results-0.1.2/results/a.txt" ]] \
    || fail "--keep-old must keep the old folder and still move its runs"
echo "--keep-old keeps the old folder -> PASS"

# --- install_latest.sh: installs into PlasBench, carries a versioned folder beside it, and updates in place ----------
mkdir -p "$TMP/fresh"
OLD5="$TMP/fresh/plasbench-0.2.3"
make_install_dir "$OLD5" "0.2.3"
mkdir -p "$OLD5/results" && echo r > "$OLD5/results/benchmark.report.html"
: > "$TMP/install_invocations.log"
PLASBENCH_INSTALL_DIR="$TMP/fresh" XDG_DATA_HOME="$TMP/xdg" PATH="$TMP/bin_031:$PATH" \
    bash "$ROOT/scripts/install_latest.sh" --yes > "$TMP/update.log" 2>&1 || fail "install_latest.sh should succeed"
grep -q '0.3.1' "$TMP/fresh/PlasBench/plasbench/__init__.py" || fail "install_latest.sh did not install into PlasBench"
[[ -f "$TMP/fresh/PlasBench/studies/results-0.2.3/results/benchmark.report.html" && ! -e "$OLD5" ]] \
    || fail "install_latest.sh must carry the versioned folder's runs in and remove it with --yes"
echo "mine" > "$TMP/fresh/PlasBench/studies/results-0.2.3/notes.txt"
PLASBENCH_INSTALL_DIR="$TMP/fresh" XDG_DATA_HOME="$TMP/xdg" PATH="$TMP/bin_032:$PATH" \
    bash "$ROOT/scripts/install_latest.sh" --yes > "$TMP/update.log" 2>&1 || fail "a second install_latest.sh should update"
grep -q '0.3.2' "$TMP/fresh/PlasBench/plasbench/__init__.py" || fail "install_latest.sh must update PlasBench in place"
[[ -f "$TMP/fresh/PlasBench/studies/results-0.2.3/notes.txt" ]] || fail "studies must survive an install_latest.sh update"
[[ ! -e "$TMP/fresh/plasbench-0.3.2" ]] || fail "no versioned folder may be created any more"
echo "install_latest.sh installs into PlasBench, carries older folders in, and updates in place -> PASS"

# --- the CLI delegates to update.sh --------------------------------------------------------------------------------
python3 - "$ROOT" <<'PY'
import sys
from pathlib import Path

from plasbench import cli

root = Path(sys.argv[1])
calls = []

def fake_run(command, received_root, env=None):
    calls.append((command, received_root, env))
    return 0

cli.run = fake_run
try:
    cli.main(["--project-root", str(root), "upgrade", "--yes"])
except SystemExit as exc:
    assert exc.code == 0, exc.code
assert calls == [([cli.bash_command(), "update.sh", "--yes"], root, None)], calls
print("plasbench upgrade delegates to update.sh with --yes -> PASS")
PY

echo "ALL UPDATE SCRIPT TESTS PASSED"
