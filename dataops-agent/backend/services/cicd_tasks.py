# backend/services/cicd_tasks.py

import asyncio
import structlog
from datetime import datetime, timezone
from uuid import UUID

from celery import shared_task
from sqlalchemy import select, desc

from database import AsyncSessionLocal
from models.cicd import PipelineCommit, CICDStatus, GateDecision

log = structlog.get_logger()

# ─── Risk Thresholds ─────────────────────────────────────────────────────────
AUTO_APPROVE_THRESHOLD = 60


# ─── Risk Scorer ─────────────────────────────────────────────────────────────

def calculate_risk_score(check_results: dict, changed_files: list) -> float:
    score = 0.0

    if check_results.get("schema_check", {}).get("drift_detected"):
        score += 40

    new_files = [f for f in changed_files if "new" in f.lower() or "add" in f.lower()]
    if new_files:
        score += 20

    dangerous_sql = check_results.get("sql_check", {}).get("dangerous_keywords", [])
    if dangerous_sql:
        score += 30

    recent_failure_rate = check_results.get("history_check", {}).get("recent_failure_rate", 0)
    if recent_failure_rate > 0.3:
        score += 20
    elif recent_failure_rate > 0.1:
        score += 10

    complexity = check_results.get("sql_check", {}).get("complexity_score", 0)
    if complexity > 8:
        score += 15
    elif complexity > 5:
        score += 8

    return min(score, 100.0)


# ─── Check 1: Schema Drift ───────────────────────────────────────────────────

async def run_schema_check(db, tenant_id: UUID, pipeline_id, changed_files: list) -> dict:
    try:
        from models.schema_snapshot import SchemaSnapshot

        if not pipeline_id:
            return {"status": "skipped", "reason": "no pipeline linked", "drift_detected": False}

        result = await db.execute(
            select(SchemaSnapshot)
            .where(SchemaSnapshot.pipeline_id == pipeline_id)
            .order_by(desc(SchemaSnapshot.created_at))
            .limit(1)
        )
        snapshot = result.scalar_one_or_none()

        if not snapshot:
            return {"status": "passed", "drift_detected": False, "note": "no prior snapshot"}

        pipeline_files = [f for f in changed_files if "pipeline" in f.lower()]
        if pipeline_files and snapshot:
            return {
                "status": "warning",
                "drift_detected": True,
                "message": "Pipeline definition changed — schema drift review recommended",
                "snapshot_id": str(snapshot.id),
            }

        return {"status": "passed", "drift_detected": False}

    except ImportError:
        return {"status": "skipped", "reason": "SchemaSnapshot model not found", "drift_detected": False}
    except Exception as e:
        log.error("cicd.schema_check_error", error=str(e))
        return {"status": "error", "error": str(e), "drift_detected": False}


# ─── Check 2: Quality Rule Dry-Run ──────────────────────────────────────────

async def run_quality_dry_run(db, tenant_id: UUID, pipeline_id) -> dict:
    try:
        if not pipeline_id:
            return {"status": "skipped", "reason": "no pipeline linked", "rules_checked": 0}

        from models.all_models import QualityRule

        result = await db.execute(
            select(QualityRule).where(
                QualityRule.pipeline_id == pipeline_id,
                QualityRule.tenant_id == str(tenant_id),
                QualityRule.is_active == True,
            )
        )
        rules = result.scalars().all()

        if not rules:
            return {"status": "passed", "rules_checked": 0, "note": "no rules attached"}

        failed_rules = []
        for rule in rules:
            if not rule.rule_type or not rule.rule_config:
                failed_rules.append({"rule_id": str(rule.id), "issue": "incomplete config"})

        return {
            "status": "failed" if failed_rules else "passed",
            "rules_checked": len(rules),
            "failed_rules": failed_rules,
        }

    except ImportError:
        return {"status": "skipped", "reason": "QualityRule model not found", "rules_checked": 0}
    except Exception as e:
        log.error("cicd.quality_dry_run_error", error=str(e))
        return {"status": "error", "error": str(e), "rules_checked": 0}


