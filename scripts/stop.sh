#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="finally-app"

if docker ps -q -f name="$CONTAINER_NAME" | grep -q .; then
  docker stop "$CONTAINER_NAME"
  docker rm "$CONTAINER_NAME"
  echo "FinAlly stopped. Data volume 'finally-data' preserved."
elif docker ps -aq -f name="$CONTAINER_NAME" | grep -q .; then
  docker rm "$CONTAINER_NAME"
  echo "Container removed. Data volume 'finally-data' preserved."
else
  echo "FinAlly is not running."
fi
