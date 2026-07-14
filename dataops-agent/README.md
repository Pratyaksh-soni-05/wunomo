# AXIOM — AI DataOps Engineer
> Part of [AI Workforce Systems](https://aiworkforce.systems) — the modular AI workforce platform.

An autonomous AI agent that monitors, debugs, and manages your data pipelines. Talk to it like a senior data engineer.

---

## Quick Start (Docker — Recommended)

**Prerequisites:** Docker Desktop installed and running.

```bash
# 1. Clone and enter the project
git clone <your-repo-url>
cd dataops-agent

# 2. Set up environment
cp .env.example .env
# Edit .env — add your GEMINI_API_KEY and GROQ_API_KEY

# 3. Start everything (DB + Redis + Backend + Celery)
docker compose up --build -d

# 4. Run database migrations
docker compose exec backend alembic upgrade head

# 5. Done! Open the API docs
open http://localhost:8000/docs
```

---

## Quick Start (Local Dev)

```bash
# 1. Create virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Mac/Linux

# 2. Install dependencies
cd backend
pip install -r requirements.txt

# 3. Start Postgres + Redis via Docker (infra only)
docker compose up -d postgres redis

# 4. Copy and configure env
cp ../.env.example ../.env

# 5. Run migrations
alembic upgrade head

# 6. Start the API
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

---

## Running Tests

```bash
cd backend
pytest tests/ -v
# Expected: 10 passed
```

---

## Architecture
dataops-agent/
├── backend/
│ ├── api/v1/ # REST endpoints (auth, chat, sources, pipelines...)
│ ├── agent/ # LangGraph agent + personality modes
│ ├── modules/ # Ingestion, quality, orchestration, observability
│ ├── models/ # SQLAlchemy ORM models
│ ├── services/ # LLM service, Celery tasks
│ └── tests/ # Pytest test suite
├── frontend/ # (Coming soon)
├── docker-compose.yml
└── .env.example


---

## API Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/v1/auth/register` | ❌ | Register tenant + owner |
| POST | `/api/v1/auth/login` | ❌ | Get JWT token |
| GET | `/api/v1/auth/me` | ✅ | Current user info |
| POST | `/api/v1/chat` | ✅ | Chat with AXIOM |
| WS | `/ws/chat/{tenant_id}/{session_id}` | ✅ | Streaming chat |
| GET | `/api/v1/sources` | ✅ | List data sources |
| GET | `/api/v1/pipelines` | ✅ | List pipelines |
| GET | `/api/v1/incidents` | ✅ | Open incidents |
| GET | `/api/v1/analytics` | ✅ | Usage analytics |
| GET | `/api/v1/approvals` | ✅ | Pending approvals |

Full interactive docs: `http://localhost:8000/docs`

---

## Personality Modes

| Mode | Audience | Style |
|------|----------|-------|
| `engineer` | Data engineers | Technical — SQL, root-cause, schema diagnostics |
| `founder` | CEOs / Founders | Business impact — cost, ETA, what broke |
| `analyst` | Business analysts | Dataset readiness, KPIs, freshness |
| `auditor` | Compliance | Lineage, change history, policy evidence |

---

## Operation Modes

| Mode | Behaviour |
|------|-----------|
| `advisory` | Recommends only, never executes |
| `assisted` | Executes safe actions, routes risky ones to approval |
| `autonomous` | Executes all approved workflows automatically |
| `audit` | Read-only — inspect and report only |

---

## Environment Variables

See `.env.example` for all required variables. Key ones:

```env
GEMINI_API_KEY=your-key-here     # Primary LLM
GROQ_API_KEY=your-key-here       # Fallback LLM
JWT_SECRET=change-this           # Auth signing key
POSTGRES_PASSWORD=changeme       # DB password
```

---

## Tech Stack

- **API:** FastAPI + Python 3.11
- **Agent:** LangGraph + LangChain
- **LLMs:** Gemini 2.0 Flash (primary) + Llama 3.3 70B via Groq (fallback)
- **DB:** PostgreSQL 16 + SQLAlchemy async
- **Queue:** Celery + Redis
- **Auth:** JWT (python-jose)
- **Tests:** Pytest + pytest-asyncio

---

## License

Proprietary — AI Workforce Systems © 2026