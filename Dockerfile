# Lightsail container services run whatever this produces, on a nano node.
# One stage: there is nothing to build -- the frontend is three static files
# that ship exactly as written.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

WORKDIR /app

# Requirements first so a code edit does not re-resolve the dependency tree.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY static/ ./static/

# Nothing here needs root once the wheels are installed.
RUN useradd --create-home --uid 10001 scanner
USER scanner

EXPOSE 8080

# Lightsail's own health check hits /healthz over HTTP; this one is for anyone
# running the image directly.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/healthz').read()"

CMD ["python", "app.py"]
