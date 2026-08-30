"""Data-source credentials must never sit in Postgres as plaintext.

The load-bearing test here is `test_raw_db_row_never_contains_the_plaintext_password`:
it queries the `data_sources` table directly with raw SQL, deliberately
bypassing the ORM's decrypting accessor, because reading through
`DataSource.connection_config` would return the decrypted dict and happily
"pass" even if nothing were encrypted at all.
"""
import json
import uuid

import pytest
from cryptography.fernet import InvalidToken
from sqlalchemy import text

from database import AsyncSessionLocal
from models.all_models import DataSource, SourceType, Tenant
from services.encryption_service import (
    encrypt_config, decrypt_config, is_encrypted, redact_config, REDACTED,
)


PLAINTEXT_PASSWORD = "pl4int3xt-must-not-persist-a7f3c9"

SAMPLE_CONFIG = {
    "host": "postgres",
    "port": 5432,
    "database": "customer_warehouse",
    "username": "warehouse_reader",
    "password": PLAINTEXT_PASSWORD,
}


async def _make_tenant(db) -> str:
    tenant_id = str(uuid.uuid4())
    db.add(Tenant(
        id=tenant_id,
        name=f"Encryption Test {tenant_id[:8]}",
        slug=f"encryption-test-{tenant_id[:8]}",
    ))
    await db.commit()
    return tenant_id


async def _make_source(db, tenant_id: str, config: dict) -> str:
    source_id = str(uuid.uuid4())
    db.add(DataSource(
        id=source_id,
        tenant_id=tenant_id,
        name=f"Encrypted Source {source_id[:8]}",
        source_type=SourceType.POSTGRES,
        connection_config=config,
        schema_snapshot={},
        tags=[],
    ))
    await db.commit()
    return source_id


# ── The core guarantee ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_raw_db_row_never_contains_the_plaintext_password():
    """A freshly created source's raw DB row must not contain the password.

    Queried with raw SQL against the real column, NOT through the ORM's
    decrypting accessor — the whole point is to see what actually landed on
    disk.
    """
    async with AsyncSessionLocal() as db:
        tenant_id = await _make_tenant(db)
        source_id = await _make_source(db, tenant_id, dict(SAMPLE_CONFIG))

        raw = (await db.execute(
            text("SELECT connection_config::text FROM data_sources WHERE id = :id"),
            {"id": source_id},
        )).scalar_one()

    assert PLAINTEXT_PASSWORD not in raw, (
        "The plaintext password was found in the raw data_sources row. "
        f"Stored value: {raw[:200]}"
    )
    # Nor any other credential-ish part of the config.
    assert "warehouse_reader" not in raw
    assert "customer_warehouse" not in raw

    # And what IS there is a real Fernet token, not just a mangled string.
    stored = json.loads(raw)
    assert is_encrypted(stored), f"stored value is not a decryptable token: {stored[:80]}"


@pytest.mark.asyncio
async def test_orm_still_reads_back_the_original_dict():
    """Encryption must be invisible to every existing reader."""
    async with AsyncSessionLocal() as db:
        tenant_id = await _make_tenant(db)
        source_id = await _make_source(db, tenant_id, dict(SAMPLE_CONFIG))

    async with AsyncSessionLocal() as db:
        source = await db.get(DataSource, source_id)
        assert source.connection_config == SAMPLE_CONFIG
        # The connectors index these directly — prove they still work.
        assert source.connection_config["password"] == PLAINTEXT_PASSWORD
        assert source.connection_config["host"] == "postgres"
        assert source.connection_config["port"] == 5432


@pytest.mark.asyncio
async def test_legacy_plaintext_row_is_still_readable():
    """Rows written before encryption shipped must not break on read.

    This is what lets the app keep serving while the backfill script has not
    run yet — without it, deploying encryption would take every existing
    source offline.
    """
    async with AsyncSessionLocal() as db:
        tenant_id = await _make_tenant(db)
        source_id = str(uuid.uuid4())
        # Write plaintext JSON directly, simulating a pre-encryption row.
        await db.execute(
            text("INSERT INTO data_sources "
                 "(id, tenant_id, name, source_type, connection_config, is_active) "
                 "VALUES (:id, :tid, :name, 'POSTGRES', CAST(:cfg AS json), true)"),
            {"id": source_id, "tid": tenant_id, "name": "Legacy Source",
             "cfg": json.dumps(SAMPLE_CONFIG)},
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        source = await db.get(DataSource, source_id)
        assert source.connection_config == SAMPLE_CONFIG


@pytest.mark.asyncio
async def test_resaving_an_encrypted_row_does_not_double_encrypt():
    async with AsyncSessionLocal() as db:
        tenant_id = await _make_tenant(db)
        source_id = await _make_source(db, tenant_id, dict(SAMPLE_CONFIG))

    async with AsyncSessionLocal() as db:
        source = await db.get(DataSource, source_id)
        source.name = "Renamed, config untouched"
        await db.commit()

    async with AsyncSessionLocal() as db:
        source = await db.get(DataSource, source_id)
        assert source.connection_config == SAMPLE_CONFIG


# ── encryption_service unit behaviour ─────────────────────────────────────────

def test_encrypt_decrypt_round_trip():
    token = encrypt_config(SAMPLE_CONFIG)
    assert isinstance(token, str)
    assert PLAINTEXT_PASSWORD not in token
    assert decrypt_config(token) == SAMPLE_CONFIG


def test_encryption_is_non_deterministic_but_still_decryptable():
    """Fernet embeds a random IV, so the same input yields different tokens."""
    a, b = encrypt_config(SAMPLE_CONFIG), encrypt_config(SAMPLE_CONFIG)
    assert a != b
    assert decrypt_config(a) == decrypt_config(b) == SAMPLE_CONFIG


def test_is_encrypted_distinguishes_tokens_from_plaintext():
    assert is_encrypted(encrypt_config(SAMPLE_CONFIG)) is True
    assert is_encrypted(SAMPLE_CONFIG) is False
    assert is_encrypted("not a token") is False
    assert is_encrypted("gAAAAABmFakeButWrongShape") is False
    assert is_encrypted(None) is False


def test_decrypt_error_message_does_not_echo_the_token():
    """Decryption failures land in logs — they must not carry the ciphertext."""
    token = encrypt_config(SAMPLE_CONFIG)
    tampered = token[:-8] + "AAAAAAAA"
    with pytest.raises(InvalidToken) as excinfo:
        decrypt_config(tampered)
    assert tampered not in str(excinfo.value)
    assert PLAINTEXT_PASSWORD not in str(excinfo.value)


# ── redaction ─────────────────────────────────────────────────────────────────

def test_redact_config_masks_credentials_but_keeps_connection_details():
    redacted = redact_config(SAMPLE_CONFIG)
    assert redacted["password"] == REDACTED
    assert redacted["host"] == "postgres"
    assert redacted["port"] == 5432
    assert redacted["database"] == "customer_warehouse"
    assert PLAINTEXT_PASSWORD not in json.dumps(redacted)


def test_redact_config_catches_credential_key_variants():
    redacted = redact_config({
        "db_password": "a", "API_KEY": "b", "auth_token": "c",
        "aws_secret_access_key": "d", "private_key": "e",
        "host": "keepme", "table": "orders",
    })
    for key in ("db_password", "API_KEY", "auth_token",
                "aws_secret_access_key", "private_key"):
        assert redacted[key] == REDACTED, f"{key} was not redacted"
    assert redacted["host"] == "keepme"
    assert redacted["table"] == "orders"
