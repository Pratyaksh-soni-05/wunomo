"""Wunomo Projects Phase 2: services/mentions.py's pure @mention parser
-- no DB, no LLM, just the text rule."""
from services.mentions import parse_mention


def test_leading_mention_is_parsed():
    name, rest = parse_mention("@Nova sync the warehouse source")
    assert name == "Nova"
    assert rest == "sync the warehouse source"


def test_mention_with_no_trailing_text():
    name, rest = parse_mention("@Nova")
    assert name == "Nova"
    assert rest == ""


def test_no_mention_returns_none_and_original_message():
    name, rest = parse_mention("sync the warehouse source")
    assert name is None
    assert rest == "sync the warehouse source"


def test_mention_not_at_the_start_is_not_recognized():
    """Slack-style: only a LEADING mention addresses someone. A mid-
    sentence @name is just text."""
    name, rest = parse_mention("can you loop in @Nova on this")
    assert name is None
    assert rest == "can you loop in @Nova on this"


def test_leading_whitespace_before_mention_is_tolerated():
    name, rest = parse_mention("   @Atlas check the pipeline")
    assert name == "Atlas"
    assert rest == "check the pipeline"


def test_multiline_message_after_mention():
    name, rest = parse_mention("@Nova here's the plan:\nstep one\nstep two")
    assert name == "Nova"
    assert rest == "here's the plan:\nstep one\nstep two"
