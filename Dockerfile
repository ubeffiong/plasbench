# PlasBench runtime image. The Platon database is intentionally not embedded:
# mount a versioned database directory or run the supplied database setup once.
FROM mambaorg/micromamba:1.5.10

COPY --chown=$MAMBA_USER:$MAMBA_USER env/environment.yml /tmp/environment.yml
RUN micromamba create -y -n plasbench -f /tmp/environment.yml && micromamba clean --all --yes

WORKDIR /opt/plasbench
COPY --chown=$MAMBA_USER:$MAMBA_USER . /opt/plasbench
RUN micromamba run -n plasbench python -m pip install --no-deps .

ENV PATH=/opt/conda/envs/plasbench/bin:$PATH
CMD ["plasbench", "--help"]
