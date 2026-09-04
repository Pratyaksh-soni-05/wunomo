from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import structlog
import uvicorn
import uuid
from sqlalchemy import text


from config import settings
from database import engine, Base
from api.v1 import (
    auth, chat, sources, pipelines, runs,
    incidents, quality, governance, uploads,
    analytics, approvals, transformations,
    cicd, onboarding, catalog, team, billing, settings as settings_router,
    api_keys, tasks, agents, projects, channels,
)


log = structlog.get_logger()



@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Model liveness check (2026-09-03, see GOTCHAS.md) -- a real 404 gets
    # logged loudly (model_liveness_check_failed) and is inspectable via
    # GET /health/models afterward, but a failure in the check's OWN
    # infrastructure (Redis briefly unavailable, a network blip reaching
    # a provider) must never prevent the app from starting -- this is a
    # visibility improvement, not a new hard dependency for boot.
    try:
        from services.model_liveness import check_configured_models
        await check_configured_models()
    except Exception as exc:
        log.error("model_liveness_check_errored", error=str(exc))

    log.info("axiom.startup", env=settings.APP_ENV, version="1.0.0")
    yield
    await engine.dispose()
    log.info("axiom.shutdown")



app = FastAPI(
    title="AXIOM — AI DataOps Engineer",
    description=(
        "AI Workforce Systems · AXIOM DataOps Engineer\n\n"
        "Autonomous AI agent that monitors, diagnoses, and manages "
        "data pipelines via natural language."
    ),
    version="1.0.0",
    lifespan=lifespan,
    redirect_slashes=False,
    docs_url="/docs" if settings.APP_ENV == "development" else None,
    redoc_url="/redoc" if settings.APP_ENV == "development" else None,
    openapi_url="/openapi.json" if settings.APP_ENV == "development" else None,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    with structlog.contextvars.bound_contextvars(request_id=request_id):
        response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response



@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.error(
        "unhandled_exception",
        path=request.url.path,
        method=request.method,
        error=str(exc),
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected error occurred. Check server logs."},
    )



# Phase 1 — Foundation
app.include_router(auth.router,            prefix="/api/v1/auth",            tags=["Auth"])
app.include_router(uploads.router,         prefix="/api/v1/uploads",         tags=["Uploads"])


# Phase 2 — Core DataOps
app.include_router(sources.router,         prefix="/api/v1/sources",         tags=["Sources"])
app.include_router(pipelines.router,       prefix="/api/v1/pipelines",       tags=["Pipelines"])
app.include_router(runs.router,            prefix="/api/v1/runs",            tags=["Runs"])
app.include_router(quality.router,         prefix="/api/v1/quality",         tags=["Quality"])
app.include_router(incidents.router,       prefix="/api/v1/incidents",       tags=["Incidents"])


# Phase 3 — Observability, Governance, Reporting
app.include_router(governance.router,      prefix="/api/v1/governance",      tags=["Governance"])
app.include_router(approvals.router,       prefix="/api/v1/approvals",       tags=["Approvals"])
app.include_router(analytics.router,       prefix="/api/v1/analytics",       tags=["Analytics"])


# Phase 4 — Transformation
app.include_router(transformations.router, prefix="/api/v1/transformations", tags=["Transformations"])
app.include_router(catalog.router,         prefix="/api/v1/catalog",         tags=["Catalog"])


# Phase 5 — CI/CD
app.include_router(cicd.router,            prefix="/api/v1/cicd",            tags=["CI/CD"])


# Agent
app.include_router(chat.router,            prefix="/api/v1/chat",            tags=["Chat"])


# Frontend Phase 4 — Onboarding
app.include_router(onboarding.router,      prefix="/api/v1/onboarding",      tags=["Onboarding"])

# Phase 15 — Team invites
app.include_router(team.router,            prefix="/api/v1/team",            tags=["Team"])
app.include_router(billing.router,         prefix="/api/v1/billing",         tags=["Billing"])

# Phase 16 — Settings persistence
app.include_router(settings_router.router,  prefix="/api/v1/settings",        tags=["Settings"])
app.include_router(api_keys.router,        prefix="/api/v1/api-keys",        tags=["API Keys"])
app.include_router(tasks.router,           prefix="/api/v1/tasks",           tags=["Tasks"])

# Wunomo Projects Phase 1 — agent source-scope management + hiring
app.include_router(agents.router,          prefix="/api/v1/agents",          tags=["Agents"])
app.include_router(projects.router,        prefix="/api/v1/projects",        tags=["Projects"])

# Wunomo Projects Phase 2 — channels
app.include_router(channels.router,        prefix="/api/v1/channels",        tags=["Channels"])



@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok", "env": settings.APP_ENV, "version": "1.0.0"}



@app.get("/health/db", tags=["Health"])
async def health_db():
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok", "db": "connected"}
    except Exception as exc:
        log.error("health.db.failed", error=str(exc))
        return JSONResponse(
            status_code=503,
            content={"status": "error", "db": "unreachable", "detail": str(exc)},
        )


@app.get("/health/models", tags=["Health"])
async def health_models(force: bool = False):
    """Cached model-liveness result (see services/model_liveness.py) --
    ?force=true bypasses the cache and re-pings every configured model
    right now. 503 whenever any configured model isn't reachable, so a
    monitor polling this can alert on a provider deprecation within
    minutes instead of discovering it mid-incident."""
    from services.model_liveness import check_configured_models
    payload = await check_configured_models(force=force)
    dead = [r for r in payload["results"] if r["status"] != "ok"]
    status_code = 503 if dead else 200
    return JSONResponse(status_code=status_code, content=payload)


@app.get("/health/tasks", tags=["Health"])
async def health_tasks():
    """Backlog visibility for the auto-advance loop (Wunomo Projects
    Phase 3, item 71): a live, on-demand answer to "is the beat tick's
    25/tick cap draining the backlog or falling behind it" -- previously
    only visible by grepping advance_active_tasks_dispatched log lines.
    Uses the same RUNNABLE_TASK_STATUSES services/tasks.py's beat tick
    selects against, so this can never disagree with what the tick
    itself considers runnable. Broken down by status so a growing QUEUED
    count (plans piling up unstarted) reads differently from a growing
    PAUSED_QUOTA_EXCEEDED one (a quota problem, not a scheduler one)."""
    from sqlalchemy import func, select
    from database import AsyncSessionLocal
    from models.all_models import RUNNABLE_TASK_STATUSES, Task
    from services.tasks import ADVANCE_BATCH_SIZE

    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(Task.status, func.count())
            .where(Task.status.in_(RUNNABLE_TASK_STATUSES))
            .group_by(Task.status)
        )
        by_status = {status.value: count for status, count in r.all()}

    total = sum(by_status.values())
    return {
        "total_runnable": total,
        "by_status": by_status,
        "batch_size": ADVANCE_BATCH_SIZE,
        # Ceiling division: how many 60s ticks it would take to drain the
        # current backlog if zero new runnable work ever arrived --
        # optimistic on purpose (real arrivals only push this further
        # out), still useful as a lower bound on "how far behind is it."
        "estimated_ticks_to_drain_if_no_new_work": -(-total // ADVANCE_BATCH_SIZE) if total else 0,
    }



if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.APP_ENV == "development",
        log_level="info",
    )