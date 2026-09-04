#!/usr/bin/env bash
# Bioconda build for PlasBench.
#
# PlasBench is a Python CLI wrapped around a collection of bash and Python
# pipeline scripts. The scripts are not importable modules and must stay
# together -- each one locates its siblings as $HERE/../{python,config,adapters}
# -- so they are installed as a unit under $PREFIX/share/plasbench, which is the
# standard conda location for a script collection. plasbench/tools.py then finds
# them there via $CONDA_PREFIX, giving Galaxy a plain command on PATH instead of
# an absolute path inside a container image.
set -euo pipefail

# 1. The Python package and its console entry points (plasbench,
#    plasbench-score, plasbench-aggregate).
$PYTHON -m pip install . -vv --no-deps --no-build-isolation

# 2. The pipeline itself.
SHARE="$PREFIX/share/plasbench"
mkdir -p "$SHARE"
for tree in scripts python adapters config env; do
    cp -r "$tree" "$SHARE/"
done
cp -r cohorts "$SHARE/" 2>/dev/null || true

# Keep the executable bit: conda tarballs preserve it, and stage 0 checks it.
find "$SHARE/scripts" "$SHARE/adapters" "$SHARE/env" -name '*.sh' -exec chmod 0755 {} +

# 3. Fail the build rather than shipping an installation whose entry points
#    cannot find the pipeline. This is the exact failure the layout is meant to
#    prevent, so it is worth asserting at build time.
test -f "$SHARE/python/score_plasmids.py"
test -f "$SHARE/python/aggregate_results.py"
test -f "$SHARE/scripts/run_all.sh"
test -f "$SHARE/config/config.sh"
