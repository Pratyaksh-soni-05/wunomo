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