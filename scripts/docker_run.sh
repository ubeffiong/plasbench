#!/usr/bin/env bash
# Run an image while recording the image's immutable local/registry identity.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Docker must answer before anything else: when it does not, say exactly why and what to do next (the same diagnosis as `plasbench install-tools docker`),
# instead of a bare "command not found". PLASBENCH_SKIP_DOCKER_CHECK=1 skips this (tests, unusual setups).
if [[ "${PLASBENCH_SKIP_DOCKER_CHECK:-0}" != "1" ]]; then
    if command -v python3 >/dev/null 2>&1 && [[ -f "$HERE/../python/docker_setup.py" ]]; then
        if ! python3 "$HERE/../python/docker_setup.py" state >/dev/null 2>&1; then
            python3 "$HERE/../python/docker_setup.py" diagnose >&2 || true
            echo "Docker is not ready, so nothing was started. To set it up: plasbench install-tools docker" >&2
            exit 1
        fi
    elif ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
        echo "Docker is not installed or its daemon is not running. To set it up: plasbench install-tools docker (guide: https://docs.docker.com/get-started/get-docker/)" >&2
        exit 1
    fi
fi
IMAGE="${PLASBENCH_IMAGE:-plasbench:local}"
digest="$(docker image inspect "$IMAGE" --format '{{index .RepoDigests 0}}' 2>/dev/null || true)"
[[ -n "$digest" && "$digest" != "<no value>" ]] || digest="$(docker image inspect "$IMAGE" --format '{{.Id}}')"
HOST_ROOT="${PLASBENCH_HOST_ROOT:-$PWD}"
# Studies (plasbench run keeps each benchmark in its own folder) live in the host's workspace, mounted at /work/studies.
HOST_DATA="${PLASBENCH_DATA_DIR:-$HOST_ROOT/data}"
HOST_WORKSPACE="${PLASBENCH_WORKSPACE:-$HOST_ROOT/studies}"
mkdir -p "$HOST_WORKSPACE" "$HOST_DATA"
exec docker run --rm \
  -v "$HOST_ROOT/config:/work/config:ro" -v "$HOST_DATA:/work/data" \
  -v "$HOST_ROOT/logs:/work/logs" -v "$HOST_ROOT/results:/work/results" -v "$HOST_WORKSPACE:/work/studies" \
  -e DATA_DIR=/work/data -e LOG_DIR=/work/logs -e PLASBENCH_WORKSPACE=/work/studies \
  -e "CONTAINER_IMAGE=$IMAGE" -e "CONTAINER_IMAGE_DIGEST=$digest" "$IMAGE" "$@"
