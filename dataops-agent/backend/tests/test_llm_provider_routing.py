"""The LLM fallback had never worked, and nothing would have told anyone.

`_build_llm()` picked a provider by substring-matching the model name:
"llama"/"mixtral"/"gemma" meant Groq, anything else meant Google. Meanwhile
FALLBACK_LLM_MODEL was `llama-3.3-70b-versatile`, which **is not present in
this Groq account** — measured against the live catalogue, not assumed. So the
fallback 404'd, and it only ever did so at the one moment the primary was
already failing, which is precisely when nobody is reading logs carefully.

Worse, the substring rule was wrong for every chat model the account actually
has: `openai/gpt-oss-120b`, `qwen/qwen3.8-27b`, `groq/compound`, `allam-2-7b`
contain none of those three strings, so configuring any of them would have sent
a Groq model name to Google.

The fix routes on the provider DECLARED in settings — `PRIMARY_LLM_PROVIDER`
already existed and was read by nothing — and validates both configured models
against their provider's live catalogue.
"""

import pytest

from config import settings
from services import llm_service
from services.llm_service import (
    _live_models,
    _provider_for_model,
    get_fallback_llm,
    get_primary_llm,
    validate_llm_config,
)


def _catalogue(provider: str) -> set[str]:
    """Live model ids, or skip. Listing models costs no generation quota with
    either provider; a network failure is a skip, a missing model is a
    failure — the distinction matters, because collapsing them is how a
    misconfiguration hides behind an outage."""
    try:
        return _live_models(provider)
    except Exception as exc:  # pragma: no cover - network dependent
        pytest.skip(f"{provider} model catalogue unreachable: {exc}")


def test_configured_models_exist_at_their_providers():
    """The check that would have caught the original bug on day one."""
    for label, provider, model in (
        ("PRIMARY", settings.PRIMARY_LLM_PROVIDER, settings.PRIMARY_LLM_MODEL),
        ("FALLBACK", settings.FALLBACK_LLM_PROVIDER, settings.FALLBACK_LLM_MODEL),
    ):
        available = _catalogue(provider)
        assert model in available, (
            f"{label} model {model!r} is not available to the configured "
            f"{provider} credentials. Available: {sorted(available)}"
        )


def test_validate_llm_config_reports_no_problems():
    _catalogue(settings.PRIMARY_LLM_PROVIDER)  # skip early if offline
    assert validate_llm_config() == []


def test_validate_llm_config_catches_a_model_the_provider_does_not_have(monkeypatch):
    """Proves the validator can go red — a check that cannot fail is not a
    check. Uses the exact value that was really configured."""
    _catalogue("groq")
    monkeypatch.setattr(settings, "FALLBACK_LLM_MODEL", "llama-3.3-70b-versatile")
    problems = validate_llm_config()
    assert any("FALLBACK" in p and "llama-3.3-70b-versatile" in p for p in problems), problems


def test_every_override_option_exists_at_its_provider():
    """The Settings -> AI Model picker offers exactly SUPPORTED_MODEL_OVERRIDES.
    On 2026-09-16 that list still carried llama-3.3-70b-versatile, six days
    after the FALLBACK fix proved the account does not serve it; a tenant who
    chose it got a 404 on every turn and a silent fallback (measured live).
    Same check as the PRIMARY/FALLBACK one, same reason."""
    from services.llm_service import SUPPORTED_MODEL_OVERRIDES, _provider_for_model
    assert SUPPORTED_MODEL_OVERRIDES, "an empty override list disables the feature silently"
    for model in SUPPORTED_MODEL_OVERRIDES:
        provider = _provider_for_model(model)
        available = _catalogue(provider)
        assert model in available, (
            f"override option {model!r} is not available to the configured "
            f"{provider} credentials. Available: {sorted(available)}")


def test_validate_llm_config_catches_a_stale_override_entry(monkeypatch):
    """The exact value that was really on offer, put back, must be reported
    under its own label so the boot log says which option is broken."""
    from services import llm_service
    _catalogue("groq")
    monkeypatch.setattr(llm_service, "SUPPORTED_MODEL_OVERRIDES",
                        ["gemini-3.5-flash", "llama-3.3-70b-versatile"])
    problems = validate_llm_config()
    assert any("OVERRIDE" in p and "llama-3.3-70b-versatile" in p for p in problems), problems
    assert not any("gemini-3.5-flash" in p for p in problems), problems


def test_stale_override_is_no_longer_on_offer():
    from services.llm_service import SUPPORTED_MODEL_OVERRIDES, supported_model_overrides
    assert "llama-3.3-70b-versatile" not in SUPPORTED_MODEL_OVERRIDES
    assert [m["value"] for m in supported_model_overrides()] == SUPPORTED_MODEL_OVERRIDES


# ── Routing ──────────────────────────────────────────────────────────────────

def test_primary_and_fallback_route_to_different_real_providers():
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_groq import ChatGroq

    primary, fallback = get_primary_llm(), get_fallback_llm()
    assert isinstance(primary, ChatGoogleGenerativeAI)
    assert isinstance(fallback, ChatGroq)
    # Hard Rule 2, restated as an assertion: the fallback must not silently
    # become a second Google client.
    assert not isinstance(fallback, ChatGoogleGenerativeAI)


def test_declared_provider_beats_name_inference():
    """The regression. A Groq model whose name contains none of
    llama/mixtral/gemma must still route to Groq."""
    from langchain_groq import ChatGroq

    assert "llama" not in settings.FALLBACK_LLM_MODEL
    assert "mixtral" not in settings.FALLBACK_LLM_MODEL
    assert "gemma" not in settings.FALLBACK_LLM_MODEL
    assert isinstance(get_fallback_llm(), ChatGroq)
    assert _provider_for_model(settings.FALLBACK_LLM_MODEL) == "groq"
    assert _provider_for_model(settings.PRIMARY_LLM_MODEL) == "gemini"


@pytest.mark.parametrize("model,expected", [
    # Real ids from this account's catalogue, none matching the old substrings.
    ("openai/gpt-oss-120b", "groq"),
    ("openai/gpt-oss-20b", "groq"),
    ("qwen/qwen3.8-27b", "groq"),
    ("groq/compound", "groq"),
    ("allam-2-7b", "groq"),
    ("meta-llama/llama-prompt-guard-2-86m", "groq"),
    # Still correct for the shapes the old rule did handle.
    ("llama-3.3-70b-versatile", "groq"),
    ("mixtral-8x7b-32768", "groq"),
    ("gemma2-9b-it", "groq"),
    # Google models keep going to Google.
    ("gemini-3.5-flash", "gemini"),
    ("gemini-2.0-flash", "gemini"),
])
def test_provider_inference_for_per_tenant_overrides(model, expected, monkeypatch):
    """Inference only applies to a tenant's `ai_model_override`, which supplies
    a bare model name and no provider. Configured models never reach it."""
    monkeypatch.setattr(settings, "PRIMARY_LLM_MODEL", "__unset__")
    monkeypatch.setattr(settings, "FALLBACK_LLM_MODEL", "__unset__")
    assert _provider_for_model(model) == expected


def test_build_llm_honours_an_explicit_provider_over_the_name():
    from langchain_groq import ChatGroq

    # A deliberately Google-looking name, declared as Groq: the declaration wins.
    built = llm_service._build_llm("gemini-shaped-name", 0.0, provider="groq")
    assert isinstance(built, ChatGroq)
