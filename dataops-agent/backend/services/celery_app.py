from celery import Celery
from config import settings

celery_app = Celery(
    "dataops",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "services.tasks",
        "services.cicd_tasks",
        "services.cicd_deployment",
        "services.cicd_monitor",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
)

celery_app.conf.beat_schedule = {
    # Existing tasks — use full module.function path since no name= set
    "check-freshness-15min": {
        "task": "services.tasks.check_all_freshness",
        "schedule": 900.0,
    },
    "anomaly-detection-1hr": {
        "task": "services.tasks.run_anomaly_detection",
        "schedule": 3600.0,
    },
    # The real, live scheduled-pipelines mechanism (Phase 19 fix) - polls
    # every active pipeline's schedule_cron directly against the DB each
    # tick. Replaces the dynamic per-pipeline beat_schedule injection design
    # in modules/orchestration/scheduler.py, which never actually reached
    # this process's schedule (see that module's docstring for why).
    "check-scheduled-pipelines-1min": {
        "task": "services.tasks.check_scheduled_pipelines",
        "schedule": 60.0,
    },
    # Auto-advance loop (Wunomo Projects Phase 3, item 71/slice 10) -- same
    # 60s cadence as check-scheduled-pipelines-1min above, deliberately not
    # tighter: execute_next_step() itself already has its own internal
    # retry-backoff sleeps, and a conservative interval keeps a runaway
    # task's wall-clock/step-budget caps compressing into minutes rather
    # than seconds if the caps ever need to fire.
    "advance-active-tasks-1min": {
        "task": "services.tasks.advance_active_tasks",
        "schedule": 60.0,
    },
    # Per-agent scheduled work (Wunomo Projects Phase 4, slice 14) -- same
    # 60s cadence and same reasoning as check-scheduled-pipelines-1min
    # above: polls every ACTIVE ScheduledAgentTask directly against the DB
    # each tick, cron-matched via croniter.
    "check-scheduled-agent-tasks-1min": {
        "task": "services.tasks.check_scheduled_agent_tasks",
        "schedule": 60.0,
    },
    "daily-reports-24hr": {
        "task": "services.tasks.generate_daily_reports",
        "schedule": 86400.0,
    },
    "cicd-post-deploy-health-check": {
        "task": "cicd.check_post_deploy_health",
        "schedule": 60.0,       # every 60 seconds
    },
    # CI/CD monitor — uses the explicit name= from @shared_task decorator
    #"cicd-post-deploy-monitor": {
        #"task": "cicd.check_post_deploy_health",
        #"schedule": 300.0,
    #},
}