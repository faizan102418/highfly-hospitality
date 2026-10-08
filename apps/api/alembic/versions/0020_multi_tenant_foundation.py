"""Introduce the organization/property tenancy foundation.

Revision ID: 0020_multi_tenant_foundation
Revises: 0019_business_date_closure
"""
from alembic import op
import sqlalchemy as sa

revision = "0020_multi_tenant_foundation"
down_revision = "0019_business_date_closure"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "organizations" not in tables:
        op.create_table(
            "organizations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("slug", sa.String(120), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("slug", name="uq_organizations_slug"),
        )

    if "properties" not in tables:
        op.create_table(
            "properties",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("code", sa.String(60), nullable=False),
            sa.Column("slug", sa.String(120), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, server_default="active"),
            sa.Column("timezone", sa.String(80), nullable=False, server_default="Asia/Karachi"),
            sa.Column("currency", sa.String(3), nullable=False, server_default="PKR"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("organization_id", "code", name="uq_properties_org_code"),
            sa.UniqueConstraint("organization_id", "slug", name="uq_properties_org_slug"),
        )
        op.create_index("ix_properties_organization_id", "properties", ["organization_id"])

    if "property_user_access" not in tables:
        op.create_table(
            "property_user_access",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("property_id", sa.Integer(), sa.ForeignKey("properties.id", ondelete="CASCADE"), nullable=False),
            sa.Column("access_scope", sa.String(30), nullable=False, server_default="property"),
            sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("user_id", "property_id", name="uq_property_user_access"),
        )
        op.create_index("ix_property_user_access_user_id", "property_user_access", ["user_id"])
        op.create_index("ix_property_user_access_property_id", "property_user_access", ["property_id"])

    if "property_settings" not in tables:
        op.create_table(
            "property_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("property_id", sa.Integer(), sa.ForeignKey("properties.id", ondelete="CASCADE"), nullable=False),
            sa.Column("setting_key", sa.String(120), nullable=False),
            sa.Column("setting_value", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("property_id", "setting_key", name="uq_property_settings_key"),
        )
        op.create_index("ix_property_settings_property_id", "property_settings", ["property_id"])

    org_id = bind.execute(
        sa.text("SELECT id FROM organizations WHERE slug = :slug"),
        {"slug": "highfly-hospitality"},
    ).scalar()
    if org_id is None:
        org_id = bind.execute(
            sa.text(
                "INSERT INTO organizations (name, slug, status) "
                "VALUES (:name, :slug, 'active') RETURNING id"
            ),
            {"name": "HighFly Hospitality", "slug": "highfly-hospitality"},
        ).scalar()

    property_id = bind.execute(
        sa.text(
            "SELECT id FROM properties WHERE organization_id = :org_id AND slug = :slug"
        ),
        {"org_id": org_id, "slug": "la-serene"},
    ).scalar()
    if property_id is None:
        property_id = bind.execute(
            sa.text(
                "INSERT INTO properties "
                "(organization_id, name, code, slug, status, timezone, currency) "
                "VALUES (:org_id, :name, :code, :slug, 'active', 'Asia/Karachi', 'PKR') "
                "RETURNING id"
            ),
            {
                "org_id": org_id,
                "name": "La Serene Hotel & Resort",
                "code": "LA-SERENE",
                "slug": "la-serene",
            },
        ).scalar()

    bind.execute(
        sa.text(
            "INSERT INTO property_user_access "
            "(user_id, property_id, access_scope, is_primary) "
            "SELECT u.id, :property_id, "
            "CASE WHEN r.name = 'admin' THEN 'organization' ELSE 'property' END, "
            "TRUE FROM users u JOIN roles r ON r.id = u.role_id "
            "WHERE NOT EXISTS ("
            " SELECT 1 FROM property_user_access pua "
            " WHERE pua.user_id = u.id AND pua.property_id = :property_id"
            ")"
        ),
        {"property_id": property_id},
    )


def downgrade() -> None:
    raise RuntimeError("Multi-tenant foundation is non-destructively upgraded; restore a verified backup to roll it back.")
