# ---------- builder: make a wheel ----------
FROM python:3-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=UTC UV_INSTALL_DIR=/usr/local/bin
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates tzdata curl \
 && rm -rf /var/lib/apt/lists/* \
 && curl -LsSf https://astral.sh/uv/install.sh | sh && uv --version

ARG APP_VERSION=0.0.0
ENV SETUPTOOLS_SCM_PRETEND_VERSION=$APP_VERSION

COPY pyproject.toml uv.lock /app/
COPY src/ /app/src/
RUN uv build
RUN ls -l dist

# ---------- runtime ----------
FROM python:3-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=UTC
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates tzdata \
 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/bin/uv /usr/local/bin/uv
COPY --from=builder /app/dist/*.whl /tmp/
RUN uv pip install --system --no-cache /tmp/*.whl

# healthcheck
COPY src/healthcheck.py /usr/local/bin/healthcheck.py
RUN chmod +x /usr/local/bin/healthcheck.py
ENV READY_FILE=/tmp/govee2mqtt.ready HEALTH_MAX_AGE=90
HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
  CMD ["/usr/bin/env","python","/usr/local/bin/healthcheck.py"]

# non-root & /config
ARG USER_ID=1000 GROUP_ID=1000
RUN addgroup --gid ${GROUP_ID} appuser \
 && adduser --uid ${USER_ID} --gid ${GROUP_ID} --disabled-password --gecos "" appuser \
 && install -d -m 0775 -o appuser -g appuser /config
VOLUME ["/config"]
USER appuser

# run the installed console script (from pyproject)
ENTRYPOINT ["govee2mqtt"]
CMD ["-c","/config"]
