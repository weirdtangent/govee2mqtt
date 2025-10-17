# ---------- builder ----------
FROM python:3-slim AS builder

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential gcc libffi-dev libssl-dev \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/app

# Upgrade tooling
RUN python -m ensurepip && pip install --upgrade pip setuptools wheel

COPY requirements.txt .
RUN python -m venv .venv \
 && .venv/bin/pip install --no-cache-dir -r requirements.txt

# ---------- production ----------
FROM python:3-slim AS production

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/usr/src/app/.venv/bin:${PATH}"

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/app

# Copy app and the prepared venv
COPY . .
COPY --from=builder /usr/src/app/.venv .venv

# Non-root user
ARG USER_ID=1000
ARG GROUP_ID=1000
RUN addgroup --gid ${GROUP_ID} appuser \
 && adduser  --uid ${USER_ID} --gid ${GROUP_ID} --disabled-password --gecos "" appuser

# Config directory (shows up in Synology as a Volume)
RUN install -d -m 0775 -o appuser -g appuser /config
VOLUME ["/config"]

USER appuser

ENTRYPOINT ["python3", "./app.py"]
CMD ["-c", "/config"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
  CMD python - <<'PY' || exit 1
import os, time, sys
p = os.getenv("READY_FILE","/tmp/govee2mqtt.ready")
try:
    st = os.stat(p)
    # “healthy” if file exists and touched within last 90s
    sys.exit(0 if time.time() - st.st_mtime < 90 else 1)
except FileNotFoundError:
    sys.exit(1)
PY
