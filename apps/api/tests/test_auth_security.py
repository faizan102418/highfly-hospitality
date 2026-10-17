import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.auth import ALGORITHM, SECRET_KEY, create_access_token, get_current_user, require_roles
from app.db import Base
from app.main import app, bootstrap_admin
from app.models import Role, User
from app.schemas import BootstrapAdminRequest


class AuthSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(bind=cls.engine)

    def setUp(self):
        self.db = Session(self.engine)
        self.db.query(User).delete()
        self.db.query(Role).delete()
        self.db.commit()

        self.admin_role = Role(name="admin")
        self.reception_role = Role(name="reception")
        self.housekeeping_role = Role(name="housekeeping")
        self.db.add_all([self.admin_role, self.reception_role, self.housekeeping_role])
        self.db.flush()

        self.user = User(
            username="security-admin",
            password_hash="not-used-by-these-tests",
            role_id=self.admin_role.id,
        )
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    @staticmethod
    def credentials(token):
        return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    def test_missing_credentials_are_rejected(self):
        with self.assertRaisesRegex(HTTPException, "Authentication required") as ctx:
            get_current_user(None, self.db)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_invalid_token_is_rejected(self):
        with self.assertRaisesRegex(HTTPException, "Invalid or expired token") as ctx:
            get_current_user(self.credentials("not-a-jwt"), self.db)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_expired_token_is_rejected(self):
        token = jwt.encode(
            {
                "sub": str(self.user.id),
                "role": self.admin_role.id,
                "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
            },
            SECRET_KEY,
            algorithm=ALGORITHM,
        )
        with self.assertRaisesRegex(HTTPException, "Invalid or expired token") as ctx:
            get_current_user(self.credentials(token), self.db)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_deleted_user_token_is_rejected(self):
        token = create_access_token(self.user)
        self.db.delete(self.user)
        self.db.commit()

        with self.assertRaisesRegex(HTTPException, "User not found") as ctx:
            get_current_user(self.credentials(token), self.db)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_role_is_resolved_from_database_not_jwt_claim(self):
        token = jwt.encode(
            {
                "sub": str(self.user.id),
                # Deliberately claim housekeeping while the DB user remains admin.
                "role": self.housekeeping_role.id,
                "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
            },
            SECRET_KEY,
            algorithm=ALGORITHM,
        )
        current_user = get_current_user(self.credentials(token), self.db)
        self.assertEqual(current_user.role_id, self.admin_role.id)

        admin_only = require_roles("admin")
        self.assertIs(admin_only(current_user, self.db), current_user)

        housekeeping_only = require_roles("housekeeping")
        with self.assertRaisesRegex(HTTPException, "Insufficient permissions") as ctx:
            housekeeping_only(current_user, self.db)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_wrong_role_is_rejected_by_server_side_authorization(self):
        self.user.role_id = self.reception_role.id
        self.db.commit()
        self.db.refresh(self.user)

        admin_only = require_roles("admin")
        with self.assertRaisesRegex(HTTPException, "Insufficient permissions") as ctx:
            admin_only(self.user, self.db)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_allowed_role_is_accepted(self):
        self.user.role_id = self.reception_role.id
        self.db.commit()
        self.db.refresh(self.user)

        reception_allowed = require_roles("admin", "reception")
        self.assertIs(reception_allowed(self.user, self.db), self.user)

    @staticmethod
    def bootstrap_payload():
        return BootstrapAdminRequest(
            username="first-admin",
            password="long-enough-test-password",
            organization_name="Test Organization",
            organization_slug="test-organization",
            property_name="Test Property",
            property_code="TEST-PROPERTY",
            property_slug="test-property",
            timezone="UTC",
            currency="PKR",
        )

    def test_bootstrap_is_disabled_without_a_configured_token(self):
        with patch("app.main.settings.bootstrap_token", ""):
            with self.assertRaisesRegex(HTTPException, "HMS_BOOTSTRAP_TOKEN is configured") as ctx:
                bootstrap_admin(self.bootstrap_payload(), setup_token=None, db=self.db)
        self.assertEqual(ctx.exception.status_code, 503)

    def test_bootstrap_rejects_an_invalid_setup_token(self):
        with patch("app.main.settings.bootstrap_token", "a" * 32):
            with self.assertRaisesRegex(HTTPException, "Invalid initial setup token") as ctx:
                bootstrap_admin(self.bootstrap_payload(), setup_token="wrong-token", db=self.db)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_bootstrap_still_rejects_reinitialization_with_valid_token(self):
        with patch("app.main.settings.bootstrap_token", "a" * 32):
            with self.assertRaisesRegex(HTTPException, "An initial user already exists") as ctx:
                bootstrap_admin(self.bootstrap_payload(), setup_token="a" * 32, db=self.db)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_api_routes_have_an_authentication_boundary(self):
        public_paths = {
            "/api/health",
            "/api/auth/setup-status",
            "/api/auth/bootstrap-admin",
            "/api/auth/login",
        }

        def dependency_names(dependant):
            names = set()
            for dependency in dependant.dependencies:
                call = dependency.call
                names.add(getattr(call, "__name__", ""))
                names.update(dependency_names(dependency))
            return names

        unprotected = []
        for route in app.routes:
            path = getattr(route, "path", "")
            if not path.startswith("/api/") or path in public_paths:
                continue
            names = dependency_names(route.dependant)
            if "get_current_user" not in names:
                unprotected.append(f"{','.join(sorted(getattr(route, 'methods', set())))} {path}")

        self.assertEqual([], unprotected, f"API routes without authentication: {unprotected}")


if __name__ == "__main__":
    unittest.main()
