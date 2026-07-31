#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_ARGS=(--env-file .env.ecs-full -f docker-compose.ecs-full.yml)

echo "==> project root: $ROOT_DIR"
echo "==> current branch: $(git rev-parse --abbrev-ref HEAD)"

echo "==> pulling latest code"
git pull --ff-only

echo "==> rebuilding and starting services"
docker compose "${COMPOSE_ARGS[@]}" up -d --build

echo "==> current service status"
docker compose "${COMPOSE_ARGS[@]}" ps

echo "==> recent frontend logs"
docker compose "${COMPOSE_ARGS[@]}" logs --tail=50 frontend || true

echo "==> recent backend logs"
docker compose "${COMPOSE_ARGS[@]}" logs --tail=50 backend || true

echo "==> recent engine logs"
docker compose "${COMPOSE_ARGS[@]}" logs --tail=50 engine || true
