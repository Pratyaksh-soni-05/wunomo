"""Seed the database with demo tenant, user, pipeline, and sample quality rules."""
import asyncio, uuid
from datetime import datetime
from database import AsyncSessionLocal, engine, Base
from models.all_models import (Tenant, User, DataSource, Pipeline,
                                PipelineRun, QualityRule, SourceType,
                                PipelineStatus, RunStatus)
from passlib.context import CryptContext


pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


TENANT_ID   = "demo-tenant-001"
USER_ID     = "demo-user-001"
SOURCE_ID   = "demo-source-001"
PIPELINE_ID = "demo-pipeline-001"


async def seed():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        existing = await db.get(Tenant, TENANT_ID)
        if existing:
            print("Demo data already seeded.")
            return

        db.add(Tenant(id=TENANT_ID, name="Acme Corp", slug="acme-corp",
                      plan="growth", is_active=True, created_at=datetime.utcnow()))

        db.add(User(id=USER_ID, tenant_id=TENANT_ID, email="demo@acme.com",
                    hashed_password=pwd_ctx.hash("demo1234"), full_name="Demo User",
                    role="owner", is_active=True, created_at=datetime.utcnow()))

        db.add(DataSource(id=SOURCE_ID, tenant_id=TENANT_ID, name="Sales Database",
                          source_type=SourceType.POSTGRES,
                          connection_config={"host": "postgres", "port": 5432,
                                             "database": "dataops", "user": "dataops_user",
                                             "password": "changeme"},
                          tags=["sales", "production"], owner="data-team",
                          created_at=datetime.utcnow()))

        db.add(Pipeline(id=PIPELINE_ID, tenant_id=TENANT_ID, source_id=SOURCE_ID,
                        name="Daily Sales Ingestion",
                        description="Ingest and validate daily sales data",
                        status=PipelineStatus.ACTIVE, schedule_cron="0 6 * * *",
                        pipeline_config={"steps": ["ingest", "validate", "transform", "publish"]},
                        sla_minutes=120, version=1, created_at=datetime.utcnow()))

        for i in range(5):
            db.add(PipelineRun(id=str(uuid.uuid4()), pipeline_id=PIPELINE_ID,
                               tenant_id=TENANT_ID, status=RunStatus.SUCCESS,
                               triggered_by="schedule", rows_processed=10000 + i * 500,
                               quality_score=95.0 + i * 0.5, duration_seconds=120 + i * 5,
                               started_at=datetime.utcnow(), completed_at=datetime.utcnow(),
                               created_at=datetime.utcnow()))

        for rule_type, col, cfg, sev, blocking in [
            ("not_null",       "order_id", {},                                  "critical", True),
            ("range",          "amount",   {"min": 0, "max": 100000},           "high",     True),
            ("accepted_values","status",   {"values": ["pending","paid","cancelled"]}, "medium", False),
        ]:
            db.add(QualityRule(id=str(uuid.uuid4()), pipeline_id=PIPELINE_ID,
                               tenant_id=TENANT_ID,
                               name=f"{rule_type}_{col}",
                               rule_type=rule_type, column_name=col, rule_config=cfg,
                               severity=sev, is_blocking=blocking,
                               pass_count=50, fail_count=0, created_at=datetime.utcnow()))

        await db.commit()

    print("\n✅  Demo data seeded successfully.")
    print("   Login:   demo@acme.com  /  demo1234")
    print("   API:     http://localhost:8000/docs")
    print("   UI:      http://localhost:3000")


if __name__ == "__main__":
    asyncio.run(seed())