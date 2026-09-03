"""Wunomo Projects Phase 2: @mention parsing.

Pure text parsing, no DB access -- kept separate from the DB-backed
resolution (services/channel_routing.py, which checks whether a parsed
name actually corresponds to a real channel member) so the parsing rule
itself is trivially unit-testable without a database.
"""
import re

_MENTION_PATTERN = re.compile(r"^\s*@(\S+)\s*(.*)$", re.DOTALL)


def parse_mention(message: str) -> tuple[str | None, str]:
    """Recognizes a mention only at the very start of the message
    (Slack-style): "@Nova sync the source" mentions Nova; "sync it, cc
    @Nova" does not. Exactly one mention per message for v1, matching
    "the tagged agent responds, nobody else" -- a message can't address
    two agents at once. Returns (mentioned_name_or_None,
    remaining_message_text); remaining text is the original message,
    unchanged, when there's no mention."""
    m = _MENTION_PATTERN.match(message)
    if m is None:
        return None, message
    return m.group(1), m.group(2).strip()
