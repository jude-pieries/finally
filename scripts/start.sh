#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="finally"
CONTAINER_NAME="finally-app"
VOLUME_NAME="finally-data"
PORT=8000

cd "$(dirname "$0")/.."

# Parse flags
BUILD=false
for arg in "$@"; do
  case "$arg" in
    --build|-b) BUILD=true ;;
  esac
done

# Build image if needed or if --build flag passed
if $BUILD || ! docker image inspect "$IMAGE_NAME" &>/dev/null 2>&1; then
  echo "Building FinAlly Docker image..."
  docker build -t "$IMAGE_NAME" .
fi

# Stop existing container if running
if docker ps -q -f name="$CONTAINER_NAME" | grep -q .; then
  echo "Stopping existing container..."
  docker stop "$CONTAINER_NAME"
  docker rm "$CONTAINER_NAME"
elif docker ps -aq -f name="$CONTAINER_NAME" | grep -q .; then
  docker rm "$CONTAINER_NAME"
fi

# Check if .env exists
if [ ! -f .env ]; then
  echo "Warning: .env not found. Copy .env.example to .env and set your API keys."
  echo "Continuing without .env (market data simulator will be used)..."
  ENV_FLAG=""
else
  ENV_FLAG="--env-file .env"
fi

# Run container
docker run -d \
  --name "$CONTAINER_NAME" \
  -v "${VOLUME_NAME}:/app/db" \
  -p "${PORT}:8000" \
  $ENV_FLAG \
  "$IMAGE_NAME"

echo ""
echo "FinAlly is running at http://localhost:${PORT}"
echo ""

# Open browser
sleep 2
if command -v open &>/dev/null; then
  open "http://localhost:${PORT}"
elif command -v xdg-open &>/dev/null; then
  xdg-open "http://localhost:${PORT}"
fi
