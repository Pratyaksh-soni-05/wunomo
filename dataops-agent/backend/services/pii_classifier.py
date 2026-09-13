"""PII / PHI column classification (Item #10).

    WHAT THIS DECIDES AND WHERE THE ANSWER LIVES
    --------------------------------------------
    Every column in a profiled DataSource gets a `sensitivity` level stored
    beside its other metadata inside `schema_snapshot`:

        {"column_name": "email", "data_type": "text", ...,
         "sensitivity": "pii",            # none | pii | phi
         "sensitivity_source": "auto",    # auto | manual
         "sensitivity_reason": "name token 'email'"}

    Stored IN the snapshot rather than in a side table, because every
    consumer already iterates snapshot["<table>"]["columns"], and a separate
    table would need a join at all ten of the call sites Task 1 found. The
    level is a plain string, deliberately, so Item #11 can add levels
    (e.g. a residency class) without a migration.

    `manual` classifications are carried forward when the profiler rewrites
    the snapshot -- see `merge_manual_overrides` -- otherwise the next
    profile run would silently revert an engineer's correction.

HOW DETECTION WORKS, AND WHERE THE LINE IS DRAWN

Two signals, either sufficient:

  1. NAME. The column name is split into tokens (snake, kebab, space and
     camelCase boundaries), and each token is looked up in a vocabulary.
     Tokens, not substrings: "id" must not match because "ssn" shares
     letters with nothing, "session_id" must not match "ssn", and
     "description" must not match "ssn" or "ip". Substring matching is
     how a feature like this becomes annoying enough to be switched off.

     Two de-boosts stop the obvious false positives that token matching
     alone would still produce:
       - boolean columns are never name-flagged: `email_verified`,
         `has_phone`, `address_confirmed` are facts ABOUT a field, not
         the field.
       - a trailing structural token (id, count, verified, flag, hash,
         type, format, length, total, exists) means the same thing:
         `address_id` is a foreign key, `phone_count` is an integer.

  2. VALUES. A small sample of non-null values (the profiler passes what
     it already loaded; nothing extra is fetched from a database) is run
     against strict, anchored regexes: SSN, email, phone, IPv4, and
     payment-card numbers with a Luhn check so a 16-digit order number
     does not flag. A column is flagged only if at least 60% of the
     sampled values match -- a free-text notes column where one row
     happens to contain an email address is not an email column.
     Sample values are used and DISCARDED; they are never written into
     the snapshot, because a snapshot holding sample PII would itself be
     the leak this feature exists to prevent.

PHI beats PII: a column whose name says `diagnosis` is phi even if its
values look like nothing in particular. There is no value regex for PHI --
medical content has no reliable surface form -- so PHI detection is
name-only and the vocabulary errs wide.

WHY OVER-FLAGGING IS THE RIGHT BIAS, AND WHY NOT INFINITELY

A missed PII column ships real personal data into an LLM prompt or a
preview response. A wrongly flagged column shows "***" where a value
should be, and an engineer with `sources.classify` fixes it in one call
and the correction sticks. Those costs are not symmetric, so ambiguous
names (`name`, `address`, `dob`) are flagged. But every false positive is
one more "***" a user has to explain, and enough of those and someone
switches the feature off wholesale -- at which point it protects nothing.
The de-boosts and the 60% value threshold are where that balance sits.
"""

import re
from typing import Iterable, Optional

import structlog

log = structlog.get_logger()

LEVELS = ("none", "pii", "phi")
VALUE_SAMPLE_SIZE = 50
VALUE_MATCH_THRESHOLD = 0.60

# ── Name vocabulary ──────────────────────────────────────────────────────────
# Single tokens, and a few two-token phrases matched against the joined token
# string so "date of birth" / "date_of_birth" / "dateOfBirth" all resolve.

PII_TOKENS = frozenset({
    # identifiers
    "ssn", "social", "passport", "license", "licence", "nationalid", "tin", "ein",
    "taxid", "nino", "aadhaar", "aadhar", "pan",
    # contact
    "email", "e-mail", "mail", "phone", "mobile", "cell", "telephone", "tel", "fax",
    # names
    "firstname", "lastname", "surname", "givenname", "middlename", "maidenname",
    "fullname", "nickname",
    # birth / age
    "dob", "birthdate", "birthday", "birth", "age",
    # location
    "address", "street", "zip", "zipcode", "postcode", "postal", "city",
    "latitude", "longitude", "lat", "lng", "lon",
    # financial
    "creditcard", "cardnumber", "ccnumber", "cvv", "cvc", "iban", "swift",
    "accountnumber", "routing", "sortcode", "salary", "income",
    # digital identity
    "ip", "ipaddress", "mac", "macaddress", "username", "userid", "login",
    "password", "passwd", "secret", "token", "apikey",
    # protected characteristics (PII under most regimes, sensitive under GDPR)
    "gender", "sex", "race", "ethnicity", "religion", "nationality",
    "citizenship", "disability", "orientation",
})

