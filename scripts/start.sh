#!/usr/bin/env bash
set -euo pipefail

echo "Starting Libya Customs (build + detach)..."
docker-compose up --build -d

echo "Done. To follow logs: docker-compose logs -f app"
