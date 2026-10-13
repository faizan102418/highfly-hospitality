from __future__ import annotations

import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg

from ops.backup.backup import create_backup, normalize_postgres_url, restore_and_verify


def maintenance_url(database_url: str) -> str:
    parts = urlsplit(normalize_postgres_url(database_url))
    return urlunsplit((parts.scheme, parts.netloc, "/postgres", parts.query, ""))


def with_database(database_url: str, database_name: str) -> str:
    parts = urlsplit(normalize_postgres_url(database_url))
    return urlunsplit((parts.scheme, parts.netloc, f"/{database_name}", parts.query, ""))


def main() -> None:
    source_url = normalize_postgres_url(os.environ["HMS_DATABASE_URL"])
    recovery_name = "la_serene_hms_recovery_ci"
    recovery_url = with_database(source_url, recovery_name)
    admin_url = maintenance_url(source_url)

    with psycopg.connect(admin_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{recovery_name}"')
            cur.execute(f'CREATE DATABASE "{recovery_name}"')

    try:
        # Seed representative tenant configuration into the disposable CI source
        # database before backup. The round-trip must preserve all three scopes.
        with psycopg.connect(source_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO organizations (name, slug, status, created_at, updated_at) "
                    "VALUES (%s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) RETURNING id",
                    ("Backup Roundtrip Org", "backup-roundtrip-org", "active"),
                )
                organization_id = cur.fetchone()[0]
                cur.execute(
                    "INSERT INTO properties (organization_id, name, code, slug, status, timezone, currency, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) RETURNING id",
                    (organization_id, "Backup Roundtrip Hotel", "BKR", "backup-roundtrip-hotel", "active", "Asia/Karachi", "PKR"),
                )
                property_id = cur.fetchone()[0]
                cur.execute(
                    "INSERT INTO organization_settings (organization_id, setting_key, setting_value, created_at, updated_at) "
                    "VALUES (%s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                    (organization_id, "default_language", "ur"),
                )
                cur.execute(
                    "INSERT INTO property_settings (property_id, setting_key, setting_value, created_at, updated_at) "
                    "VALUES (%s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
                    "(%s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                    (property_id, "language", "en", property_id, "currency", "USD"),
                )
                cur.execute(
                    "INSERT INTO property_branding "
                    "(property_id, display_name, primary_color, show_logo_on_documents, created_at, updated_at) "
                    "VALUES (%s, %s, %s, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                    (property_id, "Backup Roundtrip Brand", "#123ABC"),
                )
            conn.commit()

        with tempfile.TemporaryDirectory() as tmp:
            backup_dir = Path(tmp)
            dump_path, manifest_path = create_backup(backup_dir, retain=1)
            result = restore_and_verify(dump_path, manifest_path, recovery_url)
            assert result["status"] == "verified"
            with psycopg.connect(recovery_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT setting_value FROM organization_settings "
                        "WHERE organization_id = %s AND setting_key = %s",
                        (organization_id, "default_language"),
                    )
                    assert cur.fetchone() == ("ur",), "organization defaults were not restored"
                    cur.execute(
                        "SELECT setting_key, setting_value FROM property_settings "
                        "WHERE property_id = %s ORDER BY setting_key",
                        (property_id,),
                    )
                    assert cur.fetchall() == [("currency", "USD"), ("language", "en")], (
                        "property overrides were not restored"
                    )
                    cur.execute(
                        "SELECT display_name, primary_color FROM property_branding WHERE property_id = %s",
                        (property_id,),
                    )
                    assert cur.fetchone() == ("Backup Roundtrip Brand", "#123ABC"), (
                        "property branding was not restored"
                    )
            print({**result, "tenant_configuration_roundtrip": "verified"})
    finally:
        with psycopg.connect(admin_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(f'DROP DATABASE IF EXISTS "{recovery_name}"')


if __name__ == "__main__":
    main()
