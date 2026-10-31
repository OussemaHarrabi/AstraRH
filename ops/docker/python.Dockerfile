FROM python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159

ARG EXTRA=""
ARG INSTALL_DEV=""

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app:/app/packages \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH

RUN pip install --no-cache-dir uv==0.12.15

WORKDIR /app
COPY pyproject.toml uv.lock ./
# Dev tools are installed only when INSTALL_DEV is set.
RUN if [ -n "$INSTALL_DEV" ]; then dev_flag=""; else dev_flag="--no-dev"; fi; \
    uv sync --frozen --no-cache $dev_flag ${EXTRA:+--extra "$EXTRA"}

COPY apps ./apps
COPY packages ./packages

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin astra
USER astra
