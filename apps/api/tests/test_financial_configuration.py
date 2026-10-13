import unittest
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tenant_test_support import ensure_test_property
from app.db import Base
import app.models  # noqa: F401
import app.pms_core  # noqa: F401
from app.financial_configuration import effective_financial_settings, effective_service_charge_rate
from app.tenancy import Organization, OrganizationSetting, Property, PropertySetting


class FinancialConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    def setUp(self):
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)
        self.property = ensure_test_property(self.db)

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def test_platform_default_is_used_when_no_financial_setting_exists(self):
        self.assertEqual(effective_service_charge_rate(self.db, self.property.id), Decimal("0.10"))

    def test_organization_service_charge_default_is_used(self):
        self.db.add(OrganizationSetting(
            organization_id=self.property.organization_id,
            setting_key="default_service_charge_percent",
            setting_value="12.5",
        ))
        self.db.flush()
        self.assertEqual(effective_service_charge_rate(self.db, self.property.id), Decimal("0.125"))

    def test_property_override_wins_and_null_falls_back_to_organization(self):
        self.db.add(OrganizationSetting(
            organization_id=self.property.organization_id,
            setting_key="default_service_charge_percent",
            setting_value="12.5",
        ))
        self.db.add(PropertySetting(
            property_id=self.property.id,
            setting_key="service_charge_percent",
            setting_value="7.5",
        ))
        self.db.flush()
        self.assertEqual(effective_service_charge_rate(self.db, self.property.id), Decimal("0.075"))

        override = self.db.query(PropertySetting).filter_by(
            property_id=self.property.id, setting_key="service_charge_percent"
        ).one()
        override.setting_value = None
        self.db.flush()
        self.assertEqual(effective_service_charge_rate(self.db, self.property.id), 0.125)

    def test_financial_settings_are_scoped_to_requested_property(self):
        first = self.property
        second_org = Organization(name="Second Organization", slug="second-test-org")
        self.db.add(second_org)
        self.db.flush()
        second = Property(
            organization_id=second_org.id,
            name="Second Property",
            code="SECOND",
            slug="second-test-property",
            timezone="UTC",
            currency="PKR",
        )
        self.db.add(second)
        self.db.flush()
        self.db.add_all([
            OrganizationSetting(
                organization_id=first.organization_id,
                setting_key="default_service_charge_percent",
                setting_value="10",
            ),
            OrganizationSetting(
                organization_id=second.organization_id,
                setting_key="default_service_charge_percent",
                setting_value="4",
            ),
        ])
        self.db.flush()
        self.assertEqual(effective_service_charge_rate(self.db, first.id), Decimal("0.10"))
        self.assertEqual(effective_service_charge_rate(self.db, second.id), Decimal("0.04"))


if __name__ == "__main__":
    unittest.main()
