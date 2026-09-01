#!/usr/bin/env bash
# Run an image while recording the image's immutable local/registry identity.
set -euo pipefail
IMAGE="${PLASBENCH_IMAGE:-plasbench:local}"
digest="$(docker image inspect "$IMAGE" --format '{{index .RepoDigests 0}}' 2>/dev/null || true)"
[[ -n "$digest" && "$digest" != "<no value>" ]] || digest="$(docker image inspect "$IMAGE" --format '{{.Id}}')"
exec docker run --rm -e "CONTAINER_IMAGE=$IMAGE" -e "CONTAINER_IMAGE_DIGEST=$digest" "$IMAGE" "$@"
