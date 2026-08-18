import os
os.environ["APP_ENV"] = "test"  # MUST be before all project imports

import pytest_asyncio
import asyncio
from httpx import AsyncClient, ASGITransport


@pytest_asyncio.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture(scope="session")
async def client():
    from main import app  # imported AFTER env var is set
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# Item 47: services/auth_service.py's email-code rate limiter writes real,
# TTL'd Redis state (otp:hourly:{email}, otp:ip:{ip}, otp:cooldown:{email},
# otp:lockout:{email}, otp:exhausted_streak:{email}) that outlives any
# single test. Every test client request goes through the same source
# "IP" (the ASGI test transport), so otp:ip:{ip} in particular accumulates
# across every test in the run regardless of which file or email is
# involved - a sufficiently broad pytest selection can exhaust
# MAX_REQUESTS_PER_IP_PER_HOUR purely from the suite's own combined
# request volume, spuriously failing whichever email-code test happens to
# run once the shared budget is gone (this is exactly what made
# test_email_code_auth.py's rate-limit tests order/selection-dependent -
# see WALKTHROUGH_FINDINGS_2026-08.md item 47). Autouse + function-scoped:
# every test starts with a guaranteed-clean rate-limit slate, so the
# result no longer depends on what ran before it or how broad -k was.
@pytest_asyncio.fixture(autouse=True)
async def _reset_email_code_rate_limits():
    import services.auth_service as auth_service
    redis = auth_service._redis()
    async for key in redis.scan_iter(match="otp:*"):
        await redis.delete(key)
    yield