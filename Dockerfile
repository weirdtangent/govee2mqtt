# syntax=docker/dockerfile:1.7-labs
FROM python:3-slim
WORKDIR /app

COPY pyproject.toml uv.lock ./

# ---- Version injection support ----
ARG VERSION
ENV GOVEE2MQTT_VERSION=${VERSION}
ENV SETUPTOOLS_SCM_PRETEND_VERSION_FOR_GOVEE2MQTT=${VERSION}

# Install uv
RUN pip install uv

# copy source
COPY --exclude=.git . .

# Install dependencies (uses setup info, now src exists)
RUN uv sync --frozen --no-dev

# Install the package (if needed)
RUN uv pip install .

# ---- Runtime ----
ENV SERVICE=govee2mqtt
ENTRYPOINT ["/app/.venv/bin/govee2mqtt"]
CMD ["-c", "/config"]

