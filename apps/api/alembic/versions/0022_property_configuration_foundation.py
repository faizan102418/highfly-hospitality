"""Add organization defaults and property branding configuration.

Revision ID: 0022_property_config
Revises: 0021_property_ownership
"""

from alembic import op
import sqlalchemy as sa


revision = "0022_property_config"
down_revision = "0021_property_ownership"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "organization_settings" not in tables:
        op.create_table(
            "organization_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "organization_id",
                sa.Integer(),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("setting_key", sa.String(120), nullable=False),
            sa.Column("setting_value", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "organization_id",
                "setting_key",
                name="uq_organization_settings_key",
            ),
        )
        op.create_index(
            "ix_organization_settings_organization_id",
            "organization_settings",
            ["organization_id"],
            unique=False,
        )

    if "property_branding" not in tables:
        op.create_table(
            "property_branding",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "property_id",
                sa.Integer(),
                sa.ForeignKey("properties.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("display_name", sa.String(160), nullable=False),
            sa.Column("logo_storage_key", sa.String(500), nullable=True),
            sa.Column("address_line1", sa.String(200), nullable=True),
            sa.Column("address_line2", sa.String(200), nullable=True),
            sa.Column("city", sa.String(120), nullable=True),
            sa.Column("region", sa.String(120), nullable=True),
            sa.Column("postal_code", sa.String(30), nullable=True),
            sa.Column("country", sa.String(120), nullable=True),
            sa.Column("phone", sa.String(50), nullable=True),
            sa.Column("email", sa.String(254), nullable=True),
            sa.Column("website", sa.String(300), nullable=True),
            sa.Column("primary_color", sa.String(7), nullable=True),
            sa.Column("secondary_color", sa.String(7), nullable=True),
            sa.Column("invoice_display_name", sa.String(160), nullable=True),
            sa.Column(
                "show_logo_on_documents",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint("property_id", name="uq_property_branding_property_id"),
        )

    # Initialize branding rows from verified property names only. Contact,
    # address, logo, and other presentation details remain unset until configured.
    bind.execute(
        sa.text(
            """
            INSERT INTO property_branding (property_id, display_name, show_logo_on_documents)
            SELECT p.id, p.name, TRUE
            FROM properties AS p
            WHERE NOT EXISTS (
                SELECT 1
                FROM property_branding AS pb
                WHERE pb.property_id = p.id
            )
            """
        )
    )


def downgrade() -> None:
    # Keep configuration data safe; use a verified backup for rollback.
    raise RuntimeError(
        "0022_property_config is intentionally irreversible."
    )