# ─── Check 3: SQL Static Analysis ────────────────────────────────────────────

def run_sql_static_analysis(changed_files: list, commit_message: str) -> dict:
    BLOCKED_KEYWORDS = [
        "DROP TABLE", "TRUNCATE", "DELETE FROM",
        "DROP DATABASE", "ALTER TABLE DROP",
    ]
    HIGH_COMPLEXITY_INDICATORS = [
        "WITH RECURSIVE", "CROSS JOIN", "FULL OUTER JOIN", "UNNEST",
    ]

    combined_upper = (" ".join(changed_files) + " " + commit_message).upper()

    dangerous = [kw for kw in BLOCKED_KEYWORDS if kw in combined_upper]
    complexity_hits = [kw for kw in HIGH_COMPLEXITY_INDICATORS if kw in combined_upper]

    return {
        "status": "warning" if dangerous else "passed",
        "dangerous_keywords": dangerous,
        "complexity_indicators": complexity_hits,
        "complexity_score": len(complexity_hits) * 3,
    }


# ─── Check 4: Pipeline Run History ──────────────────────────────────────────

async def run_history_check(db, tenant_id: UUID, pipeline_id) -> dict:
    try:
        if not pipeline_id:
            return {"status": "skipped", "recent_failure_rate": 0, "runs_checked": 0}

        from models.all_models import PipelineRun

        result = await db.execute(
            select(PipelineRun)
            .where(
                PipelineRun.pipeline_id == pipeline_id,
                PipelineRun.tenant_id == str(tenant_id),
            )
            .order_by(PipelineRun.started_at.desc())
            .limit(10)
        )
        recent_runs = result.scalars().all()

        if not recent_runs:
            return {"status": "passed", "recent_failure_rate": 0, "runs_checked": 0}

        failures = sum(
            1 for r in recent_runs
            if getattr(r, "status", "") in ("failed", "error")
        )
        rate = failures / len(recent_runs)

        return {
            "status": "warning" if rate > 0.3 else "passed",
            "recent_failure_rate": round(rate, 2),
            "runs_checked": len(recent_runs),
            "failures": failures,
        }

    except ImportError:
        return {"status": "skipped", "recent_failure_rate": 0, "runs_checked": 0}
    except Exception as e:
        log.error("cicd.history_check_error", error=str(e))
        return {"status": "error", "recent_failure_rate": 0, "runs_checked": 0}


# ─── Main CI Runner Task ─────────────────────────────────────────────────────