# "name" on its own is a person's name often enough to flag, but as a suffix
# it is usually a label for a thing (product_name, table_name, pipeline_name)
# and withholding those from the model breaks the transform it was asked to
# write. So <qualifier>_name is PII only when the qualifier is a person.
NAME_QUALIFIERS = frozenset({
    "customer", "user", "patient", "person", "employee", "staff", "contact",
    "client", "member", "subscriber", "applicant", "owner", "holder", "driver",
    "passenger", "guest", "student", "parent", "guardian", "spouse", "child",
    "beneficiary", "payee", "payer", "recipient", "sender", "author", "buyer",
    "seller", "agent", "rep", "manager", "first", "last", "full", "given",
    "middle", "maiden", "legal", "display", "real", "family", "sur", "nick",
})

PII_PHRASES = (
    "date of birth", "social security", "national id", "tax id", "credit card",
    "card number", "account number", "routing number", "sort code",
    "ip address", "mac address", "first name", "last name", "full name",
    "phone number", "mobile number", "postal code", "zip code", "date_of_birth",
)

PHI_TOKENS = frozenset({
    "diagnosis", "diagnoses", "icd", "icd9", "icd10", "cpt", "mrn", "patient",
    "medical", "medication", "medications", "prescription", "rx", "drug", "dose",
    "allergy", "allergies", "bloodtype", "treatment",
    "symptom", "symptoms", "hiv", "clinical", "labresult", "insurance",
    "memberid", "npi", "physician", "doctor", "hospital",
    "immunization", "vaccine", "pregnancy", "mentalhealth", "therapy",
    "disorder", "genetic", "biometric", "fingerprint", "retina",
})

# Words that are PHI in a clinical schema but ordinary elsewhere --
# "condition" (filter condition), "procedure" (stored procedure), "lab"
# (research lab), "provider" (llm_provider, payment_provider) -- only count
# when qualified.
PHI_PHRASES = (
    "medical record", "health record", "blood type", "lab result", "lab test",
    "insurance id", "member id", "mental health", "medical condition",
    "health condition", "medical procedure", "surgical procedure",
    "healthcare provider", "health care provider", "insurance provider",
    "care provider", "provider npi", "procedure code",
)

# A trailing token that turns a sensitive-looking name into something
# structural: address_id is a key, phone_count is an integer, email_verified
# is a fact about an email rather than an email.
STRUCTURAL_SUFFIXES = frozenset({
    "id", "ids", "key", "fk", "count", "cnt", "num", "number", "total", "sum",
    "verified", "confirmed", "valid", "exists", "flag", "hash", "hashed",
    "type", "format", "kind", "len", "length", "at", "date", "ts", "timestamp",
    "enabled", "disabled", "status", "code",
})
# ...except these, where the suffix IS the sensitive thing.
SUFFIX_EXCEPTIONS = {
    ("card", "number"), ("account", "number"), ("phone", "number"),
    ("mobile", "number"), ("routing", "number"), ("passport", "number"),
    ("license", "number"), ("member", "id"), ("national", "id"), ("tax", "id"),
    ("birth", "date"), ("zip", "code"), ("postal", "code"), ("sort", "code"),
    ("fax", "number"), ("telephone", "number"), ("cell", "number"),
    ("contact", "number"), ("passport", "id"), ("ssn", "number"),
    # clinical code sets: the code IS the diagnosis / procedure
    ("icd", "code"), ("icd9", "code"), ("icd10", "code"), ("cpt", "code"),
    ("diagnosis", "code"), ("procedure", "code"), ("drg", "code"),
    # credentials: structural suffix, but the value is still a secret
    ("api", "key"), ("secret", "key"), ("private", "key"),
    ("password", "hash"), ("passwd", "hash"), ("password", "hashed"),
}

