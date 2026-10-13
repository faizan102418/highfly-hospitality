import json
import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.main import app  # noqa: F401 - register all API models before creating test metadata
from app.configuration import (
    BrandingUpdate,
    SettingsUpdate,
    _require_organization_access,
    _require_property_access,
    get_organization_settings,
    get_property_branding,
    get_property_settings,
    update_organization_settings,
    update_property_branding,
    update_property_settings,
)
from app.configuration_schema import validate_setting
from app.db import Base
from app.models import AuditLog, Role, User
from app.tenancy import Organization, OrganizationSetting, Property, PropertySetting, PropertyUserAccess


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

    def test_branding_rejects_blank_display_name(self):
        with self.assertRaises(ValueError):
            BrandingUpdate(display_name="   ")

    def test_branding_supports_partial_updates(self):
        payload = BrandingUpdate.model_validate({"primary_color": "#123ABC"})
        self.assertEqual(payload.model_dump(exclude_unset=True), {"primary_color": "#123ABC"})

    def test_settings_rejects_overlong_values(self):
        with self.assertRaises(ValueError):
            SettingsUpdate(settings={"x": "a" * 10001})

    def test_setting_registry_validates_scope_and_values(self):
        self.assertEqual(validate_setting("organization", "default_language", "ur"), "ur")
        self.assertEqual(validate_setting("property", "currency", "pkr"), "PKR")
        self.assertEqual(validate_setting("property", "tax_rate_percent", "17.00"), "17")
        with self.assertRaises(ValueError):
            validate_setting("organization", "currency", "PKR")
        with self.assertRaises(ValueError):
            validate_setting("property", "tax_rate_percent", "101")
        with self.assertRaises(ValueError):
            validate_setting("property", "timezone", "Not/A_Real_Zone")
        with self.assertRaises(ValueError):
            validate_setting("property", "enabled_modules", "front_desk,root_access")

    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=cls.engine)

    def test_access_settings_inheritance_audit_and_branding(self):
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
            access = PropertyUserAccess(user_id=user.id, property_id=property_.id, access_scope="property")
            db.add(access)
            db.commit()

            with self.assertRaises(HTTPException) as org_error:
                _require_organization_access(db, user, org.id)
            self.assertEqual(org_error.exception.status_code, 403)
            access.access_scope = "organization"
            db.commit()
            _require_property_access(db, user, property_)
            _require_organization_access(db, user, org.id)

            updated_settings = update_organization_settings(
                org.id,
                SettingsUpdate(settings={
                    "default_language": "ur",
                    "default_check_in_time": "15:00",
                    "default_tax_rate_percent": "17.00",
                }),
                db,
                user,
            )
            self.assertEqual(updated_settings["settings"]["default_language"], "ur")
            self.assertEqual(get_organization_settings(org.id, db, user)["settings"]["default_check_in_time"], "15:00")

            with self.assertRaises(HTTPException) as unknown_key:
                update_organization_settings(org.id, SettingsUpdate(settings={"currency": "PKR"}), db, user)
            self.assertEqual(unknown_key.exception.status_code, 422)

            effective = get_property_settings(property_.id, db, user)
            self.assertEqual(effective["settings"]["language"], "ur")
            self.assertEqual(effective["sources"]["language"], "organization")
            self.assertEqual(effective["settings"]["check_in_time"], "15:00")
            self.assertEqual(effective["sources"]["check_in_time"], "organization")
            self.assertEqual(effective["settings"]["currency"], "PKR")
            self.assertEqual(effective["sources"]["currency"], "platform")

            overridden = update_property_settings(
                property_.id,
                SettingsUpdate(settings={"language": "en", "currency": "usd", "timezone": "Asia/Karachi"}),
                db,
                user,
            )
            self.assertEqual(overridden["settings"]["language"], "en")
            self.assertEqual(overridden["sources"]["language"], "property")
            self.assertEqual(overridden["settings"]["currency"], "USD")
            self.assertEqual(overridden["sources"]["currency"], "property")

            reset = update_property_settings(property_.id, SettingsUpdate(settings={"language": None}), db, user)
            self.assertEqual(reset["settings"]["language"], "ur")
            self.assertEqual(reset["sources"]["language"], "organization")

            branding = update_property_branding(
                property_.id,
                BrandingUpdate(display_name="Configured Hotel", primary_color="#123ABC", show_logo_on_documents=False),
                db,
                user,
            )
            self.assertEqual(branding.display_name, "Configured Hotel")
            self.assertEqual(branding.primary_color, "#123ABC")
            self.assertFalse(branding.show_logo_on_documents)
            self.assertEqual(get_property_branding(property_.id, db, user).display_name, "Configured Hotel")

            # ORM metadata must enforce the same property/key uniqueness as migration 0020.
            db.add_all([
                PropertySetting(property_id=property_.id, setting_key="currency", setting_value="PKR"),
                PropertySetting(property_id=property_.id, setting_key="currency", setting_value="USD"),
            ])
            with self.assertRaises(Exception):
                db.commit()
            db.rollback()

            audits = db.scalars(select(AuditLog).where(AuditLog.property_id == property_.id)).all()
            self.assertTrue(any(row.entity_type == "organization_settings" for row in audits))
            self.assertTrue(any(row.entity_type == "property_settings" for row in audits))
            org_audit = next(row for row in audits if row.entity_type == "organization_settings")
            self.assertEqual(json.loads(org_audit.details)["keys"], ["default_check_in_time", "default_language", "default_tax_rate_percent"])


    def test_property_settings_and_branding_are_isolated_within_one_organization(self):
        with Session(self.engine) as db:
            role = Role(name="configuration-isolation-admin")
            db.add(role)
            db.flush()
            user = User(username="configuration-isolation-user", password_hash="test", role_id=role.id)
            org = Organization(name="Isolation Org", slug="configuration-isolation-org")
            db.add_all([user, org])
            db.flush()
            property_a = Property(organization_id=org.id, name="Hotel A", code="ISO-A", slug="isolation-a")
            property_b = Property(organization_id=org.id, name="Hotel B", code="ISO-B", slug="isolation-b")
            db.add_all([property_a, property_b])
            db.flush()
            db.add_all([
                PropertyUserAccess(user_id=user.id, property_id=property_a.id, access_scope="organization", is_primary=True),
                PropertyUserAccess(user_id=user.id, property_id=property_b.id, access_scope="organization"),
            ])
            db.commit()

            update_organization_settings(
                org.id,
                SettingsUpdate(settings={"default_language": "ur", "default_check_in_time": "15:00"}),
                db,
                user,
            )
            update_property_settings(
                property_a.id,
                SettingsUpdate(settings={"language": "en", "currency": "USD"}),
                db,
                user,
            )
            update_property_branding(
                property_a.id,
                BrandingUpdate(display_name="Hotel A Custom", primary_color="#112233"),
                db,
                user,
            )

            settings_a = get_property_settings(property_a.id, db, user)
            settings_b = get_property_settings(property_b.id, db, user)
            branding_a = get_property_branding(property_a.id, db, user)
            branding_b = get_property_branding(property_b.id, db, user)

            self.assertEqual(settings_a["settings"]["language"], "en")
            self.assertEqual(settings_a["sources"]["language"], "property")
            self.assertEqual(settings_b["settings"]["language"], "ur")
            self.assertEqual(settings_b["sources"]["language"], "organization")
            self.assertEqual(settings_b["settings"]["currency"], "PKR")
            self.assertEqual(settings_b["sources"]["currency"], "platform")
            self.assertEqual(settings_a["settings"]["check_in_time"], "15:00")
            self.assertEqual(settings_b["settings"]["check_in_time"], "15:00")
            self.assertEqual(branding_a.display_name, "Hotel A Custom")
            self.assertEqual(branding_a.primary_color, "#112233")
            self.assertEqual(branding_b.display_name, "Hotel B")
            self.assertIsNone(branding_b.primary_color)


if __name__ == "__main__":
    unittest.main()
