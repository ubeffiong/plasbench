# PlasBench runtime image. The Platon database is intentionally not embedded:
# mount a versioned database directory or run the supplied database setup once.
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
# Bake the MOB-suite reference database so benchmark runs need no network.
RUN for attempt in 1 2 3 4 5; do \
      /opt/plasbench-bin/mob_init && exit 0; \
      echo "mob_init attempt $attempt failed; retrying"; sleep 15; \
    done; exit 1

# Stage 1 unpacks the NCBI datasets archive with unzip, which the solved lock
# does not provide; without it every download aborts with "unzip: command not found".
RUN micromamba install -y -n plasbench -c conda-forge unzip \
    && micromamba clean --all --yes

WORKDIR /opt/plasbench
COPY --chown=$MAMBA_USER:$MAMBA_USER . /opt/plasbench
RUN micromamba run -n plasbench python -m pip install --no-deps .

ENV PATH=/opt/plasbench-bin:/opt/conda/envs/plasbench/bin:$PATH
ENV CONTAINER_IMAGE=$IMAGE_NAME CONTAINER_IMAGE_DIGEST=$IMAGE_DIGEST
CMD ["plasbench", "--help"]
