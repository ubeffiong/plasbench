# PlasBench runtime image. The Platon and MOB-suite databases are intentionally
# not embedded: each is fetched once at first real use (mount a versioned
# database directory, or a volume over the default location, to persist it
# across containers) rather than baked in at build time. Baking a live,
# unpinned, unchecksummed network fetch into the image would make builds
# non-reproducible and fail the whole build on any network hiccup.
FROM mambaorg/micromamba@sha256:e1476182cd40eb1f7c0cfae4adec9bfd78f3d7f05c61368306abfdc8939c1198

ARG VCS_REF=unknown
ARG BUILD_DATE=unknown
ARG IMAGE_NAME=plasbench:local
ARG IMAGE_DIGEST=unresolved-local-image
ARG PLASBENCH_VERSION=unknown
LABEL org.opencontainers.image.title="PlasBench" \
      org.opencontainers.image.version="$PLASBENCH_VERSION" \
      org.opencontainers.image.source="https://github.com/ubeffiong/plasbench" \
      org.opencontainers.image.revision="$VCS_REF" \
      org.opencontainers.image.created="$BUILD_DATE"

COPY --chown=$MAMBA_USER:$MAMBA_USER env/environment.lock.yml /tmp/environment.lock.yml
# environment.lock.yml is Conda's @EXPLICIT format. Micromamba interprets
# --file as YAML, so supply the lock's exact package URLs as specifications.
# The channels are named because newer micromamba images (e147618 and later) resolve each URL as a package spec against the default channel only, so the lock's
# bioconda packages "do not exist"; with both channels named the exact builds are found, as before.
RUN micromamba create -y -n plasbench -c conda-forge -c bioconda $(awk '!/^(@|#|$)/ {print}' /tmp/environment.lock.yml) \
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

# gplas2 (optional fourth benchmark tool) is distributed from GitLab, not
# bioconda: bioconda's `gplas` is 0.6.1 and lacks the -P/--prediction external
# classifier flag that scripts/04_run_tools.sh invokes. Its environment pins
# ~200 packages to 2019 builds (R 3.5.1, Python 3.7.3, snakemake 5.5.4) that
# cannot coexist with the main lock, so -- like MOB-suite -- it gets its own
# environment, exposed on PATH through a thin shim. Every `conda:` directive in
# its snakefiles is commented out, so it runs entirely inside this environment
# and creates none at run time. The commit is pinned so the image is reproducible.
ARG GPLAS2_COMMIT=00cf37bec5e44b05ee30c8a4c99e987abbbb4c4f
# Optional: --build-arg GPLAS2_SHA256=<sha256 of the archive> makes the build fail on a different archive (config/download_checksums.tsv records that none is verified offline yet).
ARG GPLAS2_SHA256=
USER root
RUN /opt/conda/envs/plasbench/bin/curl -sSL --retry 8 --retry-all-errors --retry-delay 5 \
      -o /tmp/gplas2.tar.gz \
      "https://gitlab.com/mmb-umcu/gplas2/-/archive/$GPLAS2_COMMIT/gplas2-$GPLAS2_COMMIT.tar.gz" \
 && if [ -n "$GPLAS2_SHA256" ]; then echo "$GPLAS2_SHA256  /tmp/gplas2.tar.gz" | sha256sum -c -; fi \
 && mkdir -p /opt/gplas2 \
 && tar -xzf /tmp/gplas2.tar.gz -C /opt/gplas2 --strip-components=1 \
 && rm -f /tmp/gplas2.tar.gz \
 && chown -R $MAMBA_USER:$MAMBA_USER /opt/gplas2
USER $MAMBA_USER
# Several of the pinned 2019 builds come from Anaconda's pkgs/r channel, which
# is slow enough here to trip libmamba's low-speed cutoff mid-transaction. The
# package cache persists across attempts inside this layer, so each retry
# resumes rather than restarting the 379MB download.
RUN for attempt in 1 2 3 4 5; do \
      MAMBA_REMOTE_MAX_RETRIES=10 MAMBA_REMOTE_BACKOFF_FACTOR=3 \
        micromamba create -y -n gplas2 --file /opt/gplas2/envs/gplas.yaml && break; \
      echo "gplas2 environment attempt $attempt failed; retrying"; sleep 20; \
    done; \
    test -x /opt/conda/envs/gplas2/bin/Rscript \
 && micromamba clean --all --yes
# setuptools_scm derives the version from git metadata, which a tarball has not
# got; pin it explicitly so the install does not depend on clone history.
RUN SETUPTOOLS_SCM_PRETEND_VERSION=1.1.2 \
    micromamba run -n gplas2 python -m pip install --no-deps -e /opt/gplas2
USER root
# gplas shells out to snakemake and Rscript, so its shim must put its own
# environment on PATH -- exactly the MOB-suite lesson.
RUN { echo '#!/bin/sh'; \
      echo 'PATH=/opt/conda/envs/gplas2/bin:$PATH'; \
      echo 'export PATH'; \
      echo 'exec /opt/conda/envs/gplas2/bin/gplas "$@"'; } > /opt/plasbench-bin/gplas \
 && chmod 0755 /opt/plasbench-bin/gplas
USER $MAMBA_USER

# git is not part of the pinned lock (it's a system tool, not a benchmarking
# dependency), but `plasbench prepare-contribution` shells out to it to stage
# a contribution branch -- without it, that command (and its test) fail
# inside this image with a bare "No such file or directory: 'git'". Installed
# last so it never invalidates the cache for the slow, network-fragile
# mobsuite/gplas2 environment layers above.
RUN micromamba install -y -n plasbench -c conda-forge git procps-ng \
    && micromamba clean --all --yes

WORKDIR /opt/plasbench
COPY --chown=$MAMBA_USER:$MAMBA_USER . /opt/plasbench
RUN micromamba run -n plasbench python -m pip install --no-deps .

# The per-step entry points (plasbench-score, plasbench-aggregate) are called by Galaxy and CWL from any working directory: tell them where the pipeline is.
ENV PLASBENCH_HOME=/opt/plasbench
ENV PATH=/opt/plasbench-bin:/opt/conda/envs/plasbench/bin:$PATH
ENV CONTAINER_IMAGE=$IMAGE_NAME CONTAINER_IMAGE_DIGEST=$IMAGE_DIGEST
CMD ["plasbench", "--help"]
