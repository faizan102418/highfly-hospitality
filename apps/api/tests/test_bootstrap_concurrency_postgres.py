"""PostgreSQL integration test for concurrent first-admin bootstrap."""
import threading
import unittest
from uuid import uuid4
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Base, engine
from app.main import bootstrap_admin
from app.models import Role, User
from app.schemas import BootstrapAdminRequest
from app.tenancy import Organization, Property


class BootstrapConcurrencyPostgreSQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if engine.dialect.name != "postgresql":
            raise unittest.SkipTest("HMS_DATABASE_URL is not PostgreSQL")

    def test_only_one_concurrent_bootstrap_creates_initial_admin_and_tenant(self):
        schema = f"bootstrap_race_{uuid4().hex[:12]}"
        with engine.connect() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            Base.metadata.create_all(bind=connection)
            connection.commit()
            with Session(bind=connection) as db:
                db.add(Role(name="admin"))
                db.commit()
            connection.exec_driver_sql("SET search_path TO public")
            connection.commit()

        barrier = threading.Barrier(2)
        results = []
        result_lock = threading.Lock()
        payloads = [
            BootstrapAdminRequest(
                username=f"first-admin-{i}",
                password="long-enough-test-password",
                organization_name="Concurrency Test Organization",
                organization_slug="concurrency-test-organization",
                property_name="Concurrency Test Property",
                property_code="CONCURRENCY-TEST",
                property_slug="concurrency-test-property",
                timezone="UTC",
                currency="PKR",
            )
            for i in (1, 2)
        ]

        def attempt(payload):
            try:
                with engine.connect() as connection:
                    try:
                        connection.exec_driver_sql(f'SET search_path TO "{schema}"')
                        connection.commit()
                        with Session(bind=connection) as db:
                            barrier.wait(timeout=10)
                            result = bootstrap_admin(payload, setup_token="bootstrap-test-token", db=db)
                            outcome = ("created", result.username)
                    finally:
                        connection.rollback()
                        connection.exec_driver_sql("SET search_path TO public")
                        connection.commit()
            except HTTPException as exc:
                outcome = ("rejected", exc.status_code)
            except Exception as exc:  # surface unexpected thread failures to the assertion below
                outcome = ("error", repr(exc))
            with result_lock:
                results.append(outcome)

        try:
            with patch("app.main.settings.bootstrap_token", "bootstrap-test-token"):
                threads = [threading.Thread(target=attempt, args=(payload,)) for payload in payloads]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=30)

            self.assertTrue(all(not thread.is_alive() for thread in threads), "bootstrap threads did not finish")
            self.assertEqual(sorted(item[0] for item in results), ["created", "rejected"], results)
            rejected = next(item for item in results if item[0] == "rejected")
            self.assertEqual(rejected[1], 409)

            with engine.connect() as connection:
                connection.exec_driver_sql(f'SET search_path TO "{schema}"')
                connection.commit()
                with Session(bind=connection) as db:
                    self.assertEqual(db.scalar(select(User.id).limit(1)) is not None, True)
                    self.assertEqual(len(db.scalars(select(User.id)).all()), 1)
                    self.assertEqual(len(db.scalars(select(Organization.id)).all()), 1)
                    self.assertEqual(len(db.scalars(select(Property.id)).all()), 1)
                connection.exec_driver_sql("SET search_path TO public")
                connection.commit()
        finally:
            with engine.connect() as connection:
                connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
                connection.commit()


if __name__ == "__main__":
    unittest.main()
