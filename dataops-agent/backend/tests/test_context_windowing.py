"""Wunomo Projects Phase 0, commit 6: window_and_summarize().

Covers the three shapes the function's own docstring/comments promise:
under-window is a no-op (with and without a prior summary already in
play), and over-window actually windows and summarizes, folding any
prior summary into the new one rather than re-summarizing from scratch.
"""
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

import agent.dataops_agent as dataops_agent_module
from agent.dataops_agent import CONTEXT_WINDOW_SIZE, window_and_summarize


def _alternating_history(n: int) -> list:
    messages = []
    for i in range(n):
        if i % 2 == 0:
            messages.append(HumanMessage(content=f"user turn {i}"))
        else:
            messages.append(AIMessage(content=f"assistant turn {i}"))
    return messages


@pytest.mark.asyncio
async def test_noop_when_history_fits_window_and_no_prior_summary(monkeypatch):
    invoke = AsyncMock()
    monkeypatch.setattr(dataops_agent_module, "invoke_llm", invoke)

    history = _alternating_history(CONTEXT_WINDOW_SIZE)
    result_history, new_summary = await window_and_summarize(
        history, tenant_id="t1", session_id="s1", prior_summary=None,
    )

    assert result_history == history
    assert new_summary is None
    invoke.assert_not_called()


@pytest.mark.asyncio
async def test_prior_summary_is_prepended_but_not_recomputed_under_window(monkeypatch):
    invoke = AsyncMock()
    monkeypatch.setattr(dataops_agent_module, "invoke_llm", invoke)

    history = _alternating_history(CONTEXT_WINDOW_SIZE - 2)
    result_history, new_summary = await window_and_summarize(
        history, tenant_id="t1", session_id="s1", prior_summary="Earlier: discussed pipeline P1.",
    )

    assert isinstance(result_history[0], SystemMessage)
    assert result_history[0].content == "Earlier: discussed pipeline P1."
    assert result_history[1:] == history
    assert new_summary is None
    invoke.assert_not_called()


@pytest.mark.asyncio
async def test_summarizes_and_windows_when_history_exceeds_window(monkeypatch):
    invoke = AsyncMock(return_value="Fresh summary of the whole conversation so far.")
    monkeypatch.setattr(dataops_agent_module, "invoke_llm", invoke)

    history = _alternating_history(CONTEXT_WINDOW_SIZE + 5)
    result_history, new_summary = await window_and_summarize(
        history, tenant_id="t1", session_id="s1", prior_summary=None,
    )

    assert new_summary == "Fresh summary of the whole conversation so far."
    assert isinstance(result_history[0], SystemMessage)
    assert result_history[0].content == new_summary
    assert result_history[1:] == history[-CONTEXT_WINDOW_SIZE:]
    invoke.assert_called_once()
    call_kwargs = invoke.call_args.kwargs
    assert call_kwargs["tenant_id"] == "t1"
    assert call_kwargs["session_id"] == "s1"
    assert call_kwargs["request_type"] == "chat_history_summary"
    prompt_text = invoke.call_args.args[0][0].content
    assert "user turn 0" in prompt_text
    assert "assistant turn 1" in prompt_text
    last_evicted = history[-CONTEXT_WINDOW_SIZE - 1].content
    assert last_evicted in prompt_text
    first_windowed = history[-CONTEXT_WINDOW_SIZE].content
    assert first_windowed not in prompt_text


@pytest.mark.asyncio
async def test_folds_prior_summary_into_the_new_one_instead_of_starting_over(monkeypatch):
    invoke = AsyncMock(return_value="Updated summary covering everything.")
    monkeypatch.setattr(dataops_agent_module, "invoke_llm", invoke)

    history = _alternating_history(CONTEXT_WINDOW_SIZE + 3)
    result_history, new_summary = await window_and_summarize(
        history, tenant_id="t1", session_id="s1",
        prior_summary="Earlier: discussed pipeline P1 failing on source S2.",
    )

    prompt_text = invoke.call_args.args[0][0].content
    assert "Earlier: discussed pipeline P1 failing on source S2." in prompt_text
    assert "Existing summary so far" in prompt_text
    assert new_summary == "Updated summary covering everything."
    assert result_history[1:] == history[-CONTEXT_WINDOW_SIZE:]
