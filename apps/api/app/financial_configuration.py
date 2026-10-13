"""Property-scoped financial policy resolution for authoritative posting and reporting."""
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .configuration_schema import resolve_effective_settings
from .tenancy import OrganizationSetting, Property, PropertySetting


def effective_financial_settings(db: Session, property_id: int) -> dict:
    """Resolve financial policy using property override -> organization -> platform."""
    property_ = db.get(Property, property_id)
    if property_ is None:
        raise ValueError(f"Property {property_id} does not exist")
    organization_rows = db.scalars(
        select(OrganizationSetting).where(
            OrganizationSetting.organization_id == property_.organization_id
        )
    ).all()
    property_rows = db.scalars(
        select(PropertySetting).where(PropertySetting.property_id == property_id)
    ).all()
    resolved = resolve_effective_settings(
        {row.setting_key: row.setting_value for row in organization_rows},
        {row.setting_key: row.setting_value for row in property_rows},
    )
    return resolved["settings"]


def effective_service_charge_rate(db: Session, property_id: int) -> Decimal:
    """Return the configured service-charge percentage as a decimal multiplier."""
    settings = effective_financial_settings(db, property_id)
    return Decimal(settings["service_charge_percent"]) / Decimal("100")
