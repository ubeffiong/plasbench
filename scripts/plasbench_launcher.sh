#!/usr/bin/env bash
# PlasBench launcher: what the desktop icon runs (plasbench desktop-icon).
# Finds conda / mamba / micromamba, activates the `plasbench` environment when it exists, then starts the PlasBench
# window (`plasbench ui`). If PlasBench is already running for this folder, `plasbench ui` only brings its window back.
# Output goes to ~/.plasbench/ui/launcher.log because a desktop icon has no terminal.
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${PLASBENCH_UI_HOME:-$HOME/.plasbench/ui}"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/launcher.log"
ENV_NAME="${PLASBENCH_ENV_NAME:-plasbench}"

{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') PlasBench launcher: $HERE"
} >>"$LOG" 2>&1

activate_env() {
  # conda / mamba (miniforge, mambaforge, miniconda, anaconda)
  local base hook
  for base in "${CONDA_ROOT:-}" "$HOME/miniforge3" "$HOME/mambaforge" "$HOME/miniconda3" "$HOME/anaconda3" \
              /opt/conda /opt/miniforge3 /usr/local/miniforge3; do
    [ -n "$base" ] || continue
    if [ -f "$base/etc/profile.d/conda.sh" ]; then
      # shellcheck disable=SC1091
      . "$base/etc/profile.d/conda.sh"
      if conda activate "$ENV_NAME" >>"$LOG" 2>&1; then
        echo "activated conda environment $ENV_NAME ($base)" >>"$LOG"
        return 0
      fi
    fi
  done
  # conda already on PATH (installed elsewhere)
  if command -v conda >/dev/null 2>&1; then
    hook="$(conda shell.bash hook 2>/dev/null)" && eval "$hook"
    if conda activate "$ENV_NAME" >>"$LOG" 2>&1; then
      echo "activated conda environment $ENV_NAME" >>"$LOG"
      return 0
    fi
  fi
  # micromamba
  local mm
  mm="$(command -v micromamba 2>/dev/null || true)"
  [ -n "$mm" ] || { [ -x "$HOME/.local/bin/micromamba" ] && mm="$HOME/.local/bin/micromamba"; }
  if [ -n "$mm" ]; then
    hook="$("$mm" shell hook --shell bash 2>/dev/null)" && eval "$hook"
    if micromamba activate "$ENV_NAME" >>"$LOG" 2>&1; then
      echo "activated micromamba environment $ENV_NAME" >>"$LOG"
      return 0
    fi
  fi
  echo "no $ENV_NAME environment found; starting with the system Python (Set up this computer can install it)" >>"$LOG"
  return 1
}

activate_env || true

PY=""
for cand in python python3; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
    PY="$cand"
    break
  fi
done
if [ -z "$PY" ]; then
  echo "ERROR: Python 3.9 or newer was not found" >>"$LOG"
  if command -v notify-send >/dev/null 2>&1; then
    notify-send "PlasBench" "Python 3.9 or newer was not found. See $LOG"
  fi
  exit 1
fi

cd "$HERE" || exit 1
exec "$PY" -m plasbench --project-root "$HERE" ui "$@" >>"$LOG" 2>&1
