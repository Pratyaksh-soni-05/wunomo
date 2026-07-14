import structlog
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select, func, desc

from .auth import get_current_user
from database import AsyncSessionLocal
from models.all_models import (
    Pipeline, PipelineRun, DataSource, Incident,
    KpiValue, UsageMetric,
    PipelineStatus, RunStatus, IncidentStatus,
)
from modules.observability.monitor import Monitor

log = structlog.get_logger()
router = APIRouter()

def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)

class RecordKpiRequest(BaseModel):
    kpi_name: str
    value: float
    unit: Optional[str] = None
    pipeline_id: Optional[str] = None
    metadata: Optional[dict] = {}

class RecordUsageRequest(BaseModel):
    metric_type: str
    value: float
    pipeline_id: Optional[str] = None
    metadata: Optional[dict] = {}

# ------------------------------------------------------------------
# 0. Health
# ------------------------------------------------------------------

@router.get("/health")
async def analytics_health(user=Depends(get_current_user)):
    return {"status": "ok"}

# ------------------------------------------------------------------
# 1. System overview
# ------------------------------------------------------------------

@router.get("")
async def get_analytics_overview(
    window_days: int = Query(7, ge=1, le=90),
    user=Depends(get_current_user),
):
    tenant_id = user["tenant_id"]
    window_start = utcnow() - timedelta(days=window_days)

    try:
        async with AsyncSessionLocal() as db:
            pip_result = await db.execute(
                select(Pipeline.status, func.count(Pipeline.id))
                .where(Pipeline.tenant_id == tenant_id)
                .group_by(Pipeline.status)
            )
            pip_counts = {}
            for row in pip_result.all():
                if row[0] is not None:
                    try:
                        key = row[0].value if hasattr(row[0], 'value') else str(row[0])
                        pip_counts[key] = row[1]
                    except Exception:
                        pass

            runs_result = await db.execute(
                select(PipelineRun).where(
                    PipelineRun.tenant_id == tenant_id,
                    PipelineRun.created_at >= window_start,
                    PipelineRun.status.in_(["success", "failed"]),
                )
            )
            runs = runs_result.scalars().all()
            total_runs = len(runs)
            success_runs = sum(1 for r in runs if getattr(r.status, 'value', str(r.status)) == "success")
            failed_runs = total_runs - success_runs
            success_rate = round(success_runs / total_runs * 100, 2) if total_runs else 0.0
            scored = [r.quality_score for r in runs if r.quality_score is not None]

            scored = [r.quality_score for r in runs if r.quality_score is not None]
            avg_quality = round(sum(scored) / len(scored), 2) if scored else None

            inc_result = await db.execute(
                select(func.count(Incident.id)).where(
                    Incident.tenant_id == tenant_id,
                    Incident.status.in_(["open", "investigating"]),
                )
            )
            open_incidents = inc_result.scalar() or 0

            src_result = await db.execute(
                select(func.count(DataSource.id)).where(
                    DataSource.tenant_id == tenant_id,
                    DataSource.is_active == True,
                )
            )
            total_sources = src_result.scalar() or 0

        # Isolated freshness check — won't crash the whole endpoint
        stale_sources = 0
        try:
            monitor = Monitor(tenant_id)
            freshness = await monitor.check_freshness()
            stale_sources = len(freshness) if isinstance(freshness, list) else 0
        except Exception:
            pass

        return {
            "tenant_id": tenant_id,
            "evaluated_at": utcnow().isoformat(),
            "window_days": window_days,
            "pipelines": {
                "total": sum(pip_counts.values()),
                "active": pip_counts.get("active", 0),
                "paused": pip_counts.get("paused", 0),
                "draft": pip_counts.get("draft", 0),
                "archived": pip_counts.get("archived", 0),
            },
            "runs": {
                "total": total_runs,
                "success": success_runs,
                "failed": failed_runs,
                "success_rate_pct": success_rate,
            },
            "quality": {"avg_score": avg_quality},
            "incidents": {"open": open_incidents},
            "sources": {"total_active": total_sources, "stale": stale_sources},
        }
    except Exception as exc:
        log.error("analytics.overview.error", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))

# ------------------------------------------------------------------
# 2. Per-pipeline stats
# ------------------------------------------------------------------

@router.get("/pipelines")
async def get_pipeline_analytics(
    window_days: int = Query(7, ge=1, le=90),
    user=Depends(get_current_user),
):
    tenant_id = user["tenant_id"]
    
    try:
        async with AsyncSessionLocal() as db:
            pips_result = await db.execute(
                select(Pipeline).where(
                    Pipeline.tenant_id == tenant_id,
                    Pipeline.status == "active",
                )
            )
            pipelines = pips_result.scalars().all()

            results = []
            for pipeline in pipelines:
                try:
                    monitor = Monitor(tenant_id)
                    stats = await monitor.get_pipeline_stats(str(pipeline.id))
                    if "error" not in stats:
                        results.append(stats)
                except Exception:
                    results.append({
                    "pipeline_id": str(pipeline.id),
                    "name": pipeline.name,
                    "status": "active",
                    "error": "stats_unavailable"
                })

            return {"pipelines": results, "count": len(results)}

    except Exception as exc:
        log.error("analytics.pipelines.error", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))

# ------------------------------------------------------------------
# 3. Quality trends
# ------------------------------------------------------------------

