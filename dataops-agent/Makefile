
.PHONY: setup dev build migrate seed test deploy clean logs

setup:
	cp .env.example .env
	docker compose up -d postgres redis
	sleep 5
	cd backend && pip install -r requirements.txt
	cd backend && alembic upgrade head
	cd backend && python scripts/seed_data.py
	@echo "Setup complete. Run make dev."

dev:
	docker compose up -d postgres redis
	cd backend && uvicorn main:app --reload --host 0.0.0.0 --port 8000 &
	cd frontend && npm run dev

build:
	docker compose build

migrate:
	cd backend && alembic revision --autogenerate -m "$(MSG)"
	cd backend && alembic upgrade head

seed:
	cd backend && python scripts/seed_data.py

test:
	cd backend && pytest tests/ -v --asyncio-mode=auto

deploy:
	./scripts/deploy.sh

clean:
	docker compose down -v

logs:
	docker compose logs -f backend celery_worker
