#!/usr/bin/env bash
# Run an image while recording the image's immutable local/registry identity.
set -euo pipefail
IMAGE="${PLASBENCH_IMAGE:-plasbench:local}"
digest="$(docker image inspect "$IMAGE" --format '{{index .RepoDigests 0}}' 2>/dev/null || true)"
[[ -n "$digest" && "$digest" != "<no value>" ]] || digest="$(docker image inspect "$IMAGE" --format '{{.Id}}')"
HOST_ROOT="${PLASBENCH_HOST_ROOT:-$PWD}"
exec docker run --rm \
  -v "$HOST_ROOT/config:/work/config:ro" -v "$HOST_ROOT/data:/work/data" \
  -v "$HOST_ROOT/logs:/work/logs" -v "$HOST_ROOT/results:/work/results" \
  -e DATA_DIR=/work/data -e LOG_DIR=/work/logs -e RESULTS_DIR=/work/results \
  -e "CONTAINER_IMAGE=$IMAGE" -e "CONTAINER_IMAGE_DIGEST=$digest" "$IMAGE" "$@"
