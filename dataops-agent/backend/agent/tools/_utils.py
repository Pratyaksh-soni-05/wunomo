import json

# Tool results become permanent entries in the agent's chat message history —
# unlike API responses, they're never paginated or discarded, so a single large
# payload (a full schema profile, a 100k-row transform result) inflates every
# subsequent LLM call in the conversation. Cap what enters history here; callers
# that need the full data (e.g. the REST API) should call the underlying
# module directly instead of going through the agent tool.
MAX_TOOL_RESULT_CHARS = 4000


def cap_tool_result(result, max_chars: int = MAX_TOOL_RESULT_CHARS):
    # An empty list/tuple (e.g. list_open_incidents with zero open incidents,
    # list_business_rules with none configured) becomes literal empty
    # ToolMessage content once LangChain builds the message -- Groq's chat
    # completions API rejects that outright ("'messages.N.content' :
    # minimum number of items is 1"), crashing POST /chat/ with an
    # unhandled 500. Every other empty/falsy shape (dict, None, "") already
    # serializes to a non-empty string ("{}", "null", '""') and is
    # unaffected; a non-empty list is also unaffected (Groq only rejects
    # zero-length content). Found live while verifying the YC demo's
    # investigation step against a tenant with a single incident that had
    # already been triaged (flips status to "investigating", so a second
    # list_open_incidents call legitimately returns an empty list).
    if isinstance(result, (list, tuple)) and len(result) == 0:
        return {"items": [], "count": 0}
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
