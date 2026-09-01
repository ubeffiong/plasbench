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
# environment.lock.yml is an explicit package specification, not an environment YAML.
RUN micromamba create -y -n plasbench --file /tmp/environment.lock.yml && micromamba clean --all --yes

WORKDIR /opt/plasbench
COPY --chown=$MAMBA_USER:$MAMBA_USER . /opt/plasbench
RUN micromamba run -n plasbench python -m pip install --no-deps .

ENV PATH=/opt/conda/envs/plasbench/bin:$PATH
ENV CONTAINER_IMAGE=$IMAGE_NAME CONTAINER_IMAGE_DIGEST=$IMAGE_DIGEST
CMD ["plasbench", "--help"]
