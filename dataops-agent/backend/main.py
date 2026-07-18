from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
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
)


log = structlog.get_logger()



@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
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



@app.websocket("/ws/chat/{tenant_id}/{session_id}")
async def websocket_chat(ws: WebSocket, tenant_id: str, session_id: str):
    await ws.accept()
    log.info("ws.connect", tenant_id=tenant_id, session_id=session_id)
    from agent.dataops_agent import run_agent
    try:
        while True:
            try:
                data = await ws.receive_json()
            except Exception:
                await ws.send_json({"type": "error", "detail": "Invalid JSON payload"})
                continue

            message = data.get("message", "").strip()
            if not message:
                await ws.send_json({"type": "error", "detail": "Empty message"})
                continue

            try:
                result = await run_agent(
                    user_message=message,
                    tenant_id=tenant_id,
                    user_id=data.get("user_id", "anon"),
                    session_id=session_id,
                    personality_mode=data.get("personality_mode", "engineer"),
                    operation_mode=data.get("operation_mode", "assisted"),
                )
                await ws.send_json({
                    "type":              "response",
                    "content":           result["response"],
                    "pending_approvals": result.get("pending_approvals", []),
                    "timestamp":         result.get("timestamp", ""),
                })
            except Exception as exc:
                log.error("ws.agent_error", tenant_id=tenant_id, error=str(exc))
                await ws.send_json({"type": "error", "detail": f"Agent error: {str(exc)}"})

    except WebSocketDisconnect:
        log.info("ws.disconnect", tenant_id=tenant_id, session_id=session_id)
    except Exception as exc:
        log.error("ws.fatal_error", tenant_id=tenant_id, error=str(exc))



if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.APP_ENV == "development",
        log_level="info",
    )