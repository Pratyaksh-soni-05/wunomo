import uuid
import pytest

from modules.quality.business_rules import BusinessRules


async def _register(client, prefix="bizrules"):
    reg = await client.post("/api/v1/auth/register", json={
        "email": f"{prefix}-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234",
        "full_name": "Business Rules Test",
        "tenant_name": f"Business Rules Corp {uuid.uuid4().hex[:6]}",
    })
    body = reg.json()
    return body["access_token"], body["tenant_id"]


async def _make_pipeline(client, token):
    headers = {"Authorization": f"Bearer {token}"}
    pipe = await client.post("/api/v1/pipelines/", json={"name": "Business Rules Pipeline"}, headers=headers)
    return pipe.json()["id"]


@pytest.mark.asyncio
async def test_list_rules_does_not_crash_on_the_real_engine_return_shape(client):
    """Regression test for the tracked Known-broken bug: QualityRuleEngine.
    list_rules() returns {"rules": [...], "count": N} (a dict), but
    BusinessRules.list_rules() used to iterate it directly without
    unwrapping — iterating a dict iterates its *keys* (the string "rules"),
    so `r.get(...)` raised AttributeError: 'str' object has no attribute
    'get' on every call, even with zero rules configured."""
    token, tenant_id = await _register(client)
    pipeline_id = await _make_pipeline(client, token)

    rules = await BusinessRules(tenant_id).list_rules(pipeline_id)
    assert rules == []


async def _create_business_rule_directly(tenant_id, pipeline_id, name):
    """Bypasses BusinessRules.create_rule() — it delegates to
    QualityRuleEngine.create_rule(), which validates rule_type against its
    OWN base 8 types (not_null/unique/...), never against
    BUSINESS_RULE_TYPES, so every real business rule_type
    (pipeline_success_rate, reconciliation, etc.) is unconditionally
    rejected as "Unknown rule_type". That's a real, separate bug — flagged
    in CLAUDE.md's Known-broken table, out of scope for this pass (which
    only fixes list_rules()'s dict/list bug). Using QualityRuleEngine
    directly with a valid base rule_type, manually tagged the same way
    BusinessRules.create_rule() would tag it if its own validation didn't
    block every call first — isolates the list_rules() test from that
    separate bug."""
    from modules.quality.rule_engine import QualityRuleEngine
    return await QualityRuleEngine(tenant_id).create_rule(
        pipeline_id=pipeline_id, name=name, rule_type="not_null", column_name="id",
        rule_config={"_business_rule": True},
    )


@pytest.mark.asyncio
async def test_list_rules_returns_only_business_rules_for_the_pipeline(client):
    token, tenant_id = await _register(client, "bizrules2")
    pipeline_id = await _make_pipeline(client, token)

    created = await _create_business_rule_directly(tenant_id, pipeline_id, "Success rate check")
    assert "error" not in created

    rules = await BusinessRules(tenant_id).list_rules(pipeline_id)
    assert len(rules) == 1
    assert rules[0]["name"] == "Success rate check"
    assert rules[0]["rule_config"]["_business_rule"] is True


@pytest.mark.asyncio
async def test_run_all_no_longer_crashes_via_list_rules(client):
    """run_all() calls list_rules() first — the same bug broke it too."""
    token, tenant_id = await _register(client, "bizrules3")
    pipeline_id = await _make_pipeline(client, token)

    await _create_business_rule_directly(tenant_id, pipeline_id, "Success rate check")

    result = await BusinessRules(tenant_id).run_all(pipeline_id)
    assert "error" not in result
    assert "results" in result
