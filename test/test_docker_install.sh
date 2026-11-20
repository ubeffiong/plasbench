#!/usr/bin/env bash
# `plasbench install-tools docker` (env/install_tools.sh -> python/docker_setup.py) with FAKE programs on PATH: a fake docker whose answers are chosen per case, a fake winget.exe,
# powershell.exe and brew that record their argument lists, and a fake sudo that must never be called. No real Docker is installed or started.
# Exit codes: 0 verified working, 20 steps handed to you, 21 consent needed, 1 failed.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
if [[ "$(uname -s)" != "Linux" ]]; then echo "SKIP: fake .exe programs are shell scripts and only run on Linux (CI runs this)"; exit 0; fi
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin" "$TMP/home" "$TMP/state"
LOG="$TMP/calls.log"

# fake docker: FAKE_DOCKER_MODE = ready | down | perm | absent | wslstub
cat > "$TMP/bin/docker" <<'EOF'
#!/usr/bin/env bash
case "${FAKE_DOCKER_MODE:-absent}" in
  ready) case "$1" in
           --version) echo "Docker version 27.3.1, build ce12230"; exit 0;;
           info) printf 'Client:\n Version: 27.3.1\nServer:\n Server Version: 27.3.1\n'; exit 0;;
           context) echo "default"; exit 0;;
           run) echo "Hello from Docker!"; exit 0;;
         esac;;
  down) case "$1" in
          --version) echo "Docker version 27.3.1, build ce12230"; exit 0;;
          *) echo "Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?" >&2; exit 1;;
        esac;;
  perm) case "$1" in
          --version) echo "Docker version 27.3.1, build ce12230"; exit 0;;
          *) echo "permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock: connect: permission denied" >&2; exit 1;;
        esac;;
  wslstub) echo "The command 'docker' could not be found in this WSL 2 distro. We recommend to activate the WSL integration in Docker Desktop settings." >&2; exit 127;;
  *) echo "docker: command not found" >&2; exit 127;;
esac
exit 1
EOF
for exe in winget.exe brew; do
    cat > "$TMP/bin/$exe" <<EOF