BOOLEAN_TYPES = ("bool", "boolean", "bit", "tinyint(1)")

# ── Value patterns ───────────────────────────────────────────────────────────

_SSN = re.compile(r"^(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}$")
_EMAIL = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_PHONE = re.compile(r"^\+?[\d\s().\-]{9,20}$")
_IPV4 = re.compile(r"^(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)$")
_CARD = re.compile(r"^(?:\d[ \-]?){13,19}$")


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def _is_phone(v: str) -> bool:
    if not _PHONE.match(v):
        return False
    digits = re.sub(r"\D", "", v)
    return 10 <= len(digits) <= 15


def _is_card(v: str) -> bool:
    if not _CARD.match(v):
        return False
    digits = re.sub(r"\D", "", v)
    return 13 <= len(digits) <= 19 and _luhn(digits)


VALUE_DETECTORS = (
    ("ssn", lambda v: bool(_SSN.match(v))),
    ("email", lambda v: bool(_EMAIL.match(v))),
    ("payment card", _is_card),
    ("ipv4", lambda v: bool(_IPV4.match(v))),
    ("phone", _is_phone),
)


# ── Name analysis ────────────────────────────────────────────────────────────

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_SPLIT = re.compile(r"[\s_\-./]+")


def tokenize(name: str) -> list[str]:
    """'dateOfBirth' -> ['date','of','birth']; 'customer_ssn' -> ['customer','ssn']."""
    if not name:
        return []
    spaced = _CAMEL.sub(" ", str(name))
    return [t for t in _SPLIT.split(spaced.lower()) if t]


def _name_level(name: str, data_type: Optional[str]) -> tuple[str, Optional[str]]:
    tokens = tokenize(name)
    if not tokens:
        return "none", None
    joined = " ".join(tokens)
    compact = "".join(tokens)

    # Boolean columns describe a field; they are not the field.
    if data_type and str(data_type).lower().startswith(BOOLEAN_TYPES):
        return "none", None

    # Phrases first, and BEFORE the suffix de-boost: "medical record number"
    # ends in a structural token but IS the MRN, and "phone number" is the
    # phone. A multi-word phrase is a strong enough signal to override the
    # suffix heuristic, which exists for single ambiguous tokens.
    for phrase in PHI_PHRASES:
        if phrase in joined:
            return "phi", f"name phrase '{phrase}'"
    for phrase in PII_PHRASES:
        if phrase in joined:
            return "pii", f"name phrase '{phrase}'"

    # Structural suffix de-boost, unless the pair itself is a known PII name.
    if len(tokens) >= 2 and tokens[-1] in STRUCTURAL_SUFFIXES \
            and (tokens[-2], tokens[-1]) not in SUFFIX_EXCEPTIONS:
        return "none", None

    for tok in tokens:
        if tok in PHI_TOKENS:
            return "phi", f"name token '{tok}'"
    if compact in PHI_TOKENS:
        return "phi", f"name '{compact}'"

    for tok in tokens:
        if tok in PII_TOKENS:
            return "pii", f"name token '{tok}'"
    if compact in PII_TOKENS:
        return "pii", f"name '{compact}'"

    if "name" in tokens:
        if tokens == ["name"]:
            return "pii", "bare column 'name'"
        i = tokens.index("name")
        if i > 0 and tokens[i - 1] in NAME_QUALIFIERS:
            return "pii", f"name of a person ('{tokens[i - 1]} name')"
    return "none", None


def _value_level(values: Iterable) -> tuple[str, Optional[str]]:
    sample = [str(v).strip() for v in values if v is not None and str(v).strip() != ""]
    sample = sample[:VALUE_SAMPLE_SIZE]
    if len(sample) < 3:
        # Too little to judge; one or two coincidental matches would flag a
        # column on almost no evidence.
        return "none", None
    for label, detect in VALUE_DETECTORS:
        hits = sum(1 for v in sample if detect(v))
        if hits / len(sample) >= VALUE_MATCH_THRESHOLD:
            return "pii", f"{hits}/{len(sample)} sampled values look like {label}"
    return "none", None


def classify_column(name: str, data_type: Optional[str] = None,
                    sample_values: Optional[Iterable] = None) -> tuple[str, str]:
    """Returns (level, reason). Name first; values only if the name is clean."""
    level, reason = _name_level(name, data_type)
    if level != "none":
        return level, reason
    if sample_values is not None:
        level, reason = _value_level(sample_values)
        if level != "none":
            return level, reason
    return "none", ""


