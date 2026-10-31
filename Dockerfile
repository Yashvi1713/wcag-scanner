# Stage 1: build the React app. Node is only needed here, not in the final image.
FROM node:22-alpine AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
COPY wcag_scanner/templates/styles.css /build/wcag_scanner/templates/styles.css
RUN npm run build

# Stage 2: the API and scanner. The official Playwright image ships Chromium and every system
# library it needs; keep its version in step with the playwright pin in pyproject.toml.
FROM mcr.microsoft.com/playwright/python:v1.64.1-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    WCAG_SCANNER_DB=/data/scans.db

WORKDIR /app
COPY pyproject.toml README.md ./
COPY wcag_scanner ./wcag_scanner
COPY demo_site ./demo_site
COPY --from=frontend /build/frontend/dist ./frontend/dist
RUN pip install . && mkdir -p /data && chown pwuser:pwuser /data

# The image's unprivileged user: a browser driven by untrusted URLs shouldn't run as root.
USER pwuser
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"
CMD ["python", "-m", "wcag_scanner", "serve", "--host", "0.0.0.0", "--port", "8000"]
