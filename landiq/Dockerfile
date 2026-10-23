# LANDIQ: one container serving the FastAPI backend and the built React frontend.
#   docker build -t landiq ./landiq
#   docker run -p 8000:8000 -e GEMINI_API_KEY=... -v landiq-data:/app/backend/storage landiq
# Single instance only: SQLite and the in-process job runner are not shared across replicas.

FROM node:22-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt
COPY backend/ backend/
COPY --from=frontend /build/dist frontend/dist
# Download the local embedding model at build time so the container starts offline.
RUN python -c "from chromadb.utils.embedding_functions import DefaultEmbeddingFunction as E; E()(['warm up'])"
RUN useradd --create-home landiq && mkdir -p backend/storage && chown -R landiq /app/backend/storage
USER landiq
WORKDIR /app/backend
VOLUME ["/app/backend/storage"]
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health')"
CMD ["python", "-m", "uvicorn", "landiq.api:app", "--host", "0.0.0.0", "--port", "8000"]
