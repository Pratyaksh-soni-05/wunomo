#!/bin/bash
set -e
echo "🚀 Deploying AXIOM DataOps Agent..."

if [ ! -f .env ]; then
  echo "❌ .env file not found. Run: cp .env.example .env"
  exit 1
fi

docker compose pull
docker compose build --no-cache
docker compose up -d
docker compose exec backend alembic upgrade head
docker compose exec backend python scripts/seed_data.py

echo "✅ Deployment complete."
echo "   API:  http://localhost:8000/docs"
echo "   UI:   http://localhost:3000"
