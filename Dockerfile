# AgentEscrow: API + built React UI in one image.
#   docker build -t agentescrow .
# Worker code runs in a SEPARATE hardened container (see docker/sandbox.Dockerfile), started through the Docker CLI.

# ---- stage 1: build the React UI ---------------------------------------------------
FROM node:22-slim AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- stage 2: the Python API --------------------------------------------------------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# The Docker CLI (only the client) lets the API start sandbox containers on the host's daemon.
COPY --from=docker:cli /usr/local/bin/docker /usr/local/bin/docker

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY agentescrow ./agentescrow
COPY scripts ./scripts
COPY --from=ui /ui/dist ./frontend/dist

ENV API_HOST=0.0.0.0 DATABASE_PATH=/data/agentescrow.db LOG_DIR=/data/logs FRONTEND_DIST=/app/frontend/dist
VOLUME /data
EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/api/health').status == 200 else 1)"

# One process on purpose: the job runner, rate limiter and live streams live in memory.
CMD ["python", "-m", "agentescrow.api.app", "--inprocess"]
