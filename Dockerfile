# PlasBench runtime image. The Platon and MOB-suite databases are intentionally
# not embedded: each is fetched once at first real use (mount a versioned
# database directory, or a volume over the default location, to persist it
# across containers) rather than baked in at build time. Baking a live,
# unpinned, unchecksummed network fetch into the image would make builds
# non-reproducible and fail the whole build on any network hiccup.
FROM mambaorg/micromamba@sha256:e3797091302382ea841498bc93a7b0a50f7c1448333d5e946d2d1608d0c5f43d

ARG VCS_REF=unknown
ARG BUILD_DATE=unknown
ARG IMAGE_NAME=plasbench:local
ARG IMAGE_DIGEST=unresolved-local-image
LABEL org.opencontainers.image.title="PlasBench" \
      org.opencontainers.image.source="https://github.com/ubeffiong/plasbench" \
      org.opencontainers.image.revision="$VCS_REF" \
      org.opencontainers.image.created="$BUILD_DATE"

COPY --chown=$MAMBA_USER:$MAMBA_USER env/environment.lock.yml /tmp/environment.lock.yml
# environment.lock.yml is Conda's @EXPLICIT format. Micromamba interprets
# --file as YAML, so supply the lock's exact package URLs as specifications.
RUN micromamba create -y -n plasbench $(awk '!/^(@|#|$)/ {print}' /tmp/environment.lock.yml) \
    && micromamba clean --all --yes

# MOB-suite pins pandas<=1.5.3 and numpy<1.23.5, which cannot co-exist with the
# modern pandas/python of the main lock. Solved into the main environment it
# produces a mob_recon that installs but crashes at import with
# "cannot import name 'EmptyDataError' from 'pandas.io.common'". MOB-suite
# therefore gets its own environment, exposed on PATH through thin shims.
RUN micromamba create -y -n mobsuite -c conda-forge -c bioconda \
      "mob_suite=3.1.9" "python=3.10" "pandas<=1.5.3" "numpy<1.23.5" \
      "blast>=2.9.0,<2.16.0" "mash>=2.0" \
    && micromamba clean --all --yes
USER root
RUN mkdir -p /opt/plasbench-bin \
 && for cmd in mob_recon mob_typer mob_cluster mob_init; do \
      { echo '#!/bin/sh'; echo 'PATH=/opt/conda/envs/mobsuite/bin:$PATH'; echo 'export PATH'; echo "exec /opt/conda/envs/mobsuite/bin/$cmd \"\$@\""; } > "/opt/plasbench-bin/$cmd"; \
      chmod 0755 "/opt/plasbench-bin/$cmd"; \
    done
USER $MAMBA_USER
# The MOB-suite database is NOT baked in here: mob_recon and mob_typer both
# download it automatically into their default directory on first real
# invocation if it is missing (matching the Platon database's runtime-fetch
# model above). Run `mob_init` once and bind-mount its default directory
# (/opt/conda/envs/mobsuite/lib/python3.10/site-packages/mob_suite/databases)
# to persist the ~1 GB download across containers instead of refetching it
# every run.

WORKDIR /opt/plasbench
COPY --chown=$MAMBA_USER:$MAMBA_USER . /opt/plasbench
RUN micromamba run -n plasbench python -m pip install --no-deps .

ENV PATH=/opt/plasbench-bin:/opt/conda/envs/plasbench/bin:$PATH
ENV CONTAINER_IMAGE=$IMAGE_NAME CONTAINER_IMAGE_DIGEST=$IMAGE_DIGEST
CMD ["plasbench", "--help"]