@shared_task(
    bind=True,
    name="cicd.run_ci_pipeline",
    max_retries=2,
    default_retry_delay=30,
)
def run_ci_pipeline(self, commit_id: str, tenant_id: str) -> None:
    """
    Main Celery task — orchestrates all 4 CI checks, scores risk,
    and routes to auto-deploy or human approval gate.
    """

    async def _run() -> None:
        bound_log = log.bind(commit_id=commit_id, tenant_id=tenant_id)

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(PipelineCommit).where(PipelineCommit.id == commit_id)
            )
            commit = result.scalar_one_or_none()

            if not commit:
                bound_log.error("cicd.commit_not_found")
                return

            commit.ci_status = CICDStatus.running
            await db.commit()
            bound_log.info("cicd.ci_started", sha=commit.commit_sha[:8], branch=commit.branch)

            tid = UUID(tenant_id)
            pid = commit.pipeline_id
            changed = commit.changed_files or []
            msg = commit.commit_message or ""

            check_results: dict = {}
            try:
                check_results["schema_check"] = await run_schema_check(db, tid, pid, changed)
                check_results["quality_check"] = await run_quality_dry_run(db, tid, pid)
                check_results["sql_check"]     = run_sql_static_analysis(changed, msg)
                check_results["history_check"] = await run_history_check(db, tid, pid)

            except Exception as e:
                bound_log.error("cicd.check_error", error=str(e))
                commit.ci_status = CICDStatus.failed
                commit.error_message = str(e)
                commit.completed_at = datetime.now(timezone.utc)
                await db.commit()

                # ── Notify CI failed due to crash ────────────────────────────
                await _safe_notify("ci_failed", {
                    "sha": commit.commit_sha,
                    "branch": commit.branch,
                    "risk_score": 0,
                    "error": str(e),
                })
                return

            risk_score = calculate_risk_score(check_results, changed)

            any_failed = any(
                isinstance(r, dict) and r.get("status") == "failed"
                for r in check_results.values()
            )
            ci_status = CICDStatus.failed if any_failed else CICDStatus.passed

            if ci_status == CICDStatus.failed or risk_score > AUTO_APPROVE_THRESHOLD:
                gate = GateDecision.pending_approval
            else:
                gate = GateDecision.auto_approved

            commit.check_results = check_results
            commit.risk_score    = risk_score
            commit.ci_status     = ci_status
            commit.gate_decision = gate
            commit.completed_at  = datetime.now(timezone.utc)
            await db.commit()

            bound_log.info(
                "cicd.ci_completed",
                sha=commit.commit_sha[:8],
                ci_status=ci_status,
                gate=gate,
                risk_score=risk_score,
            )

            # ── Notify CI pass/fail ───────────────────────────────────────────
            await _safe_notify(
                "ci_passed" if ci_status == CICDStatus.passed else "ci_failed",
                {
                    "sha": commit.commit_sha,
                    "branch": commit.branch,
                    "risk_score": risk_score,
                    "error": commit.error_message or "",
                }
            )

            # ─── Route: auto-deploy or human gate ────────────────────────────
            if gate == GateDecision.auto_approved:
                try:
                    from services.cicd_deployment import deploy_pipeline
                    deploy_pipeline.delay(commit_id, tenant_id, "auto")
                    bound_log.info("cicd.auto_deploy_queued", sha=commit.commit_sha[:8])
                except ImportError:
                    bound_log.warning(
                        "cicd.deploy_skipped",
                        reason="cicd_deployment not yet built (Phase 4)",
                        sha=commit.commit_sha[:8],
                    )
            else:
                # PipelineCommit.gate_decision (just set above) is the real,
                # role-gated, tested approval path - see CLAUDE.md's now-
                # resolved "CI/CD high-risk commits double-book their
                # approval into two never-linked tables" entry. No separate
                # PolicyEngine ApprovalRequest is created here anymore.

                # ── Notify approval required ──────────────────────────────────
                await _safe_notify("approval_required", {
                    "sha": commit.commit_sha,
                    "risk_score": risk_score,
                    "message": f"Risk score {risk_score:.0f}/100 — manual review needed",
                })

                bound_log.info(
                    "cicd.pending_human_approval",
                    sha=commit.commit_sha[:8],
                    risk_score=risk_score,
                )

    async def _run_with_fresh_pool() -> None:
        # See services/tasks.py — a retried Celery task calls asyncio.run()
        # again on a new loop, and the shared engine's pooled connections
        # from the previous (closed) loop must be dropped first.
        from database import engine
        await engine.dispose()
        await _run()

    try:
        asyncio.run(_run_with_fresh_pool())
    except Exception as exc:
        log.error("cicd.task_crashed", commit_id=commit_id, error=str(exc))
        raise self.retry(exc=exc, countdown=30)


# ─── Safe Notify Helper ───────────────────────────────────────────────────────

async def _safe_notify(event: str, payload: dict) -> None:
    """
    Fire-and-forget Slack notification.
    Never raises — a broken Slack webhook must never crash the CI pipeline.
    """
    try:
        from services.cicd_notify import notify
        await notify(event, payload)
    except Exception as e:
        log.warning("cicd.notify_skipped", notify_event=event, error=str(e))