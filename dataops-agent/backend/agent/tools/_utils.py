import json

# Tool results become permanent entries in the agent's chat message history —
# unlike API responses, they're never paginated or discarded, so a single large
# payload (a full schema profile, a 100k-row transform result) inflates every
# subsequent LLM call in the conversation. Cap what enters history here; callers
# that need the full data (e.g. the REST API) should call the underlying
# module directly instead of going through the agent tool.
MAX_TOOL_RESULT_CHARS = 4000


def cap_tool_result(result, max_chars: int = MAX_TOOL_RESULT_CHARS):
    text = json.dumps(result, default=str)
    if len(text) <= max_chars:
        return result
    return {
        "truncated": True,
        "original_size_chars": len(text),
        "preview": text[:max_chars],
        "note": (
            f"Result truncated to {max_chars} chars (original {len(text)} chars) "
            "to keep conversation history bounded. Use a more specific query "
            "(e.g. a single table/column) to see full detail."
        ),
    }
