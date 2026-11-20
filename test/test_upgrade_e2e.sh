#!/usr/bin/env bash
# `plasbench upgrade` end to end (update.sh) in a temporary home, with tiny fake release tarballs and a fake curl (nothing is downloaded, no conda):
#   --check-only          says available / current / newer and changes nothing, downloads nothing
#   --archive FILE        installs a release file with NO network; phases 1/6..6/6 are announced; the previous release is saved as a rollback copy
#   --rollback            goes back with that copy
#   --version X           downloads over https only, with a size limit, verifies the checksum, installs; an older X is announced as a downgrade
#   refusals              bad checksum, a file named for another version, a misnamed file, a tar with paths outside the release, a failed
#                         download, a second update at the same time: each says why, and NOTHING is replaced (the installed files stay byte for byte)
#   the CLI               `plasbench upgrade --check-only/--archive/--version/--rollback` pass exactly those options to update.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'chmod -R u+w "$TMP" 2>/dev/null || true; rm -rf "$TMP"' EXIT
export PLASBENCH_ASSUME_ONLINE=1
export XDG_DATA_HOME="$TMP/xdg"
fail() { echo "FAIL: $*" >&2; [[ -f "$TMP/out.log" ]] && tail -30 "$TMP/out.log" >&2; exit 1; }
PY=python3
python3 -c 'import sys' >/dev/null 2>&1 || PY=python

make_release() {   # make_release VERSION: plasbench-<v>.tar.gz (+ .sha256) in $TMP/rel, with the real update.sh and release_sync.sh and a stand-in install.sh
    local version="$1" stage="$TMP/stage-$1/plasbench-$1"
    mkdir -p "$stage/plasbench" "$stage/scripts" "$stage/config" "$TMP/rel"
    printf '__version__ = "%s"\n' "$version" > "$stage/plasbench/__init__.py"
    cp "$ROOT/update.sh" "$stage/update.sh"
    cp "$ROOT/scripts/release_sync.sh" "$stage/scripts/release_sync.sh"
    printf 'release %s\n' "$version" > "$stage/RELEASE_MARKER"
    cat > "$stage/install.sh" <<EOF
#!/usr/bin/env bash
echo "install.sh \$(pwd) invoked with: \$*" >> "$TMP/install_invocations.log"
[[ -z "\${FAKE_INSTALL_FAIL:-}" ]] || { echo "ERROR: no conda-family package manager is available." >&2; exit 1; }
EOF
    chmod +x "$stage/install.sh" "$stage/update.sh"
    ( cd "$TMP/stage-$version" && tar -czf "$TMP/rel/plasbench-$version.tar.gz" "plasbench-$version" )
    ( cd "$TMP/rel" && sha256sum "plasbench-$version.tar.gz" > "plasbench-$version.tar.gz.sha256" )
}

