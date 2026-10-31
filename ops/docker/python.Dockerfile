FROM python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159

ARG EXTRA=""
ARG INSTALL_DEV=""

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app:/app/packages \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    FASTEMBED_CACHE_PATH=/opt/models \
    PATH=/opt/venv/bin:$PATH

RUN pip install --no-cache-dir uv==0.12.15

# OCR for scanned CVs: the ml image only.
RUN if [ "$EXTRA" = "ml" ]; then \
      apt-get update && \
      apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-eng tesseract-ocr-fra tesseract-ocr-ara && \
      rm -rf /var/lib/apt/lists/*; \
    fi

WORKDIR /app
COPY pyproject.toml uv.lock ./
# Dev tools are installed only when INSTALL_DEV is set.
RUN if [ -n "$INSTALL_DEV" ]; then dev_flag=""; else dev_flag="--no-dev"; fi; \
    uv sync --frozen --no-cache $dev_flag ${EXTRA:+--extra "$EXTRA"}

# The ml service has no internet at runtime, so its model is baked in at build time.
RUN if [ "$EXTRA" = "ml" ]; then \
      python -c "from fastembed import TextEmbedding; \
TextEmbedding(model_name='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')" && \
      chmod -R a+rX /opt/models; \
    fi

COPY apps ./apps
COPY packages ./packages
COPY data ./data
COPY seed ./seed

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin astra
USER astra
