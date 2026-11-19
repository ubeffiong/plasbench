#!/usr/bin/env bash
# Hermetic tests of python/source_install.py: FAKE conda and pip on PATH and a LOCAL bare git repository as the "upstream". Nothing is downloaded.
# Covers: consent needed without --yes, the pinned commit checked out and proved with git rev-parse, a floating branch refused, the dependency install
# calls, the verification command, the provenance file, cleanup at every failing step, idempotent re-run, upgrade when the pin changes (and the old
# install kept when the upgrade fails), the verified-manual exit 20, and the exit codes through env/install_tools.sh.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export PLASBENCH_ASSUME_ONLINE=1 PLASBENCH_SOURCE_TEST_OVERRIDES=1
PY="$(command -v python3 || command -v python)"
ok=1
check() { if [[ "$2" == "yes" ]]; then echo "  ok    $1"; else echo "  FAIL  $1"; ok=0; tail -4 "$TMP/out" 2>/dev/null | cut -c1-200; ls -a "$TMP/envs" 2>/dev/null; fi; }
yn() { if "$@" >/dev/null 2>&1; then echo yes; else echo no; fi; }

# ---- the fake upstream: a local repository with a tool, a conda file and a requirements file --------------------------------------------------------------
UP="$TMP/upstream-work"; BARE="$TMP/upstream.git"
mkdir -p "$UP/envs" && cd "$UP" || exit 1
git init -q -b main . && git config user.email t@example.invalid && git config user.name t && git config commit.gpgsign false
printf 'name: fake\n' > envs/fake.yaml
printf 'fakedep==1.0\n' > requirements.txt
printf 'import sys\nprint("usage: faketool v1 %%s" %% " ".join(sys.argv[1:]))\n' > tool.py
git add . && git commit -q -m one && SHA1="$(git rev-parse HEAD)"
git tag v1
printf 'import sys\nprint("usage: faketool v2 %%s" %% " ".join(sys.argv[1:]))\n' > tool.py
git commit -q -am two && SHA2="$(git rev-parse HEAD)"
git clone -q --bare "$UP" "$BARE" && cd "$ROOT" || exit 1

# ---- fake conda (creates the prefix with a fake pip and python) and a fake solver log -------------------------------------------------------------------------
mkdir -p "$TMP/bin"
cat > "$TMP/bin/conda" <<EOF
#!/usr/bin/env bash
echo "conda \$*" >> "$TMP/calls.log"
[[ "\${1:-}" == "--version" ]] && { echo "conda 0.0-fake"; exit 0; }
[[ -n "\${FAKE_CONDA_FAIL:-}" ]] && exit 1
prefix=""; prev=""
for a in "\$@"; do [[ "\$prev" == "-p" ]] && prefix="\$a"; prev="\$a"; done
[[ -n "\$prefix" ]] || exit 0
mkdir -p "\$prefix/bin"
printf '#!/bin/sh\necho "pip \$*" >> "$TMP/calls.log"\n[ -n "\$FAKE_PIP_FAIL" ] && exit 1\nexit 0\n' > "\$prefix/bin/pip"
printf '#!/bin/sh\nexec "$PY" "\$@"\n' > "\$prefix/bin/python"
chmod +x "\$prefix/bin/pip" "\$prefix/bin/python"
exit 0
EOF
chmod +x "$TMP/bin/conda"
export PATH="$TMP/bin:$PATH"

MAIN="$TMP/envs/plasbench"; mkdir -p "$MAIN/bin"
leftovers() { find "$TMP/envs" -maxdepth 1 \( -name '.plasbench-*' -o -name '*previous*' \) | grep -q . ; }

# make_registry FILE COMMIT EXPECT : a registry with one installable profile, "faketool"
make_registry() {
    "$PY" - "$1" "$2" "$3" "$BARE" <<'PYEOF'
import json, sys
path, commit, expect = sys.argv[1:4]
entry = {"tools": ["faketool"], "mode": "source", "repo": "https://example.invalid/faketool.git", "ref": "v1", "commit": commit, "licence": "MIT (test)",
         "download_mb": 1, "disk_gb": 1, "minutes": "1 (test)",
         "env": {"python": None, "steps": [{"type": "conda_file", "path": "envs/fake.yaml"}, {"type": "pip_requirements", "path": "requirements.txt"}, {"type": "pip_install", "target": "."}]},
         "commands": {"faketool": {"kind": "script", "path": "tool.py", "interpreter": "python"}},
         "verify": {"argv": ["faketool", "--help"], "expect": expect, "why": "the fake tool prints its usage"},
         "inputs": [], "note": "", "sources": ["https://example.invalid/tags"], "researched": "2026-11-19"}
json.dump({"schema": 1, "profiles": {"faketool": entry}}, open(path, "w"))
PYEOF
}
install_it() {  # REGISTRY [extra args]
    local reg="$1"; shift
    PLASBENCH_SOURCE_URL_FAKETOOL="${FAKE_URL:-$BARE}" "$PY" "$ROOT/python/source_install.py" install faketool --registry "$reg" --main-prefix "$MAIN" --solver conda "$@" < /dev/null
}
INSTALL="$TMP/envs/plasbench-faketool"

