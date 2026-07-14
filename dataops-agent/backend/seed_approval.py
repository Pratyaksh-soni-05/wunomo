import asyncio
from modules.governance.policy_engine import PolicyEngine

async def seed():
    engine = PolicyEngine('e078fbf3-59d0-40ec-8f9f-fbe8bf4cb9c1')
    result = await engine.create_request(
        user_id='37a26ee8-fd07-429f-95f8-80abacf6b2ab',
        session_id='test-session-001',
        action_name='rerun_pipeline',
        action_args={'pipeline_id': '013819ed-b928-4ef1-8270-0ae0eda0ce3f'},
        risk_level='medium',
        reason='Testing the approval flow'
    )
    print(result)

asyncio.run(seed())
