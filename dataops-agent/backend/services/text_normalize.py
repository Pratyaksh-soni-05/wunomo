"""Normalize LLM-generated text before matching it against identifiers or
PII patterns.

Found live 2026-09-29: Gemini has been observed emitting U+2011 (NON-BREAKING
HYPHEN) in place of U+002D (ASCII HYPHEN-MINUS) inside UUID-shaped text.
prompt_guard.redact_identifiers() matches on a literal `str.replace(value,
...)`, and pii_classifier's SSN/card detectors match on a regex anchored to
`-`, so either fails to match a value whose hyphens the model rendered with
a different code point -- the identifier or PII then passes through
un-redacted, indistinguishable in the output from a value that was never
flagged at all.

NFKC normalization alone does NOT fix this, verified before writing this
file, not assumed: U+2011 normalizes under NFKC to U+2010, which is still
not ASCII hyphen. Neither do en dash (U+2013), em dash (U+2014), or figure
dash (U+2012) -- none of Unicode's "General Punctuation" dashes are defined
as compatibility-equivalent to ASCII hyphen-minus, only the fullwidth/
small-form variants (U+FF0D, U+FE63) are. So this runs NFKC first (it still
earns its place for OTHER compatibility tricks -- fullwidth digits,
ligatures, etc.) and then an explicit translation table for the
dash/hyphen-lookalike family NFKC does not cover.

Single shared module, imported by both prompt_guard.py and pii_classifier.py,
rather than a second hand-maintained pattern list in either -- the two
files' regexes/replace calls disagree on plenty else, but should never
disagree on what counts as a hyphen.
"""

import unicodedata

# Every code point in this table renders, in most fonts, close enough to
# ASCII hyphen-minus (U+002D) that a model choosing one over the other reads
# as a formatting accident, not a meaningful distinction -- exactly the
# condition under which a defender must fold them together. U+00AD (SOFT
# HYPHEN) is included too: it is usually invisible, but an invisible
# character embedded inside a UUID/SSN/card number is a distinct variant of
# the same bypass (the literal-match/regex still doesn't line up), not
# something to render literally here.
_DASH_LOOKALIKES = str.maketrans({
    "‐": "-",  # HYPHEN
    "‑": "-",  # NON-BREAKING HYPHEN (the reported case)
    "‒": "-",  # FIGURE DASH
    "–": "-",  # EN DASH
    "—": "-",  # EM DASH
    "―": "-",  # HORIZONTAL BAR
    "−": "-",  # MINUS SIGN
    "­": "-",  # SOFT HYPHEN
    "﹣": "-",  # SMALL HYPHEN-MINUS (NFKC already covers this one)
    "－": "-",  # FULLWIDTH HYPHEN-MINUS (NFKC already covers this one)
})


def normalize_for_matching(text: str) -> str:
    """NFKC, then fold dash/hyphen lookalikes to ASCII '-'.

    Applied to the WHOLE input, not just substrings that happen to match a
    known identifier or PII pattern -- there is no way to know in advance
    which substrings those are without first normalizing. The visible
    side effect: a stray em dash or non-breaking hyphen anywhere in ordinary
    prose (not just inside an identifier) also becomes a plain ASCII
    hyphen. Accepted deliberately -- a minor, cosmetic typography change is
    a better trade than a silent redaction bypass.
    """
    if not text:
        return text
    return unicodedata.normalize("NFKC", text).translate(_DASH_LOOKALIKES)
