"""Explicit shared tenant fixture for PostgreSQL integration tests."""
from datetime import date

from sqlalchemy import select

from app.tenancy import Organization, Property


def ensure_test_property(db):
    organization = db.scalar(select(Organization).where(Organization.slug == "ci-test-org"))
    if organization is None:
        organization = Organization(name="CI Test Organization", slug="ci-test-org")
        db.add(organization)
        db.flush()

    property_ = db.scalar(
        select(Property).where(
            Property.organization_id == organization.id,
            Property.slug == "ci-test-property",
        )
    )
    if property_ is None:
        property_ = Property(
            organization_id=organization.id,
            name="CI Test Property",
            code="CI-TEST",
            slug="ci-test-property",
            timezone="UTC",
            currency="PKR",
        )
        db.add(property_)
        db.flush()

    db.flush()
    return property_
