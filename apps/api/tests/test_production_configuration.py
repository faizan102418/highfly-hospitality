"""Regression tests for the cloud production configuration contract."""

import unittest

from pydantic import ValidationError

from app.config import Settings


class ProductionConfigurationTests(unittest.TestCase):
    def make_production_settings(self, **overrides):
        values = {
            "environment": "production",
            "database_url": "postgresql+psycopg://hms:example@localhost:5432/la_serene_hms",
            "secret_key": "s" * 48,
        }
        values.update(overrides)
        return Settings(_env_file=None, **values)

    def test_production_requires_a_database_url(self):
        with self.assertRaisesRegex(ValidationError, "HMS_DATABASE_URL is required in production"):
            self.make_production_settings(database_url="")

    def test_production_rejects_sqlite_database_url(self):
        with self.assertRaisesRegex(ValidationError, "Production HMS_DATABASE_URL must use PostgreSQL"):
            self.make_production_settings(database_url="sqlite:///la_serene_hms.sqlite3")

    def test_production_rejects_default_or_short_secret(self):
        with self.assertRaisesRegex(ValidationError, "HMS_SECRET_KEY must be a strong non-default secret"):
            self.make_production_settings(secret_key="la-serene-development-secret-change-me")

        with self.assertRaisesRegex(ValidationError, "HMS_SECRET_KEY must be a strong non-default secret"):
            self.make_production_settings(secret_key="short")

    def test_valid_postgresql_production_configuration_is_accepted(self):
        settings = self.make_production_settings()
        self.assertEqual(settings.environment, "production")
        self.assertTrue(settings.database_url.startswith("postgresql+psycopg://"))
        self.assertEqual(len(settings.secret_key), 48)

    def test_bootstrap_token_must_be_at_least_32_characters_when_set(self):
        with self.assertRaisesRegex(ValidationError, "HMS_BOOTSTRAP_TOKEN must contain at least 32 characters"):
            self.make_production_settings(bootstrap_token="x" * 31)

    def test_32_character_bootstrap_token_is_accepted(self):
        settings = self.make_production_settings(bootstrap_token="x" * 32)
        self.assertEqual(settings.bootstrap_token, "x" * 32)


if __name__ == "__main__":
    unittest.main()
