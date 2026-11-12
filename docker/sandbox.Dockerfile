# Image used to run untrusted, worker-written code against the hidden tests.
# Build (from the project root):  docker build -t agentescrow-sandbox -f docker/sandbox.Dockerfile .
FROM python:3.12-slim

RUN pip install --no-cache-dir pytest==9.1.1 \
    && useradd --no-create-home --uid 10001 sandbox

COPY docker/sandbox_entrypoint.py /opt/sandbox/sandbox_entrypoint.py

USER sandbox
WORKDIR /tmp
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# No ENTRYPOINT: the host runs `python /opt/sandbox/sandbox_entrypoint.py` with a locked-down `docker run`.
