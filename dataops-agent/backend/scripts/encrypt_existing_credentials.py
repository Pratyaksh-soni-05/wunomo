"""One-time backfill: encrypt plaintext `data_sources.connection_config` rows.

Every source registered before credential encryption shipped has its
host/port/username/**password** sitting in Postgres as plaintext JSON. The
`EncryptedJSON` ORM type (models/all_models.py) encrypts everything written
from now on and transparently passes existing plaintext rows through on read,
so the app keeps working either way — this script converts the backlog.

Safe to re-run. Rows that are already encrypted are detected and skipped, so
running it twice does not double-encrypt, and an interrupted run can simply be
started again.

Deliberately bypasses the ORM and reads the column as raw text: going through
`EncryptedJSON` would decrypt on load, making an already-encrypted row
indistinguishable from a plaintext one and defeating the whole idempotency
check.

Run it inside the backend container:

    docker compose exec backend python -m scripts.encrypt_existing_credentials

Add --dry-run to report what would change without writing anything.
"""
import argparse
import json
import sys

from sqlalchemy import create_engine, text

from config import settings
from services.encryption_service import encrypt_config, decrypt_config, is_encrypted


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what would change without writing to the database.",
    )
    args = parser.parse_args()

    engine = create_engine(settings.SYNC_DATABASE_URL)

    encrypted_count = 0
    already_count = 0
    empty_count = 0
    failed: list[tuple[str, str]] = []

    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, name, connection_config::text FROM data_sources ORDER BY created_at"
        )).fetchall()

        print(f"Found {len(rows)} data_sources row(s).\n")

        for source_id, name, raw in rows:
            label = f"{source_id}  ({name})"

            if raw is None:
                empty_count += 1
                print(f"  SKIP  {label} — connection_config is NULL")
                continue

            try:
                value = json.loads(raw)
            except (ValueError, TypeError) as exc:
                failed.append((source_id, f"column is not valid JSON: {exc}"))
                print(f"  FAIL  {label} — column is not valid JSON: {exc}")
                continue

            if is_encrypted(value):
                already_count += 1
                print(f"  SKIP  {label} — already encrypted")
                continue

            if not isinstance(value, dict):
                failed.append((source_id, f"expected a dict, got {type(value).__name__}"))
                print(f"  FAIL  {label} — expected a dict, got {type(value).__name__}")
                continue

            # Encrypt, then prove the round-trip reproduces the original dict
            # BEFORE anything is written. A row that cannot be read back is a
            # permanently lost credential, so this is checked per row rather
            # than trusted once for the batch.
            try:
                token = encrypt_config(value)
                roundtripped = decrypt_config(token)
            except Exception as exc:
                failed.append((source_id, f"encryption failed: {exc}"))
                print(f"  FAIL  {label} — encryption failed: {exc}")
                continue

            if roundtripped != value:
                failed.append((source_id, "round-trip mismatch — not written"))
                print(f"  FAIL  {label} — round-trip mismatch, refusing to write")
                continue

            if args.dry_run:
                encrypted_count += 1
                print(f"  WOULD ENCRYPT  {label} — {len(value)} key(s), round-trip verified")
                continue

            # Each row is its own transaction: one bad row cannot roll back
            # rows that already converted and verified cleanly.
            with engine.begin() as write_conn:
                write_conn.execute(
                    text("UPDATE data_sources SET connection_config = CAST(:cfg AS json) "
                         "WHERE id = :id"),
                    {"cfg": json.dumps(token), "id": source_id},
                )
            encrypted_count += 1
            print(f"  OK    {label} — encrypted, round-trip verified")

    verb = "would be encrypted" if args.dry_run else "encrypted"
    print("\n" + "─" * 60)
    print(f"  {verb:>22}: {encrypted_count}")
    print(f"  {'already encrypted':>22}: {already_count}")
    if empty_count:
        print(f"  {'NULL config (skipped)':>22}: {empty_count}")
    if failed:
        print(f"  {'FAILED':>22}: {len(failed)}")
        for source_id, reason in failed:
            print(f"      {source_id}: {reason}")
    print("─" * 60)

    if args.dry_run:
        print("\nDry run — no rows were modified.")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