#!/usr/bin/env bash
printf '%s\n' "$exe \$*" >> "$LOG"
echo "fake $exe output"
exit "\${FAKE_INSTALLER_EXIT:-0}"
EOF
done
cat > "$TMP/bin/powershell.exe" <<EOF
#!/usr/bin/env bash
printf '%s\n' "powershell.exe \$*" >> "$LOG"
exit 0
EOF
cat > "$TMP/bin/sudo" <<EOF
#!/usr/bin/env bash
printf '%s\n' "SUDO WAS CALLED \$*" >> "$LOG"
exit 1
EOF
chmod +x "$TMP"/bin/*

ok=1
check() { if [[ "$2" == "yes" ]]; then echo "  ok    $1"; else echo "  FAIL  $1"; ok=0; fi; }
yn() { if "$@"; then echo yes; else echo no; fi; }

# docker_cmd PLATFORM DOCKER_MODE [args...]: run install-tools docker with a pretend platform; output in $TMP/out, status in $code
docker_cmd() {
    local platform="$1" mode="$2"; shift 2
    : > "$LOG"
    env -u PLASBENCH_OFFLINE HOME="$TMP/home" PATH="$TMP/bin:/usr/bin:/bin" PLASBENCH_ASSUME_ONLINE=1 PLASBENCH_STATE_DIR="$TMP/state" PLASBENCH_DOCKER_WAIT=0 \
        PLASBENCH_DOCKER_PLATFORM="$platform" FAKE_DOCKER_MODE="$mode" bash "$ROOT/env/install_tools.sh" "$@" docker > "$TMP/out" 2>&1
    code=$?
}

docker_cmd linux ready;
check "Docker working: exit 0, and nothing was installed" "$(yn test "$code" -eq 0 -a ! -s "$LOG")"
check "the verified version and context are recorded for plasbench check and the manifest" "$(yn grep -q '"version": "27.3.1"' "$TMP/state/docker_status.json")"
check "plasbench check line says ready (optional)" "$(PATH="$TMP/bin:/usr/bin:/bin" FAKE_DOCKER_MODE=ready PLASBENCH_DOCKER_PLATFORM=linux python3 "$ROOT/python/docker_setup.py" check-line | grep -q 'docker (optional): ready' && echo yes || echo no)"

docker_cmd wsl2 absent
check "WSL2, not installed, no --yes: exit 21 (consent needed)" "$(yn test "$code" -eq 21)"
check "  ... winget was not started" "$(yn test ! -s "$LOG")"
check "  ... the plan names winget, who approves (UAC) and the licence" "$(yn grep -q 'Windows asks you to approve' "$TMP/out" && grep -q 'cannot accept the licence for you' "$TMP/out")"

docker_cmd wsl2 absent --yes
check "WSL2 with --yes: winget.exe runs with the exact argument list" "$(yn grep -qx 'winget.exe install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements' "$LOG")"
check "  ... Docker is not ready yet, so exit 20 (waiting for you)" "$(yn test "$code" -eq 20)"
check "  ... 'Waiting for you to finish in Docker Desktop' and the WSL integration step" "$(yn grep -q 'Waiting for you to finish in Docker Desktop' "$TMP/out" && grep -q 'WSL integration' "$TMP/out")"
check "  ... only winget was started (one line in the log)" "$(yn test "$(wc -l < "$LOG")" -eq 1)"

: > "$LOG"
env -u PLASBENCH_OFFLINE HOME="$TMP/home" PATH="$TMP/bin:/usr/bin:/bin" PLASBENCH_ASSUME_ONLINE=1 PLASBENCH_STATE_DIR="$TMP/state" PLASBENCH_DOCKER_WAIT=0 PLASBENCH_DOCKER_PLATFORM=wsl2 \
    FAKE_DOCKER_MODE=absent FAKE_INSTALLER_EXIT=1602 bash "$ROOT/env/install_tools.sh" --yes docker > "$TMP/out" 2>&1; code=$?
check "UAC declined (winget exit 1602): exit 1 with a plain sentence" "$(yn test "$code" -eq 1 && grep -q 'declined or closed' "$TMP/out")"

docker_cmd macos absent --yes
check "macOS with --yes: brew install --cask docker-desktop" "$(yn grep -qx 'brew install --cask docker-desktop' "$LOG")"
check "  ... exit 20 and the open -a Docker step" "$(yn test "$code" -eq 20 && grep -q 'open -a Docker' "$TMP/out")"

docker_cmd linux absent --yes
check "Linux: exit 20 even with --yes (a sudo script is handed over, never run)" "$(yn test "$code" -eq 20)"
check "  ... the script is printed, sudo was never called" "$(yn grep -q 'script: official' "$TMP/out" && ! grep -q 'SUDO WAS CALLED' "$LOG" && test ! -s "$LOG")"
check "  ... no piped shell installer anywhere in the output" "$(yn bash -c '! grep -E "\| *(sudo )?(ba)?sh|get\.docker\.com" "$0"' "$TMP/out")"

docker_cmd linux perm
check "permission denied: exit 20 with the docker group step" "$(yn test "$code" -eq 20 && grep -q 'usermod -aG docker' "$TMP/out")"
docker_cmd linux down
check "daemon stopped: exit 20 with the start command" "$(yn test "$code" -eq 20 && grep -q 'systemctl start docker' "$TMP/out")"
docker_cmd wsl2 wslstub
check "WSL integration off: exit 20 with the Docker Desktop setting to turn on" "$(yn test "$code" -eq 20 && grep -q 'WSL integration' "$TMP/out" && test ! -s "$LOG")"
docker_cmd container absent --yes
check "inside a container: exit 20, Docker-in-Docker said to be out of scope" "$(yn test "$code" -eq 20 && grep -q 'out of scope' "$TMP/out")"

PLASBENCH_INSTALL_DRY_RUN=1 docker_cmd wsl2 absent --yes
check "dry run: exit 0, the plan is printed, nothing is started" "$(yn test "$code" -eq 0 -a ! -s "$LOG" && grep -q 'dry run' "$TMP/out")"

: > "$LOG"
env -u PLASBENCH_ASSUME_ONLINE HOME="$TMP/home" PATH="$TMP/bin:/usr/bin:/bin" PLASBENCH_OFFLINE=1 PLASBENCH_STATE_DIR="$TMP/state" PLASBENCH_DOCKER_PLATFORM=wsl2 FAKE_DOCKER_MODE=absent \
    bash "$ROOT/env/install_tools.sh" --yes docker > "$TMP/out" 2>&1; code=$?
check "offline: the winget route is refused before anything runs (netcheck services winget, docker)" "$(yn test "$code" -ne 0 -a "$code" -ne 20 -a ! -s "$LOG" && grep -qi 'internet' "$TMP/out")"
env -u PLASBENCH_ASSUME_ONLINE HOME="$TMP/home" PATH="$TMP/bin:/usr/bin:/bin" PLASBENCH_OFFLINE=1 PLASBENCH_STATE_DIR="$TMP/state" PLASBENCH_DOCKER_PLATFORM=linux FAKE_DOCKER_MODE=absent \
    bash "$ROOT/env/install_tools.sh" --yes docker > "$TMP/out" 2>&1; code=$?
check "offline: a hand-off route needs no internet (exit 20)" "$(yn test "$code" -eq 20)"

# scripts/docker_run.sh says why, instead of a bare 'command not found'
env HOME="$TMP/home" PATH="$TMP/bin:/usr/bin:/bin" PLASBENCH_STATE_DIR="$TMP/state" PLASBENCH_DOCKER_PLATFORM=linux FAKE_DOCKER_MODE=down bash "$ROOT/scripts/docker_run.sh" plasbench demo > "$TMP/out" 2>&1; code=$?
check "docker_run.sh with the daemon stopped: exit 1, the same diagnosis, the install-tools hint" "$(yn test "$code" -eq 1 && grep -q 'daemon' "$TMP/out" && grep -q 'plasbench install-tools docker' "$TMP/out")"
env HOME="$TMP/home" PATH="$TMP/bin:/usr/bin:/bin" PLASBENCH_STATE_DIR="$TMP/state" PLASBENCH_DOCKER_PLATFORM=linux FAKE_DOCKER_MODE=absent bash "$ROOT/scripts/docker_run.sh" plasbench demo > "$TMP/out" 2>&1; code=$?
check "docker_run.sh with Docker missing: exit 1, 'not installed' (not a bare command-not-found)" "$(yn test "$code" -eq 1 && grep -q 'not installed' "$TMP/out")"

[[ "$ok" -eq 1 ]] && echo "ALL DOCKER INSTALL TESTS PASSED" || { echo "DOCKER INSTALL TESTS FAILED"; exit 1; }