@router.get("/quality")
async def get_quality_trends(
    pipeline_id: Optional[str] = Query(None),
    window_days: int = Query(14, ge=1, le=90),
    user=Depends(get_current_user),
):
    tenant_id = user["tenant_id"]
    window_start = utcnow() - timedelta(days=window_days)

    try:
        async with AsyncSessionLocal() as db:
            query = select(PipelineRun).where(
                PipelineRun.tenant_id == tenant_id,
                PipelineRun.created_at >= window_start,
                PipelineRun.status.in_(["success", "failed"]),
            )
            if pipeline_id:
                query = query.where(PipelineRun.pipeline_id == pipeline_id)
            result = await db.execute(query)
            runs = result.scalars().all()

            by_day: dict[str, dict] = {}
            for r in runs:
                day = (r.created_at or utcnow()).date().isoformat()
                if day not in by_day:
                    by_day[day] = {"date": day, "run_count": 0, "pass_count": 0,
                                   "fail_count": 0, "quality_scores": []}
                by_day[day]["run_count"] += 1
                if getattr(r.status, 'value', str(r.status)) == "success":
                    by_day[day]["pass_count"] += 1
                else:
                    by_day[day]["fail_count"] += 1
                if r.quality_score is not None:
                    by_day[day]["quality_scores"].append(r.quality_score)

            trends = []
            for day, data in sorted(by_day.items()):
                scores = data.pop("quality_scores")
                data["avg_quality_score"] = round(sum(scores) / len(scores), 2) if scores else None
                trends.append(data)

            return {"trends": trends, "window_days": window_days, "pipeline_id": pipeline_id}

    except Exception as exc:
        log.error("analytics.quality_trends.error", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))

# ------------------------------------------------------------------
# 4. KPI endpoints
# ------------------------------------------------------------------

@router.get("/kpis")
async def get_kpis(
    kpi_name: Optional[str] = Query(None),
    window_days: int = Query(30, ge=1, le=365),
    user=Depends(get_current_user),
):
    tenant_id = user["tenant_id"]
    window_start = utcnow() - timedelta(days=window_days)

    try:
        async with AsyncSessionLocal() as db:
            query = (
                select(KpiValue)
                .where(
                    KpiValue.tenant_id == tenant_id,
                    KpiValue.recorded_at >= window_start,
                )
                .order_by(desc(KpiValue.recorded_at))
            )
            if kpi_name:
                query = query.where(KpiValue.kpi_name == kpi_name)
            result = await db.execute(query)
            kpis = result.scalars().all()

            grouped: dict[str, list] = {}
            for k in kpis:
                grouped.setdefault(k.kpi_name, []).append(k)

            output = []
            for name, values in grouped.items():
                latest = values[0]
                trend = [
                    {
                        "value": v.value,
                        "unit": v.unit,
                        "recorded_at": v.recorded_at.isoformat() if v.recorded_at else None,
                    }
                    for v in values[:30]
                ]
                output.append({
                    "kpi_name": name,
                    "latest_value": latest.value,
                    "unit": latest.unit,
                    "last_recorded_at": latest.recorded_at.isoformat() if latest.recorded_at else None,
                    "trend": trend,
                })

            return {"kpis": output, "count": len(output)}

    except Exception as exc:
        log.error("analytics.kpis.error", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))

@router.post("/kpis", status_code=201)
async def record_kpi(
    body: RecordKpiRequest,
    user=Depends(get_current_user),
):
    try:
        async with AsyncSessionLocal() as db:
            kpi = KpiValue(
                tenant_id=user["tenant_id"],
                kpi_name=body.kpi_name,
                value=body.value,
                unit=body.unit,
                recorded_at=utcnow(),
            )
            db.add(kpi)
            await db.commit()
            await db.refresh(kpi)
            return {
                "kpi_id": str(kpi.id),
                "kpi_name": kpi.kpi_name,
                "value": kpi.value,
                "unit": kpi.unit,
                "recorded_at": kpi.recorded_at.isoformat(),
            }
    except Exception as exc:
        log.error("analytics.record_kpi.error", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))

# ------------------------------------------------------------------
# 5. Usage metrics
# ------------------------------------------------------------------

@router.get("/usage")
async def get_usage_metrics(
    metric_type: Optional[str] = Query(None),
    window_days: int = Query(30, ge=1, le=365),
    user=Depends(get_current_user),
):
    tenant_id = user["tenant_id"]
    window_start = utcnow() - timedelta(days=window_days)

    try:
        async with AsyncSessionLocal() as db:
            query = select(UsageMetric).where(
                UsageMetric.tenant_id == tenant_id,
                UsageMetric.recorded_at >= window_start,
            )
            if metric_type:
                query = query.where(UsageMetric.metric_type == metric_type)
            result = await db.execute(query)
            metrics = result.scalars().all()

            grouped: dict[str, dict[str, float]] = {}
            for m in metrics:
                mtype = m.metric_type
                day = (m.recorded_at or utcnow()).date().isoformat()
                grouped.setdefault(mtype, {})
                grouped[mtype][day] = grouped[mtype].get(day, 0.0) + m.value

            output = []
            for mtype, daily in grouped.items():
                total = sum(daily.values())
                trend = [{"date": d, "value": v} for d, v in sorted(daily.items())]
                output.append({
                    "metric_type": mtype,
                    "total": round(total, 4),
                    "daily_trend": trend,
                })

            return {"usage": output, "window_days": window_days}

    except Exception as exc:
        log.error("analytics.usage.error", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))
