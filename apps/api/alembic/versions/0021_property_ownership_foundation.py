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
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    missing = [name for name in ALL_PROPERTY_TABLES if name not in inspector.get_table_names()]
    if missing:
        raise RuntimeError("Cannot apply 0021: expected operational tables are missing: " + ", ".join(missing))

    # Never guess ownership from a customer name or slug. This revision only
    # upgrades a clean install; legacy rows require an explicit reviewed mapping.
    counts = {
        table_name: bind.execute(sa.text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one()
        for table_name in ALL_PROPERTY_TABLES
    }
    populated = {name: count for name, count in counts.items() if count}
    if populated:
        summary = ", ".join(f"{name}={count}" for name, count in populated.items())
        raise RuntimeError(
            "Cannot apply 0021: legacy operational rows exist and property ownership cannot be inferred. "
            "No rows were assigned or changed. Provision a tenant and write an explicit ownership "
            f"migration before retrying. Non-empty tables: {summary}"
        )

    for table_name in ALL_PROPERTY_TABLES:
        _add_property_id(table_name)
    for table_name in ALL_PROPERTY_TABLES:
        _make_property_id_not_null(table_name)
    for table_name in STATE_TABLES:
        _add_property_unique_constraint(table_name)
    for table_name in ALL_PROPERTY_TABLES:
        _add_property_index(table_name)


def downgrade() -> None:
    # Intentionally conservative: removing property ownership would
    # destroy the tenant-isolation foundation.
    raise RuntimeError(
        "0021_property_ownership is intentionally irreversible."
    )
