"""Seed the initial hotel business date.

Revision ID: 0008_seed_business_date
Revises: 0007_financial_idempotency
"""
from alembic import op

revision = "0008_seed_business_date"
down_revision = "0007_financial_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Business-date state is created for each property during explicit tenant
    # provisioning. A migration must never create a global singleton row.
    pass


def downgrade() -> None:
    # Non-destructive: property-specific business-date history belongs to tenants.
    pass