make_registry "$TMP/r1.json" "$SHA1" "usage"
make_registry "$TMP/r2.json" "$SHA2" "usage"
check "the test registry validates" "$(yn "$PY" "$ROOT/python/source_install.py" validate --registry "$TMP/r1.json")"

# 1. consent: without --yes (no terminal) nothing is installed and the exit code is 21
install_it "$TMP/r1.json" > "$TMP/out" 2>&1; code=$?
check "no --yes: exit 21 (consent needed), not a failure" "$([[ $code -eq 21 ]] && echo yes || echo no)"
check "the plan names the repository, the pinned commit, the size and the licence" "$(grep -q "Source" "$TMP/out" && grep -q "$SHA1" "$TMP/out" && grep -q "about 1 MB" "$TMP/out" && grep -q "MIT (test)" "$TMP/out" && echo yes || echo no)"
check "no --yes: nothing was cloned, built or exposed" "$([[ ! -e $INSTALL && ! -e $MAIN/bin/faketool && ! -s $TMP/calls.log ]] && echo yes || echo no)"

# 2. a first install
install_it "$TMP/r1.json" --yes > "$TMP/out" 2>&1; code=$?
check "--yes installs (exit 0)" "$([[ $code -eq 0 ]] && echo yes || echo no)"; [[ $code -eq 0 ]] || cat "$TMP/out"
check "the pinned commit is checked out (git rev-parse HEAD)" "$([[ "$(git -C "$INSTALL/plasbench-src" rev-parse HEAD)" == "$SHA1" ]] && echo yes || echo no)"
check "the conda environment is created at the isolated prefix from the checkout's own file" "$(grep -q "conda env create -p .*plasbench-faketool -f .*fake.yaml" "$TMP/calls.log" && echo yes || echo no)"
check "the dependency files are installed with pip into that environment" "$(grep -q 'pip install -r .*requirements.txt' "$TMP/calls.log" && grep -q 'pip install \.' "$TMP/calls.log" && echo yes || echo no)"
check "the tool runs through its wrapper in the main environment" "$([[ "$("$MAIN/bin/faketool" --help)" == *"usage: faketool v1"* ]] && echo yes || echo no)"
check "the provenance file records revision, source, time, environment and hashes" "$("$PY" - "$INSTALL/plasbench-install.json" "$SHA1" <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
need = ("commit", "repo", "ref", "installed_at", "env_prefix", "source_tree_sha256", "dependency_files_sha256", "dependency_versions", "solver_version", "verify", "tree")
ok = d["commit"] == sys.argv[2] and all(k in d for k in need) and len(d["source_tree_sha256"]) == 64 and all(len(v) == 64 for v in d["dependency_files_sha256"].values())
print("yes" if ok else "no")
PYEOF
)"
check "the wrapper names the provenance file (the run manifest and check read it)" "$(grep -q 'PlasBench source install: faketool' "$MAIN/bin/faketool" && echo yes || echo no)"
check "command-info reads the revision back from the wrapper" "$(PATH="$MAIN/bin:$PATH" "$PY" "$ROOT/python/source_install.py" command-info faketool | grep -q "$SHA1" && echo yes || echo no)"
check "nothing is left behind (staging, previous)" "$(leftovers && echo no || echo yes)"

# 3. idempotent
: > "$TMP/calls.log"
install_it "$TMP/r1.json" --yes > "$TMP/out" 2>&1; code=$?
check "a second run says it is already installed at the pinned revision" "$([[ $code -eq 0 ]] && grep -q 'already installed at the pinned revision' "$TMP/out" && echo yes || echo no)"
check "the second run solved and installed nothing" "$(grep -qE 'conda (env )?create|pip install' "$TMP/calls.log" && echo no || echo yes)"

# 4. a floating branch is refused; an unknown revision leaves nothing behind
"$PY" - "$TMP/r1.json" "$TMP/rbranch.json" <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1])); d["profiles"]["faketool"]["commit"] = "main"; json.dump(d, open(sys.argv[2], "w"))
PYEOF
rm -rf "$INSTALL" "$MAIN/bin/faketool"
install_it "$TMP/rbranch.json" --yes > "$TMP/out" 2>&1; code=$?
check "a branch name in place of a commit is refused (nothing cloned)" "$([[ $code -ne 0 && ! -e $INSTALL ]] && grep -qi '40-character' "$TMP/out" && echo yes || echo no)"
make_registry "$TMP/rbad.json" "0123456789abcdef0123456789abcdef01234567" "usage"
install_it "$TMP/rbad.json" --yes > "$TMP/out" 2>&1; code=$?
check "a commit that is not upstream fails with a precise message and leaves nothing" "$([[ $code -eq 1 && ! -e $INSTALL && ! -e $MAIN/bin/faketool ]] && grep -q 'is not in' "$TMP/out" && ! leftovers && echo yes || echo no)"

