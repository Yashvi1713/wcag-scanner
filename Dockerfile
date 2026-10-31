# The official Playwright image ships Chromium and every system library it needs.
# Keep its version in step with the playwright pin in pyproject.toml.
FROM mcr.microsoft.com/playwright/python:v1.64.1-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    WCAG_SCANNER_DB=/data/scans.db

WORKDIR /app
COPY pyproject.toml README.md ./
COPY wcag_scanner ./wcag_scanner
COPY demo_site ./demo_site
RUN pip install . && mkdir -p /data && chown pwuser:pwuser /data

# The image's unprivileged user: a browser driven by untrusted URLs shouldn't run as root.
USER pwuser
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"
CMD ["python", "-m", "wcag_scanner", "serve", "--host", "0.0.0.0", "--port", "8000"]