# ── Snapshot integration ─────────────────────────────────────────────────────

def classify_snapshot(snapshot: dict, samples: Optional[dict] = None) -> dict:
    """Annotate every column in a SchemaProfiler snapshot in place.

    `samples`, when given, is {table: {column: [values...]}} from data the
    profiler already had in hand. It is consumed here and not stored.
    """
    for table, info in (snapshot or {}).items():
        cols = info.get("columns") if isinstance(info, dict) else None
        if not cols:
            continue
        tbl_samples = (samples or {}).get(table, {})
        for col in cols:
            if col.get("sensitivity_source") == "manual":
                continue  # an engineer's decision outranks the detector
            name = col.get("column_name")
            level, reason = classify_column(name, col.get("data_type"),
                                            tbl_samples.get(name))
            col["sensitivity"] = level
            col["sensitivity_source"] = "auto"
            col["sensitivity_reason"] = reason
    return snapshot


def merge_manual_overrides(old: Optional[dict], new: dict) -> dict:
    """Carry `manual` classifications from the previous snapshot into a
    freshly profiled one, matched by (table, column_name). Without this every
    re-profile would revert an engineer's correction to the detector's
    guess, which is the fastest way to teach people the override is
    pointless."""
    if not old:
        return new
    manual = {}
    for table, info in old.items():
        for col in (info.get("columns") or []) if isinstance(info, dict) else []:
            if col.get("sensitivity_source") == "manual":
                manual[(table, col.get("column_name"))] = col
    if not manual:
        return new
    for table, info in new.items():
        for col in (info.get("columns") or []) if isinstance(info, dict) else []:
            prior = manual.get((table, col.get("column_name")))
            if prior:
                col["sensitivity"] = prior.get("sensitivity", "none")
                col["sensitivity_source"] = "manual"
                col["sensitivity_reason"] = prior.get("sensitivity_reason", "manual override")
    return new


def sensitive_columns(snapshot: Optional[dict], table: Optional[str] = None) -> dict:
    """{table: {column_name: level}} for every column at pii or phi.

    The single query every enforcement point uses, and the hook Item #11's
    pre-LLM filter should build on rather than re-deriving.
    """
    out: dict = {}
    for tbl, info in (snapshot or {}).items():
        if table is not None and tbl != table:
            continue
        cols = info.get("columns") if isinstance(info, dict) else None
        for col in cols or []:
            lvl = col.get("sensitivity", "none")
            if lvl in ("pii", "phi"):
                out.setdefault(tbl, {})[col.get("column_name")] = lvl
    return out


# ── Enforcement helpers ──────────────────────────────────────────────────────

MASK = "***"


def mask_rows(rows: list, flagged: Iterable[str], strip: bool = False) -> list:
    """Mask (or remove) flagged columns in a list of row dicts.

    strip=False replaces values with MASK and keeps the key -- for responses
    a person reads, where knowing the column exists is useful and the value
    is not. strip=True removes the key entirely -- for anything bound for an
    LLM, where even the column NAME must not travel.
    """
    flagged = set(flagged)
    if not flagged or not rows:
        return rows
    out = []
    for r in rows:
        if not isinstance(r, dict):
            out.append(r)
            continue
        if strip:
            out.append({k: v for k, v in r.items() if k not in flagged})
        else:
            out.append({k: (MASK if k in flagged else v) for k, v in r.items()})
    return out


def filter_columns(columns: list, flagged: Iterable[str]) -> list:
    flagged = set(flagged)
    return [c for c in columns if c not in flagged]


def flagged_for_table(snapshot: Optional[dict], table: Optional[str]) -> set[str]:
    """Column names to enforce for a result drawn from `table`.

    If the snapshot has an entry for that table, use it. If not -- the
    caller passed a name the profiler never saw, or the source is a file
    whose only table is "main" while the caller said something else -- fall
    back to the union of every sensitive column across the whole snapshot.
    A column called `email` is sensitive whichever table it came from, and
    guessing wrong in the permissive direction is the failure this feature
    exists to prevent.
    """
    by_table = sensitive_columns(snapshot)
    if table in by_table:
        return set(by_table[table])
    return {c for cols in by_table.values() for c in cols}


