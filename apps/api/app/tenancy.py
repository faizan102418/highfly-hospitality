from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="active")
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active")
    timezone: Mapped[str] = mapped_column(String(80), default="Asia/Karachi")
    currency: Mapped[str] = mapped_column(String(3), default="PKR")
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)


class PropertyUserAccess(Base):
    __tablename__ = "property_user_access"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    access_scope: Mapped[str] = mapped_column(String(30), default="property")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class PropertySetting(Base):
    __tablename__ = "property_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    setting_key: Mapped[str] = mapped_column(String(120))
    setting_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)


class OrganizationSetting(Base):
    __tablename__ = "organization_settings"
    __table_args__ = (
        UniqueConstraint("organization_id", "setting_key", name="uq_organization_settings_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    setting_key: Mapped[str] = mapped_column(String(120), nullable=False)
    setting_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)


class PropertyBranding(Base):
    __tablename__ = "property_branding"
    __table_args__ = (UniqueConstraint("property_id", name="uq_property_branding_property_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    logo_storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    address_line1: Mapped[str | None] = mapped_column(String(200), nullable=True)
    address_line2: Mapped[str | None] = mapped_column(String(200), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    region: Mapped[str | None] = mapped_column(String(120), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    country: Mapped[str | None] = mapped_column(String(120), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    website: Mapped[str | None] = mapped_column(String(300), nullable=True)
    primary_color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    secondary_color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    invoice_display_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    show_logo_on_documents: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)


# Request handlers must resolve a property through this helper instead of
# silently using a global/default tenant. Callers may pass an explicitly
# selected property ID; otherwise only the user's marked primary property is
# eligible. A user with no primary property must complete provisioning first.
def resolve_authorized_property(db, user_id: int, property_id: int | None = None) -> Property:
    from fastapi import HTTPException
    from sqlalchemy import select

    stmt = (
        select(Property)
        .join(PropertyUserAccess, PropertyUserAccess.property_id == Property.id)
        .where(
            PropertyUserAccess.user_id == user_id,
            Property.status == "active",
            Organization.status == "active",
            Organization.id == Property.organization_id,
        )
        .join(Organization, Organization.id == Property.organization_id)
    )
    if property_id is None:
        stmt = stmt.where(PropertyUserAccess.is_primary.is_(True))
    else:
        stmt = stmt.where(Property.id == property_id)

    matches = db.scalars(stmt.order_by(Property.id)).all()
    if not matches:
        if property_id is None:
            raise HTTPException(
                status_code=409,
                detail="No active primary property is configured for this user",
            )
        raise HTTPException(status_code=403, detail="No access to the selected property")
    if property_id is None and len(matches) != 1:
        raise HTTPException(
            status_code=409,
            detail="Multiple primary properties are configured; select a property explicitly",
        )
    return matches[0]
