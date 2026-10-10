import unittest
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import engine
from app.models import Role, User
from app.tenancy import Organization, Property, PropertyUserAccess, resolve_authorized_property
from tenant_test_support import ensure_test_property


class PropertyIsolationPostgreSQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if engine.dialect.name != "postgresql":
            raise unittest.SkipTest("HMS_DATABASE_URL is not PostgreSQL")

    def test_user_cannot_resolve_an_unassigned_property(self):
        suffix = uuid4().hex[:12]
        with Session(engine) as db:
            allowed_property = ensure_test_property(db)
            organization = Organization(
                name=f"Isolation Org {suffix}",
                slug=f"isolation-org-{suffix}",
            )
            db.add(organization)
            db.flush()
            other_property = Property(
                organization_id=organization.id,
                name=f"Isolation Property {suffix}",
                code=f"ISO-{suffix[:6]}",
                slug=f"isolation-property-{suffix}",
                timezone="UTC",
                currency="PKR",
            )
            db.add(other_property)
            role = db.scalar(select(Role).where(Role.name == "admin"))
            if role is None:
                role = Role(name="admin")
                db.add(role)
                db.flush()
            user = User(
                username=f"ci-isolation-{suffix}",
                password_hash="test",
                role_id=role.id,
            )
            db.add(user)
            db.flush()
            db.add(PropertyUserAccess(
                user_id=user.id,
                property_id=allowed_property.id,
                access_scope="property",
                is_primary=True,
            ))
            db.flush()

            resolved = resolve_authorized_property(db, user.id)
            self.assertEqual(resolved.id, allowed_property.id)
            with self.assertRaises(HTTPException) as denied:
                resolve_authorized_property(db, user.id, other_property.id)
            self.assertEqual(denied.exception.status_code, 403)
            db.rollback()


if __name__ == "__main__":
    unittest.main()
