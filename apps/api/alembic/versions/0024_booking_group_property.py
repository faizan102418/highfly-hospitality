"""Add property ownership to booking groups and backfill unambiguous groups.

Revision ID: 0024_booking_group_property
Revises: 0023_property_date_guards
"""
from alembic import op
import sqlalchemy as sa

revision = "0024_booking_group_property"
down_revision = "0023_property_date_guards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    column = sa.Column(
        "property_id",
        sa.Integer(),
        sa.ForeignKey("properties.id", name="fk_booking_groups_property_id_properties"),
        nullable=True,
    )
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("booking_groups", recreate="always") as batch_op:
            batch_op.add_column(column)
            batch_op.create_index("ix_booking_groups_property_id", ["property_id"])
    else:
        op.add_column("booking_groups", column)
        op.create_index("ix_booking_groups_property_id", "booking_groups", ["property_id"])

    # Backfill only groups whose existing reservations all identify one property.
    # Empty and cross-property legacy groups remain NULL and are denied by the API.
    op.execute(sa.text("""
        UPDATE booking_groups AS bg
           SET property_id = scoped.property_id
          FROM (
              SELECT gr.group_id, MIN(r.property_id) AS property_id
                FROM group_reservations AS gr
                JOIN reservations AS r ON r.id = gr.reservation_id
               GROUP BY gr.group_id
              HAVING COUNT(DISTINCT r.property_id) = 1
          ) AS scoped
         WHERE bg.id = scoped.group_id
    """))


def downgrade() -> None:
    raise RuntimeError("Booking-group property ownership must not be removed.")
