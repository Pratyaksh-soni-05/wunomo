"""
Symmetric encryption for data-source credentials at rest.

`DataSource.connection_config` holds host/port/username/**password** for every
tenant-registered Postgres/MySQL source. Until this module existed it was written
to Postgres as plaintext JSON, meaning a database dump, a stolen backup, or a
read-only replica leaked every tenant's warehouse credentials in the clear.

    KEY MANAGEMENT — READ THIS BEFORE DEPLOYING
    -------------------------------------------
    The key lives in the CREDENTIAL_ENCRYPTION_KEY environment variable and must
    NEVER be committed to version control, pasted into a ticket, or checked into
    `.env` files that are themselves committed. Losing it makes every stored
    credential permanently unrecoverable — there is no recovery path, tenants
    must re-enter their connection details. Rotating it requires decrypting with
    the old key and re-encrypting with the new one (see
    `scripts/encrypt_existing_credentials.py`, which is the shape such a
    rotation script would take).

    Generate one with:
        python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Fernet (AES-128-CBC + HMAC-SHA256, timestamped) is used rather than raw AES so
that authentication and IV handling are not hand-rolled here.

In `APP_ENV=test` a deterministic, well-known development key is used when the
env var is unset, so the suite runs without external setup. It is deliberately
*deterministic* rather than randomly generated per process: a random key would
make rows written by one test process undecryptable by the next, and this
project's tests share one real database across runs (see GOTCHAS.md). Every
other environment fails loudly at startup instead — a silently-generated
throwaway key would "work" right up until a restart orphaned every row it wrote.
"""

from functools import lru_cache
import json

from cryptography.fernet import Fernet, InvalidToken

from config import settings


# Deterministic, intentionally-public key used ONLY when APP_ENV=test and no real
# key is configured. Never used in development/staging/production — those raise.
_TEST_FALLBACK_KEY = "dGVzdC1vbmx5LWtleS1ub3QtZm9yLXJlYWwtdXNlLDEyMzQ1Ng=="


class EncryptionKeyMissingError(RuntimeError):
    """Raised when CREDENTIAL_ENCRYPTION_KEY is unset outside of tests."""


@lru_cache()
def _fernet() -> Fernet:
    key = (settings.CREDENTIAL_ENCRYPTION_KEY or "").strip()

    if not key:
        if settings.APP_ENV == "test":
            key = _TEST_FALLBACK_KEY
        else:
            raise EncryptionKeyMissingError(
                "CREDENTIAL_ENCRYPTION_KEY is not set. Data-source credentials "
                "cannot be encrypted or decrypted without it, and generating a "
                "throwaway key here would silently orphan every credential "
                "already in the database on the next restart. Generate one with:\n"
                '  python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"\n'
                "then set it in dataops-agent/.env (the file Docker actually "
                "reads) and recreate the backend:\n"
                "  docker compose up -d --force-recreate backend"
            )

    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError) as exc:
        raise EncryptionKeyMissingError(
            f"CREDENTIAL_ENCRYPTION_KEY is set but is not a valid Fernet key "
            f"({exc}). It must be 32 url-safe base64-encoded bytes — regenerate "
            f'with: python -c "from cryptography.fernet import Fernet; '
            f'print(Fernet.generate_key().decode())"'
        ) from exc


def verify_encryption_key_configured() -> None:
    """Fail loudly at app startup rather than on the first source registration.

    Called from `main.py`'s lifespan hook. Without this the missing-key error
    would only surface the first time somebody registered or read a data
    source, long after the deploy appeared to succeed.
    """
    _fernet()


def encrypt_config(config: dict) -> str:
    """Encrypt a connection-config dict into an opaque Fernet token string."""
    if not isinstance(config, dict):
        raise TypeError(
            f"encrypt_config expects a dict, got {type(config).__name__}"
        )
    plaintext = json.dumps(config, sort_keys=True, default=str).encode("utf-8")
    return _fernet().encrypt(plaintext).decode("ascii")


def decrypt_config(token: str) -> dict:
    """Decrypt a Fernet token string produced by `encrypt_config` back to a dict."""
    if not isinstance(token, str):
        raise TypeError(
            f"decrypt_config expects a str token, got {type(token).__name__}"
        )
    try:
        plaintext = _fernet().decrypt(token.encode("ascii"))
    except (InvalidToken, ValueError) as exc:
        # Deliberately does not include the token or any decrypted material in
        # the message — this string ends up in logs and error responses.
        raise InvalidToken(
            "Stored credential could not be decrypted. This usually means "
            "CREDENTIAL_ENCRYPTION_KEY differs from the key the row was "
            "written with."
        ) from exc
    return json.loads(plaintext.decode("utf-8"))


def is_encrypted(value) -> bool:
    """True if `value` is a token this module can decrypt.

    Used by the ORM type and the backfill script to tell an already-encrypted
    row from a legacy plaintext one, which is what makes the backfill safely
    re-runnable. Checks that the token actually decrypts rather than just
    pattern-matching the `gAAAAA` prefix, so a plaintext string that happens to
    look Fernet-shaped is never mistaken for ciphertext.
    """
    if not isinstance(value, str):
        return False
    try:
        _fernet().decrypt(value.encode("ascii"))
        return True
    except Exception:
        return False


# Keys whose values must never reach an API response, a log line, or an
# exception message. Matched case-insensitively as substrings, so `db_password`
# and `AWS_SECRET_ACCESS_KEY` are both caught.
SENSITIVE_KEY_FRAGMENTS = (
    "password", "passwd", "secret", "token", "api_key", "apikey",
    "credential", "private_key", "access_key", "auth",
)

REDACTED = "********"


def redact_config(config: dict) -> dict:
    """Return a copy of `config` with every credential-ish value masked.

    For API responses and log lines. Non-sensitive keys (host, port, database,
    file_path, table) are preserved so the Sources edit form still renders.
    """
    if not isinstance(config, dict):
        return {}
    lowered = SENSITIVE_KEY_FRAGMENTS
    return {
        k: (REDACTED if any(f in str(k).lower() for f in lowered) else v)
        for k, v in config.items()
    }
