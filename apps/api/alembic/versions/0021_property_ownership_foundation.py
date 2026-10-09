"""Add property ownership to root hotel data.

Revision ID: 0021_property_ownership
Revises: 0020_multi_tenant_foundation
"""

from alembic import op
import sqlalchemy as sa


revision = "0021_property_ownership"
down_revision = "0020_multi_tenant_foundation"
branch_labels = None
depends_on = None


ROOT_TABLES = [
    "room_types",
    "rooms",
    "guests",
    "reservations",
    "booking_groups",
    "stock_items",
    "suppliers",
    "menu_items",
    "expenses",
    "financial_transactions",
    "restaurant_orders",
    "audit_logs",
    "purchase_orders",
]

STATE_TABLES = [
    "business_date_state",
    "invoice_sequences",
]

ALL_PROPERTY_TABLES = ROOT_TABLES + STATE_TABLES


def _property_fk_name(table_name: str) -> str:
    return f"fk_{table_name}_property_id"


def _add_property_id(table_name: str) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    columns = {
        column["name"]
        for column in inspector.get_columns(table_name)
    }

    if "property_id" in columns:
        return

    column = sa.Column(
        "property_id",
        sa.Integer(),
        sa.ForeignKey(
            "properties.id",
            name=_property_fk_name(table_name),
            ondelete="RESTRICT",
        ),
        nullable=True,
    )

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(
            table_name,
            recreate="always",
        ) as batch_op:
            batch_op.add_column(column)
    else:
        op.add_column(table_name, column)


def _make_property_id_not_null(table_name: str) -> None:
    bind = op.get_bind()

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(
            table_name,
            recreate="always",
        ) as batch_op:
            batch_op.alter_column(
                "property_id",
                existing_type=sa.Integer(),
                nullable=False,
            )
    else:
        op.alter_column(
            table_name,
            "property_id",
            existing_type=sa.Integer(),
            nullable=False,
        )


def _add_property_unique_constraint(table_name: str) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    constraint_name = f"uq_{table_name}_property_id"

    constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints(table_name)
        if constraint.get("name")
    }

    if constraint_name in constraints:
        return

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(
            table_name,
            recreate="always",
        ) as batch_op:
            batch_op.create_unique_constraint(
                constraint_name,
                ["property_id"],
            )
    else:
        op.create_unique_constraint(
            constraint_name,
            table_name,
            ["property_id"],
        )


def _add_property_index(table_name: str) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    indexes = {
        index["name"]
        for index in inspector.get_indexes(table_name)
        if index.get("name")
    }

    index_name = f"ix_{table_name}_property_id"

    if index_name not in indexes:
        op.create_index(
            index_name,
            table_name,
            ["property_id"],
            unique=False,
        )


def upgrade() -> None:
    # Add nullable ownership columns first so existing rows can be
    # safely backfilled.
    for table_name in ALL_PROPERTY_TABLES:
        _add_property_id(table_name)

    bind = op.get_bind()

    # The existing system has one seeded property: La Serene.
    # All pre-tenancy operational data therefore belongs to that property.
    property_id = bind.execute(
        sa.text(
            """
            SELECT id
            FROM properties
            WHERE slug = 'la-serene'
            ORDER BY id
            LIMIT 1
            """
        )
    ).scalar()

    if property_id is None:
        raise RuntimeError(
            "Cannot apply 0021: La Serene property was not found."
        )

    for table_name in ALL_PROPERTY_TABLES:
        bind.execute(
            sa.text(
                f"""
                UPDATE {table_name}
                SET property_id = :property_id
                WHERE property_id IS NULL
                """
            ),
            {"property_id": property_id},
        )

    # Ownership becomes mandatory after backfill.
    for table_name in ALL_PROPERTY_TABLES:
        _make_property_id_not_null(table_name)

    # Business-date state and invoice numbering are maintained
    # independently for each property.
    for table_name in STATE_TABLES:
        _add_property_unique_constraint(table_name)

    # Index property ownership for all property-owned tables.
    for table_name in ALL_PROPERTY_TABLES:
        _add_property_index(table_name)


def downgrade() -> None:
    # Intentionally conservative: removing property ownership would
    # destroy the tenant-isolation foundation.
    raise RuntimeError(
        "0021_property_ownership is intentionally irreversible."
    )
