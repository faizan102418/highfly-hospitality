"""Explicit shared tenant fixture for PostgreSQL integration tests."""
from datetime import date

from sqlalchemy import select

from app.financial_models import InvoiceSequence
from app.models import BusinessDateState
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

    state = db.scalar(
        select(BusinessDateState).where(BusinessDateState.property_id == property_.id)
    )
    if state is None:
        state = BusinessDateState(
            property_id=property_.id,
            current_business_date=date(2026, 9, 9),
        )
        db.add(state)

    sequence = db.scalar(
        select(InvoiceSequence).where(InvoiceSequence.property_id == property_.id)
    )
    if sequence is None:
        db.add(InvoiceSequence(property_id=property_.id, last_number=0))

    db.flush()
    return property_
