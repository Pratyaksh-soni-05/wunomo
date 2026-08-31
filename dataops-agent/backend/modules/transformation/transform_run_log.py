import structlog
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError

from services.tenant_context import with_tenant_context

log = structlog.get_logger()

RESULT_PREVIEW_ROW_CAP = 20


@with_tenant_context
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
    except (OperationalError, InterfaceError, DBAPIError) as exc:
        # Genuinely transient: connection dropped, pool exhausted, DB briefly
        # unreachable. The transform itself already succeeded and its result is
        # about to be returned; losing one audit row to a blip should not turn a
        # successful transform into a failed request.
        log.warning("transform_run_log.transient_failure",
                    tenant_id=tenant_id, source_id=source_id,
                    transform_type=transform_type, error=str(exc))
    except Exception as exc:
        # Everything else — and specifically InsufficientPrivilege from a
        # Row-Level Security denial — is NOT transient and must not be
        # swallowed. Before this, an RLS rejection here was caught, logged at
        # warning, and discarded: the audit trail would silently stop recording
        # transform runs with nothing surfaced to the caller and no failed
        # request to notice. A security control that fails open and quiet is
        # worse than one that isn't there, because it still reads as present.
        #
        # NOTE for Master Ranking Item #9 (tamper-evident audit trail): this
        # re-raise makes a *failed* audit write loud, but it does not make a
        # *successful* one tamper-evident. These rows are still plain,
        # mutable, unsigned, unchained records that anyone with UPDATE on the
        # table can rewrite after the fact. Item #9 is what closes that; treat
        # this comment as the pointer from here to there.
        log.error("transform_run_log.write_failed",
                  tenant_id=tenant_id, user_id=user_id, session_id=session_id,
                  source_id=source_id, transform_type=transform_type,
                  origin=origin, error_type=type(exc).__name__, error=str(exc))
        raise
