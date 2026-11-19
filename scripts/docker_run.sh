#!/usr/bin/env bash
# Run an image while recording the image's immutable local/registry identity.
set -euo pipefail
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
