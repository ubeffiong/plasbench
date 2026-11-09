#!/usr/bin/env bash
# MOB-suite is installed into its own pinned environment, never the main one
# (its pandas<=1.5.3 pin cannot co-exist with the main environment, where
# mob_recon then crashes at start). With a fake conda:
#   * `install_tools.sh reconstruction` installs platon into the main env and
#     creates <env>-mobsuite with the pinned spec for mob_suite;
#   * mob_recon / mob_typer / mob_cluster / mob_init wrappers in the main env's
#     bin/ run the separate environment's programs;
#   * scripts/lib.sh mobsuite_db_dir follows the wrapper to that environment's
#     database, not to a copy importable from the main interpreter.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

BASE="$TMP/base"; MAIN="$BASE/envs/plasbench"; MOB="$BASE/envs/plasbench-mobsuite"
mkdir -p "$TMP/bin" "$MAIN/bin"
cat > "$TMP/bin/conda" <<EOF
#!/usr/bin/env bash
echo "conda \$*" >> "$TMP/conda.log"
case "\$1" in
  info) echo "$BASE" ;;
  create)
    prefix=""; while [[ \$# -gt 0 ]]; do [[ "\$1" == "-p" ]] && prefix="\$2"; shift; done
    mkdir -p "\$prefix/bin" "\$prefix/lib/python3.10/site-packages/mob_suite/databases"
    echo ok > "\$prefix/lib/python3.10/site-packages/mob_suite/databases/status.txt"
    for c in mob_recon mob_typer mob_cluster mob_init; do
      printf '#!/bin/sh\necho "%s 3.1.9 from \$0"\n' "\$c" > "\$prefix/bin/\$c"; chmod +x "\$prefix/bin/\$c"
    done ;;
  install) : ;;
esac
EOF
chmod +x "$TMP/bin/conda"

PATH="$TMP/bin:/usr/bin:/bin" CONDA_PREFIX="" bash "$ROOT/env/install_tools.sh" --env plasbench reconstruction \
    > "$TMP/install.log" 2>&1 || { echo "FAIL: install_tools.sh reconstruction" >&2; cat "$TMP/install.log" "$TMP/conda.log" >&2; exit 1; }

grep -q "conda install .* platon" "$TMP/conda.log" || { echo "FAIL: platon not installed into the main env" >&2; cat "$TMP/conda.log" >&2; exit 1; }
if grep -E "conda install .*mob_suite" "$TMP/conda.log"; then echo "FAIL: mob_suite was installed into the main env" >&2; exit 1; fi
grep -q "conda create -y -p $MOB .*mob_suite=3.1.9 .*pandas<=1.5.3" "$TMP/conda.log" \
    || { echo "FAIL: the pinned MOB-suite environment was not created" >&2; cat "$TMP/conda.log" >&2; exit 1; }
echo "reconstruction: platon into the main env, mob_suite into its own pinned env -> PASS"

for c in mob_recon mob_typer mob_cluster mob_init; do
    [[ -x "$MAIN/bin/$c" ]] || { echo "FAIL: no $c wrapper in the main env" >&2; exit 1; }
done
out="$("$MAIN/bin/mob_recon" --version)"
[[ "$out" == *"3.1.9 from $MOB/bin/mob_recon"* ]] || { echo "FAIL: wrapper does not run the separate env: $out" >&2; exit 1; }
echo "wrappers in the main env run MOB-suite's own environment -> PASS"

found="$(PATH="$MAIN/bin:/usr/bin:/bin" bash -c "source '$ROOT/scripts/lib.sh'; mobsuite_db_dir")"
[[ "$found" == "$MOB/lib/python3.10/site-packages/mob_suite/databases" ]] \
    || { echo "FAIL: mobsuite_db_dir found '$found'" >&2; exit 1; }
echo "mobsuite_db_dir follows the wrapper to the separate environment's database -> PASS"

: > "$TMP/conda.log"
PATH="$TMP/bin:/usr/bin:/bin" CONDA_PREFIX="" bash "$ROOT/env/install_tools.sh" --env plasbench mobsuite > "$TMP/install2.log" 2>&1
if grep -q "conda create" "$TMP/conda.log"; then echo "FAIL: a working MOB-suite env was rebuilt" >&2; exit 1; fi
echo "re-running the mobsuite profile keeps a working environment (no rebuild) -> PASS"

grep -qE '^\s*-\s*mob_suite' "$ROOT/env/environment.yml" && { echo "FAIL: environment.yml still installs mob_suite" >&2; exit 1; }
grep -q '/mob_suite-' "$ROOT/env/environment.lock.yml" && { echo "FAIL: the lock still pins mob_suite" >&2; exit 1; }
grep -q 'install_tools.sh" --env "$ENV_NAME" mobsuite' "$ROOT/env/setup_conda.sh" || { echo "FAIL: setup_conda.sh does not install the MOB-suite env" >&2; exit 1; }
echo "environment.yml and the lock no longer carry mob_suite; setup_conda.sh installs its own env -> PASS"
echo "ALL MOB-SUITE ENVIRONMENT TESTS PASSED"
