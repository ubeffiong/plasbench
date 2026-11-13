#!/usr/bin/env bash
# PlaScope, Plasmer and PlasmidHunter cannot be solved into the python 3.12 main
# environment (centrifuge 1.0.3 needs python <= 3.6; Plasmer and every
# PlasmidHunter release need python 3.10). With a fake conda and pip:
#   * each profile creates <env>-<tool> with its own python pin and never
#     installs the tool into the main environment;
#   * plasmidhunter is pip-installed with that environment's own pip, pinned;
#   * the main environment gets a wrapper that runs the isolated command, with
#     the isolated bin/ (centrifuge, diamond...) first on PATH;
#   * re-running a profile keeps a working environment (no rebuild).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

BASE="$TMP/base"; MAIN="$BASE/envs/plasbench"
mkdir -p "$TMP/bin" "$MAIN/bin"
cat > "$TMP/bin/conda" <<EOF
#!/usr/bin/env bash
echo "conda \$*" >> "$TMP/conda.log"
case "\$1" in
  info) echo "$BASE" ;;
  create)
    prefix=""; args="\$*"; while [[ \$# -gt 0 ]]; do [[ "\$1" == "-p" ]] && prefix="\$2"; shift; done
    mkdir -p "\$prefix/bin"
    mk() { printf '#!/bin/sh\necho "%s from \$0 PATH=\$PATH"\n' "\$1" > "\$prefix/bin/\$1"; chmod +x "\$prefix/bin/\$1"; }
    case "\$args" in
      *plascope*) mk plaScope.sh; mk centrifuge ;;
      *plasmer*) mk Plasmer ;;
    esac
    case "\$args" in *" pip"*)
      printf '#!/bin/sh\necho "pip \$*" >> "$TMP/conda.log"\nd=\$(dirname "\$0")\nprintf "#!/bin/sh\\\\necho plasmidhunter from \\\$0\\\\n" > "\$d/plasmidhunter"; chmod +x "\$d/plasmidhunter"\n' > "\$prefix/bin/pip"
      chmod +x "\$prefix/bin/pip" ;;
    esac ;;
  install) : ;;
esac
EOF
chmod +x "$TMP/bin/conda"

run() { PATH="$TMP/bin:/usr/bin:/bin" CONDA_PREFIX="" bash "$ROOT/env/install_tools.sh" --env plasbench "$1" > "$TMP/$1.log" 2>&1 \
    || { echo "FAIL: install_tools.sh $1" >&2; cat "$TMP/$1.log" "$TMP/conda.log" >&2; exit 1; }; }

run plascope; run plasmer; run plasmidhunter

if grep -E "conda install .*(plascope|plasmer|plasmidhunter|diamond)" "$TMP/conda.log"; then
    echo "FAIL: a tool was installed into the main environment" >&2; exit 1; fi
grep -q "conda create -y -p $BASE/envs/plasbench-plascope .*plascope=1.3.1 python=3.6" "$TMP/conda.log" \
    || { echo "FAIL: PlaScope env not created with python 3.6" >&2; cat "$TMP/conda.log" >&2; exit 1; }
grep -q "conda create -y -p $BASE/envs/plasbench-plasmer -c iskoldt .*plasmer python=3.10" "$TMP/conda.log" \
    || { echo "FAIL: Plasmer env not created with python 3.10 from iskoldt" >&2; cat "$TMP/conda.log" >&2; exit 1; }
grep -q "conda create -y -p $BASE/envs/plasbench-plasmidhunter .*python=3.10 diamond prodigal pip" "$TMP/conda.log" \
    || { echo "FAIL: PlasmidHunter env not created with python 3.10" >&2; cat "$TMP/conda.log" >&2; exit 1; }
grep -q "^pip install plasmidhunter==1.4" "$TMP/conda.log" \
    || { echo "FAIL: plasmidhunter not pip-installed (pinned) into its own env" >&2; cat "$TMP/conda.log" >&2; exit 1; }
grep -q -- "-c defaults" "$TMP/conda.log" && { echo "FAIL: the commercial defaults channel is used" >&2; exit 1; }
echo "each tool gets its own environment with a compatible python; none touch the main env -> PASS"

for pair in plaScope.sh:plascope centrifuge:plascope Plasmer:plasmer plasmidhunter:plasmidhunter; do
    cmd="${pair%%:*}"; env="${pair##*:}"
    [[ -x "$MAIN/bin/$cmd" ]] || { echo "FAIL: no $cmd wrapper in the main env" >&2; exit 1; }
    out="$("$MAIN/bin/$cmd")"
    [[ "$out" == *"from $BASE/envs/plasbench-$env/bin/$cmd"* ]] || { echo "FAIL: $cmd wrapper does not run its env: $out" >&2; exit 1; }
done
[[ "$("$MAIN/bin/plaScope.sh")" == *"PATH=$BASE/envs/plasbench-plascope/bin:"* ]] \
    || { echo "FAIL: PlaScope wrapper does not put its env's centrifuge first on PATH" >&2; exit 1; }
echo "wrappers in the main env run each tool from its own environment -> PASS"

: > "$TMP/conda.log"
run plascope; run plasmer; run plasmidhunter
if grep -q "create\|^pip" "$TMP/conda.log"; then echo "FAIL: a working isolated env was rebuilt" >&2; cat "$TMP/conda.log" >&2; exit 1; fi
echo "re-running the profiles keeps working environments (no rebuild) -> PASS"
echo "ALL ISOLATED TOOL ENVIRONMENT TESTS PASSED"