# 5. cleanup at each failing step
FAKE_URL="$TMP/does-not-exist.git" install_it "$TMP/r1.json" --yes > "$TMP/out" 2>&1; code=$?
check "a failed clone: exit 1, nothing left" "$([[ $code -eq 1 && ! -e $INSTALL && ! -e $MAIN/bin/faketool ]] && ! leftovers && echo yes || echo no)"
FAKE_CONDA_FAIL=1 install_it "$TMP/r1.json" --yes > "$TMP/out" 2>&1; code=$?
check "a failed conda step: exit 1, the half-built environment is removed" "$([[ $code -eq 1 && ! -e $INSTALL && ! -e $MAIN/bin/faketool ]] && ! leftovers && echo yes || echo no)"
FAKE_PIP_FAIL=1 install_it "$TMP/r1.json" --yes > "$TMP/out" 2>&1; code=$?
check "a failed pip step: exit 1, the environment and checkout are removed" "$([[ $code -eq 1 && ! -e $INSTALL && ! -e $MAIN/bin/faketool ]] && ! leftovers && echo yes || echo no)"
make_registry "$TMP/rverify.json" "$SHA1" "this text is never printed"
install_it "$TMP/rverify.json" --yes > "$TMP/out" 2>&1; code=$?
check "a failed verification: exit 1, nothing exposed, nothing left" "$([[ $code -eq 1 && ! -e $INSTALL && ! -e $MAIN/bin/faketool ]] && grep -q 'verification failed' "$TMP/out" && ! leftovers && echo yes || echo no)"

# 6. upgrade when the pin changes; a failing upgrade keeps the old install
install_it "$TMP/r1.json" --yes > /dev/null 2>&1
FAKE_CONDA_FAIL=1 install_it "$TMP/r2.json" --yes > "$TMP/out" 2>&1; code=$?
check "an upgrade that fails: exit 1 and the old install still works" "$([[ $code -eq 1 && "$("$MAIN/bin/faketool" --help)" == *"v1"* && "$(git -C "$INSTALL/plasbench-src" rev-parse HEAD)" == "$SHA1" ]] && ! leftovers && echo yes || echo no)"
install_it "$TMP/r2.json" --yes > "$TMP/out" 2>&1; code=$?
check "the pin changed: the new revision is installed" "$([[ $code -eq 0 && "$(git -C "$INSTALL/plasbench-src" rev-parse HEAD)" == "$SHA2" && "$("$MAIN/bin/faketool" --help)" == *"v2"* ]] && grep -q 'Upgrade' "$TMP/out" && ! leftovers && echo yes || echo no)"

# 7. the real registry: valid, every pin 40-hex, every URL https; manual profiles exit 20 with evidence; consent through the installer script
check "config/source_tools.json validates" "$(yn "$PY" "$ROOT/python/source_install.py" validate)"
"$PY" "$ROOT/python/tool_installer_registry.py" resolve plsmd > "$TMP/out" 2>&1; code=$?
check "plsmd resolves to exit 20 with its evidence and a recipe" "$([[ $code -eq 20 ]] && grep -q 'Checked against upstream' "$TMP/out" && grep -q 'Steps:' "$TMP/out" && echo yes || echo no)"
mkdir -p "$TMP/conda/envs/plasbench"
PATH="$TMP/bin:$PATH" CONDA_PREFIX="$TMP/conda/envs/plasbench" bash "$ROOT/env/install_tools.sh" --env plasbench gplas2 < /dev/null > "$TMP/out" 2>&1; code=$?
check "install-tools gplas2 without --yes: exit 21, plan shown, nothing cloned" "$([[ $code -eq 21 ]] && grep -q '9ec35cf6674c41ad91afc582dcbe9b2eee9161b0' "$TMP/out" && grep -q 'gitlab.com/mmb-umcu/gplas2' "$TMP/out" && ! grep -q 'cloning' "$TMP/out" && echo yes || echo no)"
PATH="$TMP/bin:$PATH" CONDA_PREFIX="$TMP/conda/envs/plasbench" bash "$ROOT/env/install_tools.sh" --env plasbench ppr-meta < /dev/null > "$TMP/out" 2>&1; code=$?
check "install-tools ppr-meta: exit 20 and no ERROR line" "$([[ $code -eq 20 ]] && ! grep -q 'ERROR' "$TMP/out" && echo yes || echo no)"

[[ "$ok" -eq 1 ]] && echo "ALL SOURCE INSTALL TESTS PASSED" || { echo "SOURCE INSTALL TESTS FAILED"; tail -30 "$TMP/out"; exit 1; }
