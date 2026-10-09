import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.configuration import BrandingUpdate, SettingsUpdate, _require_organization_access, _require_property_access
from app.db import Base
from app.models import Role, User
from app.tenancy import Organization, Property, PropertyUserAccess


class ConfigurationValidationTests(unittest.TestCase):
    def test_branding_accepts_valid_fields(self):
        payload = BrandingUpdate(display_name="La Serene", primary_color="#123ABC", email="desk@example.com", website="https://example.com")
        self.assertEqual(payload.primary_color, "#123ABC")

    def test_branding_rejects_invalid_color(self):
        with self.assertRaises(ValueError):
            BrandingUpdate(display_name="La Serene", primary_color="blue")

    def test_branding_rejects_website_without_scheme(self):
        with self.assertRaises(ValueError):
            BrandingUpdate(display_name="La Serene", website="example.com")

    def test_settings_rejects_overlong_values(self):
        with self.assertRaises(ValueError):
            SettingsUpdate(settings={"x": "a" * 10001})

    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=cls.engine)

    def test_property_access_is_explicit_and_organization_scope_is_required(self):
        with Session(self.engine) as db:
            role = Role(name="admin")
            db.add(role)
            db.flush()
            user = User(username="configuration-test", password_hash="test", role_id=role.id)
            org = Organization(name="Test Org", slug="configuration-test")
            db.add_all([user, org])
            db.flush()
            property_ = Property(organization_id=org.id, name="Hotel", code="HTL", slug="hotel")
            db.add(property_)
            db.flush()
            db.add(PropertyUserAccess(user_id=user.id, property_id=property_.id, access_scope="property"))
            db.commit()

            with self.assertRaises(HTTPException) as property_error:
                _require_property_access(db, user, Property(organization_id=org.id, name="Other", code="OTH", slug="other"))
            self.assertEqual(property_error.exception.status_code, 403)

            with self.assertRaises(HTTPException) as org_error:
                _require_organization_access(db, user, org.id)
            self.assertEqual(org_error.exception.status_code, 403)

            db.add(PropertyUserAccess(user_id=user.id, property_id=property_.id, access_scope="organization"))
            db.commit()
            _require_property_access(db, user, property_)
            _require_organization_access(db, user, org.id)


if __name__ == "__main__":
    unittest.main()