fake_curl() {   # fake_curl DIR LATEST: GitHub says LATEST is the latest and serves tarballs from $TMP/rel; every call is logged
    mkdir -p "$1"
    cat > "$1/curl" <<EOF
#!/usr/bin/env bash
echo "\$*" >> "$TMP/curl_calls.log"
dest="" url=""
args=("\$@")
for ((i=0; i<\${#args[@]}; i++)); do
    case "\${args[i]}" in -o) dest="\${args[i+1]}" ;; http*) url="\${args[i]}" ;; esac
done
[[ -z "\${FAKE_CURL_FAIL:-}" ]] || exit "\$FAKE_CURL_FAIL"
file="\${url##*/}"
if [[ "\$url" == *"/releases/latest" ]]; then echo '{"tag_name": "v$2"}'
elif [[ -f "$TMP/rel/\$file" ]]; then cp "$TMP/rel/\$file" "\$dest"
else echo "FAKE CURL: unexpected URL: \$url" >&2; exit 22; fi
EOF
    chmod +x "$1/curl"
}
no_curl() {     # a curl that must never be called
    mkdir -p "$1"
    printf '#!/usr/bin/env bash\necho "curl was called: $*" >> "%s/curl_forbidden.log"\nexit 99\n' "$TMP" > "$1/curl"
    chmod +x "$1/curl"
}
tree_sum() { ( cd "$1" && find . -type f ! -path './.plasbench-rollback/*' ! -path './.plasbench-upgrade.lock/*' -print0 | sort -z | xargs -0 sha256sum | sha256sum ); }

# --- an installed PlasBench 0.3.1 (a first install from an older versioned folder, as update.sh does it) -------------------------------
make_release 0.3.1
OLD="$TMP/plasbench-0.1.0"
mkdir -p "$OLD/plasbench" "$OLD/config" "$OLD/scripts"
printf '__version__ = "0.1.0"\n' > "$OLD/plasbench/__init__.py"
cp "$ROOT/update.sh" "$OLD/update.sh"
fake_curl "$TMP/bin_031" "0.3.1"
PLASBENCH_INSTALL_DIR="$TMP" PATH="$TMP/bin_031:$PATH" bash "$OLD/update.sh" --yes > "$TMP/out.log" 2>&1 || fail "the first install should succeed"
PB="$TMP/PlasBench"
grep -q '0.3.1' "$PB/plasbench/__init__.py" || fail "0.3.1 was not installed"
mkdir -p "$PB/studies/mine/results" && echo "my data" > "$PB/studies/mine/results/keep.txt"
echo "export THREADS=6" >> "$PB/config/local.env"
echo "a first install saves no rollback copy (nothing to go back to) -> PASS"
[[ ! -d "$PB/.plasbench-rollback" ]] || fail "a first install must not create a rollback copy"

# --- --check-only ---------------------------------------------------------------------------------------------------------------------
make_release 0.3.2
fake_curl "$TMP/bin_032" "0.3.2"
: > "$TMP/curl_calls.log"
before="$(tree_sum "$PB")"
out="$(PATH="$TMP/bin_032:$PATH" bash "$PB/update.sh" --check-only 2>&1)" || fail "--check-only must exit 0: $out"
grep -q "RESULT available: 0.3.1 -> 0.3.2" <<< "$out" || fail "--check-only must report the available update: $out"
[[ "$(tree_sum "$PB")" == "$before" ]] || fail "--check-only changed files"
! grep -q "\.tar\.gz" "$TMP/curl_calls.log" || fail "--check-only must not download the release"
grep -q "releases/latest" "$TMP/curl_calls.log" || fail "--check-only must ask the release list"
out="$(PATH="$TMP/bin_031:$PATH" bash "$PB/update.sh" --check-only 2>&1)" || fail "--check-only (current)"
grep -q "RESULT current" <<< "$out" || fail "--check-only must say the release is current: $out"
fake_curl "$TMP/bin_030" "0.3.0"
out="$(PATH="$TMP/bin_030:$PATH" bash "$PB/update.sh" --check-only 2>&1)" || fail "--check-only (newer)"
grep -q "RESULT newer" <<< "$out" || fail "--check-only must say this folder is newer than the release: $out"
! bash "$PB/update.sh" --check-only --archive "$TMP/rel/plasbench-0.3.2.tar.gz" > /dev/null 2>&1 || fail "--check-only with --archive must be refused"
echo "--check-only reports available / current / newer, changes nothing and downloads nothing -> PASS"

# --- --archive: no network, phases, rollback copy -------------------------------------------------------------------------------------
no_curl "$TMP/bin_none"
: > "$TMP/install_invocations.log"
PATH="$TMP/bin_none:$PATH" bash "$PB/update.sh" --archive "$TMP/rel/plasbench-0.3.2.tar.gz" --yes > "$TMP/out.log" 2>&1 || fail "--archive should install"
[[ ! -e "$TMP/curl_forbidden.log" ]] || fail "--archive must not call curl (no network)"
grep -q '0.3.2' "$PB/plasbench/__init__.py" || fail "--archive did not install 0.3.2"
[[ "$(cat "$PB/RELEASE_MARKER")" == "release 0.3.2" ]] || fail "release files were not replaced"
for n in 1 2 3 4 5 6; do grep -q "PHASE $n/6" "$TMP/out.log" || fail "phase $n/6 was not announced"; done
grep -q -- "--yes" "$TMP/install_invocations.log" || fail "install.sh was not run with --yes"
[[ -f "$PB/studies/mine/results/keep.txt" ]] && grep -q "THREADS=6" "$PB/config/local.env" || fail "studies and settings must be kept"
[[ -f "$PB/.plasbench-rollback/plasbench-0.3.1.tar.gz" && -f "$PB/.plasbench-rollback/plasbench-0.3.1.tar.gz.sha256" ]] || fail "the previous release was not saved as a rollback copy"
( cd "$PB/.plasbench-rollback" && sha256sum -c plasbench-0.3.1.tar.gz.sha256 > /dev/null ) || fail "the rollback copy does not match its checksum"
[[ ! -e "$PB/.plasbench-upgrade.lock" ]] || fail "the update lock was not released"
echo "--archive installs with no network, announces six phases, keeps studies and settings, saves a rollback copy -> PASS"

# --- --archive without a .sha256 prints the checksum to compare ------------------------------------------------------------------------
mkdir -p "$TMP/bare" && cp "$TMP/rel/plasbench-0.3.2.tar.gz" "$TMP/bare/plasbench-0.3.2.tar.gz"
PATH="$TMP/bin_none:$PATH" bash "$PB/update.sh" --archive "$TMP/bare/plasbench-0.3.2.tar.gz" --yes > "$TMP/out.log" 2>&1 || fail "--archive without .sha256 should still install (same version: repair)"
grep -q "its SHA-256 is" "$TMP/out.log" || fail "without a .sha256 the log must print the file's SHA-256 to compare"
grep -q "installing it again" "$TMP/out.log" || fail "the same version from a file must say it installs again"
echo "--archive without a .sha256 prints its SHA-256; the same version is installed again (repair) -> PASS"

# --- refusals leave everything untouched -----------------------------------------------------------------------------------------------
make_release 0.3.3
before="$(tree_sum "$PB")"
refuse() {   # refuse REASON ARGS...: update.sh must fail with ERROR[REASON] and change nothing
    local reason="$1"; shift
    if PATH="$TMP/bin_none:$PATH" bash "$PB/update.sh" "$@" > "$TMP/out.log" 2>&1; then fail "this must be refused ($reason): $*"; fi
    grep -q "ERROR\[$reason\]" "$TMP/out.log" || fail "expected ERROR[$reason] for: $*"
    [[ "$(tree_sum "$PB")" == "$before" ]] || fail "a refused update ($reason) changed installed files"
    [[ ! -e "$PB/.plasbench-upgrade.lock" ]] || fail "the update lock stayed after a refusal ($reason)"
}
mkdir -p "$TMP/bad" && cp "$TMP/rel/plasbench-0.3.3.tar.gz" "$TMP/bad/plasbench-0.3.3.tar.gz"
printf '%064d  plasbench-0.3.3.tar.gz\n' 0 > "$TMP/bad/plasbench-0.3.3.tar.gz.sha256"
refuse checksum --archive "$TMP/bad/plasbench-0.3.3.tar.gz" --yes
echo "a bad checksum is refused before anything is replaced -> PASS"
cp "$TMP/rel/plasbench-0.3.3.tar.gz" "$TMP/bad/plasbench-latest.tar.gz"
refuse name --archive "$TMP/bad/plasbench-latest.tar.gz" --yes
cp "$TMP/rel/plasbench-0.3.3.tar.gz" "$TMP/bad/plasbench-0.3.3 (1).tar.gz"
refuse name --archive "$TMP/bad/plasbench-0.3.3 (1).tar.gz" --yes
refuse notfound --archive "$TMP/bad/plasbench-9.9.9.tar.gz" --yes
echo "a misnamed or missing file is refused -> PASS"
# a file named for 0.3.4 that holds 0.3.3 (a renamed file)
cp "$TMP/rel/plasbench-0.3.3.tar.gz" "$TMP/bad/plasbench-0.3.4.tar.gz"
mkdir -p "$TMP/mis/plasbench-0.3.4" && tar -xzf "$TMP/rel/plasbench-0.3.3.tar.gz" -C "$TMP/mis" && rm -rf "$TMP/mis/plasbench-0.3.4" && mv "$TMP/mis/plasbench-0.3.3" "$TMP/mis/plasbench-0.3.4"
( cd "$TMP/mis" && tar -czf "$TMP/bad/plasbench-0.3.4.tar.gz" plasbench-0.3.4 )
( cd "$TMP/bad" && sha256sum plasbench-0.3.4.tar.gz > plasbench-0.3.4.tar.gz.sha256 )
refuse name --archive "$TMP/bad/plasbench-0.3.4.tar.gz" --yes
echo "a file whose content is another version than its name is refused -> PASS"
# a tar with files outside plasbench-<version>/
mkdir -p "$TMP/evil/plasbench-0.3.5" && cp -r "$TMP/stage-0.3.3/plasbench-0.3.3/." "$TMP/evil/plasbench-0.3.5/" && printf '__version__ = "0.3.5"\n' > "$TMP/evil/plasbench-0.3.5/plasbench/__init__.py" && echo x > "$TMP/evil/stray.txt"
( cd "$TMP/evil" && tar -czf "$TMP/bad/plasbench-0.3.5.tar.gz" plasbench-0.3.5 stray.txt )
( cd "$TMP/bad" && sha256sum plasbench-0.3.5.tar.gz > plasbench-0.3.5.tar.gz.sha256 )
refuse extract --archive "$TMP/bad/plasbench-0.3.5.tar.gz" --yes
echo "not a tar at all" > "$TMP/bad/plasbench-0.3.6.tar.gz"
( cd "$TMP/bad" && sha256sum plasbench-0.3.6.tar.gz > plasbench-0.3.6.tar.gz.sha256 )
refuse extract --archive "$TMP/bad/plasbench-0.3.6.tar.gz" --yes
echo "an archive with files outside plasbench-<version>/, or no archive at all, is refused -> PASS"
# options that exclude each other
if bash "$PB/update.sh" --archive "$TMP/rel/plasbench-0.3.3.tar.gz" --version 0.3.3 > "$TMP/out.log" 2>&1; then fail "--archive with --version must be refused"; fi
# a download that fails (no such file on the server / no network): nothing replaced, the reason is named
fake_curl "$TMP/bin_033" "0.3.3"
if FAKE_CURL_FAIL=6 PATH="$TMP/bin_033:$PATH" bash "$PB/update.sh" --yes > "$TMP/out.log" 2>&1; then fail "a failed download must fail"; fi
grep -q "ERROR\[offline\]" "$TMP/out.log" && [[ "$(tree_sum "$PB")" == "$before" ]] || fail "a failed download must say offline and change nothing"
echo "a failed download is named and changes nothing -> PASS"
# a second update at the same time
sleep 30 & holder=$!
mkdir "$PB/.plasbench-upgrade.lock" && echo "$holder" > "$PB/.plasbench-upgrade.lock/pid"
refuse_lock() { if PATH="$TMP/bin_none:$PATH" bash "$PB/update.sh" --archive "$TMP/rel/plasbench-0.3.3.tar.gz" --yes > "$TMP/out.log" 2>&1; then fail "a second update must be refused"; fi; }
refuse_lock
grep -q "ERROR\[lock\]" "$TMP/out.log" || fail "the second update must name the lock"
[[ -d "$PB/.plasbench-upgrade.lock" ]] || fail "the running update's lock must not be removed by the refused one"
[[ "$(tree_sum "$PB")" == "$before" ]] || fail "a refused second update changed files"
kill "$holder" 2>/dev/null || true; wait "$holder" 2>/dev/null || true
rm -rf "$PB/.plasbench-upgrade.lock"
mkdir "$PB/.plasbench-upgrade.lock" && echo "999999" > "$PB/.plasbench-upgrade.lock/pid"
PATH="$TMP/bin_none:$PATH" bash "$PB/update.sh" --archive "$TMP/rel/plasbench-0.3.3.tar.gz" --yes > "$TMP/out.log" 2>&1 || fail "a lock left by a dead update must not block"
grep -q '0.3.3' "$PB/plasbench/__init__.py" || fail "the update after a dead lock did not install"
echo "only one update at a time; a stale lock does not block -> PASS"

# --- --rollback ------------------------------------------------------------------------------------------------------------------------
[[ -f "$PB/.plasbench-rollback/plasbench-0.3.2.tar.gz" ]] || fail "the update to 0.3.3 must have saved 0.3.2"
[[ ! -e "$PB/.plasbench-rollback/plasbench-0.3.1.tar.gz" ]] || fail "only the latest rollback copy is kept"
PATH="$TMP/bin_none:$PATH" bash "$PB/update.sh" --rollback --yes > "$TMP/out.log" 2>&1 || fail "--rollback should work"
grep -q '0.3.2' "$PB/plasbench/__init__.py" && [[ "$(cat "$PB/RELEASE_MARKER")" == "release 0.3.2" ]] || fail "--rollback did not restore 0.3.2"
grep -q "WARNING: 0.3.2 is OLDER" "$TMP/out.log" || fail "a rollback is announced as a downgrade"
[[ -f "$PB/studies/mine/results/keep.txt" ]] || fail "studies must survive a rollback"
[[ -f "$PB/.plasbench-rollback/plasbench-0.3.3.tar.gz" ]] || fail "a rollback saves the replaced release too (so it can be undone)"
rm -rf "$PB/.plasbench-rollback"
if PATH="$TMP/bin_none:$PATH" bash "$PB/update.sh" --rollback --yes > "$TMP/out.log" 2>&1; then fail "--rollback without a saved copy must fail"; fi
grep -q "ERROR\[notfound\]" "$TMP/out.log" || fail "--rollback without a copy must say so"
echo "--rollback restores the saved release, announces the downgrade, keeps studies, and says so when there is no copy -> PASS"

# --- --version over https only, with a size limit ---------------------------------------------------------------------------------------
make_release 0.3.7
: > "$TMP/curl_calls.log"
fake_curl "$TMP/bin_037" "0.3.7"
PATH="$TMP/bin_037:$PATH" bash "$PB/update.sh" --version 0.3.7 --yes > "$TMP/out.log" 2>&1 || fail "--version 0.3.7 should install"
grep -q '0.3.7' "$PB/plasbench/__init__.py" || fail "--version did not install 0.3.7"
grep -q "tar.gz" "$TMP/curl_calls.log" && ! grep -q "releases/latest" "$TMP/curl_calls.log" || fail "--version must download that release without asking for the latest"
while read -r line; do
    [[ -z "$line" ]] && continue
    [[ "$line" == *"--proto =https"* ]] || fail "every download must be https only: $line"
    [[ "$line" == *"https://github.com/ubeffiong/plasbench/"* || "$line" == *"https://api.github.com/"* ]] || fail "every download must go to GitHub: $line"
done < "$TMP/curl_calls.log"
grep -q -- "--max-filesize" "$TMP/curl_calls.log" || fail "the download needs a size limit"
grep -q "sha256" "$TMP/curl_calls.log" || fail "the checksum file must be downloaded too"
grep -q "checksum" "$TMP/out.log" || fail "the checksum must be verified"
PATH="$TMP/bin_037:$PATH" bash "$PB/update.sh" --version 0.3.7 --yes > "$TMP/out.log" 2>&1 || fail "installing the installed version again"
grep -q "already up to date" "$TMP/out.log" || fail "--version of the installed version must say it is up to date"
make_release 0.3.0
fake_curl "$TMP/bin_030b" "0.3.0"
PATH="$TMP/bin_030b:$PATH" bash "$PB/update.sh" --version 0.3.0 --yes > "$TMP/out.log" 2>&1 || fail "an explicit older --version should install"
grep -q "WARNING: 0.3.0 is OLDER than the installed 0.3.7" "$TMP/out.log" || fail "an older --version is announced as a downgrade"
if PATH="$TMP/bin_030b:$PATH" bash "$PB/update.sh" --version "0.3;rm -rf" > "$TMP/out.log" 2>&1; then fail "a version with shell characters must be refused"; fi
echo "--version downloads over https from GitHub only, with a size limit and the checksum; an older one is an announced downgrade; junk is refused -> PASS"

# --- the environment step failing is named, and the rollback copy is there --------------------------------------------------------------
make_release 0.3.8
if FAKE_INSTALL_FAIL=1 PATH="$TMP/bin_none:$PATH" bash "$PB/update.sh" --archive "$TMP/rel/plasbench-0.3.8.tar.gz" --yes > "$TMP/out.log" 2>&1; then fail "a failing installer must fail the update"; fi
grep -q "PHASE 5/6" "$TMP/out.log" && grep -q "no conda-family" "$TMP/out.log" || fail "the failure must show the environment phase and the reason"
[[ -f "$PB/.plasbench-rollback/plasbench-0.3.0.tar.gz" ]] || fail "the rollback copy must exist when the installer step fails"
echo "a failing environment step is shown at phase 5/6 with the rollback copy available -> PASS"

# --- the command line passes the options through -----------------------------------------------------------------------------------------
"$PY" - "$ROOT" "$TMP" <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from plasbench import cli

root, tmp = Path(sys.argv[1]), Path(sys.argv[2])
calls, verified = [], []
cli.run = lambda command, received_root, env=None: (calls.append(command), 0)[1]
cli.verify_after_upgrade = lambda r, *a, **k: (verified.append(r), 0)[1]


def run(*args):
    del calls[:], verified[:]
    try:
        cli.main(["--project-root", str(root), "upgrade", *args])
    except SystemExit as exc:
        assert exc.code in (0, None), exc.code
    return calls[0][2:], len(verified)


assert run("--check-only") == (["--check-only"], 0), "a check does not verify or repair the install"
assert run("--yes", "--version", "9.9.9") == (["--yes", "--version", "9.9.9"], 1)
assert run("--yes", "--rollback") == (["--yes", "--rollback"], 1)
archive = tmp / "plasbench-9.9.9.tar.gz"
archive.write_bytes(b"x")
args, n = run("--yes", "--archive", str(archive))
assert args == ["--yes", "--archive", str(archive.resolve())] and n == 1, args
assert run() == ([], 1)
print("plasbench upgrade passes --check-only, --version, --archive and --rollback to update.sh -> PASS")
PY

echo "ALL UPGRADE END-TO-END TESTS PASSED"
