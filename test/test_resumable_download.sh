#!/usr/bin/env bash
# scripts/lib.sh resumable_download (used for the Platon and MOB-suite databases):
#   * a connection that drops partway keeps the bytes already received and the
#     next attempt continues from there (curl -C -), never from zero;
#   * the finished file is renamed from .part only when its size is right;
#   * a finished file is not downloaded again;
#   * while the host is unreachable it waits, then continues when it is back.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin"
head -c 300000 /dev/urandom > "$TMP/source.bin"
WANT="$(stat -c %s "$TMP/source.bin")"

# Fake curl: honours -C - by appending from the current .part size; the first
# call delivers only 100000 bytes and then "drops the connection" (exit 18).
cat > "$TMP/bin/curl" <<EOF
#!/usr/bin/env bash
echo "curl \$*" >> "$TMP/curl.log"
out=""; resume=0
while [[ \$# -gt 0 ]]; do case "\$1" in -o) out="\$2"; shift;; -C) resume=1; shift;; esac; shift; done
have=0; [[ \$resume -eq 1 && -f "\$out" ]] && have=\$(stat -c %s "\$out")
n=\$(grep -c . "$TMP/curl.log")
if [[ \$n -eq 1 ]]; then tail -c +\$((have+1)) "$TMP/source.bin" | head -c 100000 >> "\$out"; exit 18; fi
tail -c +\$((have+1)) "$TMP/source.bin" >> "\$out"
EOF
chmod +x "$TMP/bin/curl"

dl() { PATH="$TMP/bin:$PATH" PLASBENCH_RETRY_SLEEP=0 bash -c "source '$ROOT/scripts/lib.sh'; resumable_download \"\$@\"" _ "$@"; }

PLASBENCH_ASSUME_ONLINE=1 dl "https://example.org/data.tar.gz" "$TMP/out/data.tar.gz" "$WANT" > "$TMP/run1.log" 2>&1 \
    || { echo "FAIL: download did not complete" >&2; cat "$TMP/run1.log" "$TMP/curl.log" >&2; exit 1; }
cmp -s "$TMP/source.bin" "$TMP/out/data.tar.gz" || { echo "FAIL: resumed file differs from the source" >&2; exit 1; }
[[ ! -e "$TMP/out/data.tar.gz.part" ]] || { echo "FAIL: .part left behind" >&2; exit 1; }
[[ "$(grep -c -- '-C -' "$TMP/curl.log")" -eq 2 ]] || { echo "FAIL: second attempt did not resume" >&2; cat "$TMP/curl.log" >&2; exit 1; }
grep -q "resuming at 0 MB" "$TMP/run1.log" || true
grep -q "keeping" "$TMP/run1.log" || { echo "FAIL: interruption not reported" >&2; cat "$TMP/run1.log" >&2; exit 1; }
echo "a dropped connection resumes from the saved bytes and yields the identical file -> PASS"

: > "$TMP/curl.log"
PLASBENCH_ASSUME_ONLINE=1 dl "https://example.org/data.tar.gz" "$TMP/out/data.tar.gz" "$WANT" > "$TMP/run2.log" 2>&1
[[ ! -s "$TMP/curl.log" ]] && grep -q "already downloaded" "$TMP/run2.log" \
    || { echo "FAIL: a finished file was downloaded again" >&2; exit 1; }
echo "a finished download is not repeated -> PASS"

# Offline, then back: wait_online pauses and continues. net_online is replaced so
# the "network" comes back on the third probe.
out="$(PATH="$TMP/bin:$PATH" PLASBENCH_ONLINE_POLL=0 bash -c "
source '$ROOT/scripts/lib.sh'
n=0; net_online() { n=\$((n+1)); [[ \$n -ge 3 ]]; }
wait_online example.org && echo RESUMED")"
[[ "$out" == *"download paused"* && "$out" == *"internet is back"* && "$out" == *RESUMED* ]] \
    || { echo "FAIL: offline wait did not pause and resume: $out" >&2; exit 1; }
echo "while offline the download pauses, and continues when the connection returns -> PASS"
echo "ALL RESUMABLE DOWNLOAD TESTS PASSED"