async def enforce_for_source(tenant_id: str, source_id: Optional[str], result: dict,
                             strip: bool = False) -> dict:
    """enforce_on_result() for callers that hold a source_id, not a snapshot.

    Used by the SQL/Pandas transformation endpoints and agent tools, whose
    results come out of SqlRunner/PythonRunner (Item #5, not modified here)
    and whose column provenance is unknown -- a query may join anything -- so
    `table=None` deliberately selects the union of every sensitive column in
    the source. Tenant-scoped: a source_id from another tenant yields no
    snapshot and therefore no masking, which is the same outcome as the
    runner refusing it in the first place.
    """
    if not source_id or not isinstance(result, dict) or "error" in result:
        return result
    from sqlalchemy import select
    from models.all_models import DataSource
    from services.tenant_context import tenant_session
    # tenant_session, not a bare AsyncSessionLocal: under RLS a session with
    # no tenant context reads zero rows, so the snapshot would come back None
    # and nothing would be masked -- silently failing OPEN. The tool-path
    # test (called outside the HTTP middleware) is what exposed this.
    async with tenant_session(tenant_id) as db:
        snapshot = (await db.execute(
            select(DataSource.schema_snapshot).where(
                DataSource.id == source_id, DataSource.tenant_id == tenant_id)
        )).scalar_one_or_none()
    if not snapshot:
        # Registered but never profiled (snapshot == {}), or not visible to
        # this tenant (None). No stored classification is not a reason to
        # release everything: classify the result's own columns on the spot
        # from their names and the values in hand, exactly as the ingest
        # preview does. Nothing is persisted.
        log.info("pii_classifier.unprofiled_source", tenant_id=tenant_id, source_id=source_id)
        return enforce_on_unprofiled_result(result, strip=strip)
    return enforce_on_result(result, snapshot, None, strip=strip)


def enforce_on_unprofiled_result(result: dict, strip: bool = False) -> dict:
    rows = result.get("rows") or []
    columns = list(result.get("columns") or (rows[0].keys() if rows and isinstance(rows[0], dict) else []))
    flagged = set()
    for c in columns:
        values = [r.get(c) for r in rows[:VALUE_SAMPLE_SIZE] if isinstance(r, dict)]
        level, _ = classify_column(c, None, values)
        if level in ("pii", "phi"):
            flagged.add(c)
    if not flagged:
        return result
    synthetic = {"_": {"columns": [{"column_name": c, "sensitivity": "pii"} for c in flagged]}}
    return enforce_on_result(result, synthetic, None, strip=strip)


def classify_and_mask_frame_preview(df, preview_rows: list) -> tuple[list, list]:
    """For ingest-time previews, where no snapshot exists yet: classify the
    frame's columns on the spot (name + the frame's own values) and mask the
    preview rows. Returns (masked_rows, flagged_column_names)."""
    flagged = []
    for c in df.columns:
        level, _ = classify_column(c, str(df[c].dtype), df[c].dropna().head(VALUE_SAMPLE_SIZE).tolist())
        if level in ("pii", "phi"):
            flagged.append(c)
    return mask_rows(preview_rows, flagged), flagged


def enforce_on_result(result: dict, snapshot: Optional[dict], table: Optional[str],
                      strip: bool = False) -> dict:
    """Apply masking (or stripping) to a {"columns": [...], "rows": [...]}
    result dict in place and return it. The shape every preview, SQL and
    Pandas result in this codebase already uses, so one helper covers all
    of them. Adds `masked_columns` when masking so a person can see what was
    withheld; adds nothing when stripping, because the LLM must not learn
    the names either.
    """
    if not isinstance(result, dict) or "error" in result:
        return result
    flagged = flagged_for_table(snapshot, table)
    if not flagged:
        return result
    if "rows" in result:
        result["rows"] = mask_rows(result["rows"], flagged, strip=strip)
    if strip:
        if "columns" in result:
            result["columns"] = filter_columns(result["columns"], flagged)
        # Column-keyed side dicts (dtypes, null_counts, null_pct...) name the
        # column just as well as `columns` does. The request-spy test found
        # `dtypes` carrying the stripped names out through the file
        # connector's preview; treat every dict keyed by column name alike.
        for key, val in list(result.items()):
            if key != "rows" and isinstance(val, dict) and flagged & set(val):
                result[key] = {k: v for k, v in val.items() if k not in flagged}
    else:
        present = [c for c in (result.get("columns") or []) if c in flagged]
        if present:
            result["masked_columns"] = present
    return result