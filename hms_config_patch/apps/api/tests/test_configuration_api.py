import unittest

from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.main import app  # noqa: F401 — register all HMS tables before metadata.create_all
from app.configuration import (
    PropertyBrandingUpdate,
    _require_organization_access,
    _require_property_access,
)
from app.db import Base
from app.models import Role, User
from app.tenancy import Organization, Property, PropertyUserAccess, OrganizationSetting, PropertyBranding


class ConfigurationApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=cls.engine)

    def setUp(self):
        self.db = Session(self.engine)
        for model in (PropertyBranding, OrganizationSetting, PropertyUserAccess, Property, Organization, User, Role):
            self.db.query(model).delete()
        self.db.commit()
        role = Role(name="admin")
        self.db.add(role)
        self.db.flush()
        self.user = User(username="config-admin", password_hash="test", role_id=role.id)
        self.db.add(self.user)
        self.org = Organization(name="HighFly Hospitality", slug="highfly-config-test")
        self.db.add(self.org)
        self.db.flush()
        self.property = Property(organization_id=self.org.id, name="La Serene", code="LS-CONFIG", slug="la-serene-config")
        self.other_property = Property(organization_id=self.org.id, name="Other", code="OTHER-CONFIG", slug="other-config")
        self.other_org = Organization(name="Other Org", slug="other-config-org")
        self.db.add_all([self.property, self.other_property, self.other_org])
        self.db.flush()
        self.other_org_property = Property(organization_id=self.other_org.id, name="Other Org Hotel", code="OOH", slug="other-org-hotel")
        self.db.add(self.other_org_property)
        self.db.add(PropertyUserAccess(user_id=self.user.id, property_id=self.property.id, access_scope="property", is_primary=True))
        self.db.commit()

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def test_branding_validation_accepts_hex_colors_and_rejects_bad_colors(self):
        payload = PropertyBrandingUpdate(display_name="La Serene", primary_color="#1A2B3C")
        self.assertEqual(payload.primary_color, "#1A2B3C")
        with self.assertRaises(ValidationError):
            PropertyBrandingUpdate(display_name="La Serene", primary_color="red")

    def test_branding_validation_rejects_non_http_website(self):
        with self.assertRaises(ValidationError):
            PropertyBrandingUpdate(display_name="La Serene", website="laserene.example")

    def test_user_can_access_organization_via_explicit_property_access(self):
        found = _require_organization_access(self.db, self.user, self.org.id)
        self.assertEqual(found.id, self.org.id)

    def test_user_cannot_access_unassigned_property(self):
        with self.assertRaises(HTTPException) as ctx:
            _require_property_access(self.db, self.user, self.other_property.id)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_user_cannot_access_organization_without_property_access(self):
        with self.assertRaises(HTTPException) as ctx:
            _require_organization_access(self.db, self.user, self.other_org.id)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_unknown_property_returns_not_found(self):
        with self.assertRaises(HTTPException) as ctx:
            _require_property_access(self.db, self.user, 999999)
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
