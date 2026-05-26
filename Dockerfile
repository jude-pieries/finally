# Stage 1: Build Next.js frontend
FROM node:20-slim AS build-frontend
WORKDIR /app
COPY frontend/package*.json ./frontend/
RUN cd frontend && npm install
COPY frontend/ ./frontend/
RUN cd frontend && npm run build

# Stage 2: Python backend with static files
FROM python:3.12-slim AS final
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY backend/ ./backend/
RUN cd backend && uv sync --no-dev

COPY --from=build-frontend /app/frontend/out ./static

RUN mkdir -p /app/db

ENV DB_PATH=/app/db/finally.db
ENV STATIC_DIR=/app/static

EXPOSE 8000
WORKDIR /app/backend
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
