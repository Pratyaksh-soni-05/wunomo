import structlog

log = structlog.get_logger()

RESULT_PREVIEW_ROW_CAP = 20


async def log_transform_run(
    *, tenant_id: str, user_id: str, session_id: str | None,
    source_id: str | None, transform_type: str, origin: str,
    code: str, result: dict,
) -> None:
    """Persist a TransformRun row for a real transform execution (SQL or
    pandas) so the Transforms History tab has real data to list and replay.
    Only called for actual executions (POST /run/sql, /run/pandas, and the
    chat-agent equivalents with dry_run=False) — never for dry-runs/EXPLAIN
    or generation-only calls, matching the approved Phase 13 scope.

    Best-effort — a DB hiccup here must never break the actual transform
    result already computed and about to be returned to the caller.
    """
    from database import AsyncSessionLocal
    from models.all_models import TransformRun

    is_error = "error" in result
    rows = result.get("rows") if not is_error else None
    preview = rows[:RESULT_PREVIEW_ROW_CAP] if rows else None

    try:
        async with AsyncSessionLocal() as db:
            db.add(TransformRun(
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
                source_id=source_id,
                transform_type=transform_type,
                origin=origin,
                code=code,
                status="error" if is_error else "success",
                row_count=result.get("row_count") if not is_error else None,
                duration_ms=result.get("duration_ms") if not is_error else None,
                error_message=result.get("error") if is_error else None,
                result_preview=preview,
            ))
            await db.commit()
    except Exception as exc:
        log.warning("transform_run_log.failed", error=str(exc))
