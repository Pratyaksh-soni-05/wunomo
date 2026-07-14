import traceback, sys

# Test 1: Can we import RunStatus cleanly?
try:
    from models.all_models import RunStatus
    print("RunStatus values:", [e.value for e in RunStatus])
except Exception as e:
    print("RunStatus import ERROR:", e)

# Test 2: Can we import Monitor cleanly?
try:
    from modules.observability.monitor import Monitor
    print("Monitor import OK")
except Exception as e:
    print("Monitor import ERROR:", repr(e))
    traceback.print_exc()

# Test 3: Can we instantiate Monitor without calling check_freshness?
try:
    m = Monitor("test-tenant")
    print("Monitor instantiate OK")
except Exception as e:
    print("Monitor instantiate ERROR:", repr(e))
    traceback.print_exc()

# Test 4: What does check_freshness actually raise?
import asyncio
async def test_freshness():
    try:
        m = Monitor("test-tenant")
        result = await m.check_freshness()
        print("check_freshness result:", result)
    except Exception as e:
        print("check_freshness RAISED:", repr(e))
        traceback.print_exc()

asyncio.run(test_freshness())
