# syntax=docker/dockerfile:1
# Canonical backend image. Build context = repo root (see render.yaml,
# docker-compose.yml). backend/Dockerfile is the same image for hosts whose
# build context is backend/.

FROM python:3.15-slim-bookworm AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY backend/requirements.txt .
RUN pip install --upgrade "setuptools>=78.1.1" "wheel>=0.46.2" && pip install -r requirements.txt

FROM python:3.15-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8000
RUN pip uninstall -y setuptools wheel && useradd --system --uid 10001 --no-create-home app
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app backend/app ./app
COPY --chown=app:app backend/migrations ./migrations
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request as u; u.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8000'), timeout=4)"
# $PORT is injected by the host at runtime.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
