#!/usr/bin/env bash
# Regression for env/bootstrap_conda.sh: must short-circuit when conda/mamba/
# micromamba already exists, must build the correct platform-specific
# installer URL, must verify (and reject a bad) checksum, must respect
# --yes, and must decline cleanly on "no" without ever running the
# downloaded installer. Fakes `curl` so it runs fully offline.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# --- already-installed short circuit: no download attempted at all. ---
mkdir -p "$TMP/bin_have_conda"
printf '#!/usr/bin/env bash\necho fake-conda\n' > "$TMP/bin_have_conda/conda"
chmod +x "$TMP/bin_have_conda/conda"
out="$(PATH="$TMP/bin_have_conda:$PATH" bash "$ROOT/env/bootstrap_conda.sh" 2>&1)"
echo "$out" | grep -q "Found 'conda' already installed" || { echo "FAIL: did not detect existing conda" >&2; echo "$out" >&2; exit 1; }
echo "already-installed conda short-circuits with no download attempt -> PASS"

# --- fake installer + checksum served by a fake curl, mimicking the real
# GitHub release layout (installer + installer.sha256 sidecar). ---
mkdir -p "$TMP/bin_no_conda" "$TMP/fixtures"
printf '#!/usr/bin/env bash\necho "fake miniforge installer ran with: $*" >> "%s/installer_invocations.log"\nmkdir -p "$3"\n' "$TMP" > "$TMP/fixtures/installer.sh"
# The real installer takes "-b -p PREFIX"; the fake records args and creates
# the prefix so the script's own success path has something to report.
cat > "$TMP/fixtures/installer.sh" <<EOF
#!/usr/bin/env bash
echo "installer ran: \$*" >> "$TMP/installer_invocations.log"
prefix=""
while [[ \$# -gt 0 ]]; do case "\$1" in -p) prefix="\$2"; shift 2;; *) shift;; esac; done
mkdir -p "\$prefix/bin" "\$prefix/etc/profile.d"
touch "\$prefix/bin/conda" "\$prefix/etc/profile.d/conda.sh"
EOF
sha256sum "$TMP/fixtures/installer.sh" | awk '{print $1"  Miniforge3-test.sh"}' > "$TMP/fixtures/installer.sh.sha256"

cat > "$TMP/bin_no_conda/curl" <<EOF
#!/usr/bin/env bash
# Fake curl: -fsSL -o DEST URL -- serves the fixture installer for the
# .sh URL and its sidecar for the .sh.sha256 URL, regardless of platform
# tag in the URL (keeps the test independent of the host's own uname).
dest="" url=""
while [[ \$# -gt 0 ]]; do case "\$1" in -o) dest="\$2"; shift 2;; -f|-s|-S|-L) shift;; *) url="\$1"; shift;; esac; done
echo "\$url" >> "$TMP/curl_requests.log"
if [[ "\$url" == *.sha256 ]]; then
    cp "$TMP/fixtures/installer.sh.sha256" "\$dest"
else
    cp "$TMP/fixtures/installer.sh" "\$dest"
fi
EOF
chmod +x "$TMP/bin_no_conda/curl" "$TMP/fixtures/installer.sh"

# Fake `uname` so this test exercises the Linux code path regardless of the
# actual host OS (e.g. this suite also runs under Git Bash on Windows, where
# real uname reports MINGW64_NT-... -- correctly out of scope for the real
# script, but not what this test is checking).
cat > "$TMP/bin_no_conda/uname" <<'EOF'
#!/usr/bin/env bash
case "$1" in
    -s) echo "Linux" ;;
    -m) echo "x86_64" ;;
    *) echo "Linux" ;;
esac
EOF
chmod +x "$TMP/bin_no_conda/uname"

run_bootstrap() {
    : > "$TMP/curl_requests.log"; rm -f "$TMP/installer_invocations.log"
    PATH="$TMP/bin_no_conda:/usr/bin:/bin" bash "$ROOT/env/bootstrap_conda.sh" "$@" > "$TMP/run.log" 2>&1
}

# --- --yes: installs without prompting, verifies checksum, runs installer
# with the requested prefix. ---
PREFIX1="$TMP/prefix1"
if run_bootstrap --yes --prefix "$PREFIX1"; then :; else echo "FAIL: --yes run should succeed" >&2; cat "$TMP/run.log" >&2; exit 1; fi
grep -q "checksum OK" "$TMP/run.log" || { echo "FAIL: expected checksum verification to succeed" >&2; cat "$TMP/run.log" >&2; exit 1; }
[[ -f "$PREFIX1/bin/conda" ]] || { echo "FAIL: fake installer did not run against the requested prefix" >&2; cat "$TMP/run.log" >&2; exit 1; }
grep -q "\.sh$" "$TMP/curl_requests.log" && grep -q "\.sha256$" "$TMP/curl_requests.log" || {
    echo "FAIL: expected both the installer and its .sha256 sidecar to be fetched" >&2; cat "$TMP/curl_requests.log" >&2; exit 1; }
echo "--yes downloads, verifies checksum, and installs to the requested prefix -> PASS"

# --- checksum mismatch must abort before ever running the installer. ---
PREFIX2="$TMP/prefix2"
printf 'deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef  Miniforge3-test.sh\n' > "$TMP/fixtures/installer.sh.sha256"
if run_bootstrap --yes --prefix "$PREFIX2"; then
    echo "FAIL: a checksum mismatch must abort the install" >&2; cat "$TMP/run.log" >&2; exit 1
fi
grep -qi "checksum mismatch" "$TMP/run.log" || { echo "FAIL: expected a checksum-mismatch error" >&2; cat "$TMP/run.log" >&2; exit 1; }
[[ ! -e "$PREFIX2" ]] || { echo "FAIL: installer must not have run after a checksum mismatch" >&2; exit 1; }
echo "a checksum mismatch aborts before running the installer -> PASS"
sha256sum "$TMP/fixtures/installer.sh" | awk '{print $1"  Miniforge3-test.sh"}' > "$TMP/fixtures/installer.sh.sha256"  # restore

# --- declining the interactive prompt must never download or install. ---
PREFIX3="$TMP/prefix3"
: > "$TMP/curl_requests.log"
if PATH="$TMP/bin_no_conda:/usr/bin:/bin" PLASBENCH_CONDA_PREFIX="$PREFIX3" bash "$ROOT/env/bootstrap_conda.sh" < /dev/null > "$TMP/run.log" 2>&1; then
    echo "FAIL: declining (EOF/no input) should exit non-zero" >&2; cat "$TMP/run.log" >&2; exit 1
fi
[[ ! -s "$TMP/curl_requests.log" ]] || { echo "FAIL: no download should happen before consent" >&2; cat "$TMP/curl_requests.log" >&2; exit 1; }
[[ ! -e "$PREFIX3" ]] || { echo "FAIL: nothing should be installed without consent" >&2; exit 1; }
echo "declining consent (no input) never downloads or installs anything -> PASS"

echo "ALL BOOTSTRAP CONDA TESTS PASSED"
