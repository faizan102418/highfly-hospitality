"""Organization settings and property branding endpoints."""

import json
import re
from datetime import datetime
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import get_current_user, require_roles
from .db import get_db
from .models import AuditLog, User
from .tenancy import Organization, OrganizationSetting, Property, PropertyBranding, PropertyUserAccess

router = APIRouter(prefix="/api", tags=["configuration"])
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class SettingItem(BaseModel):
    key: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_.-]+$")
    value: str | None = Field(default=None, max_length=10000)


class OrganizationSettingsUpdate(BaseModel):
    settings: list[SettingItem] = Field(max_length=200)


class OrganizationSettingsResponse(BaseModel):
    organization_id: int
    settings: dict[str, str | None]


class PropertyBrandingUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=160)
    logo_storage_key: str | None = Field(default=None, max_length=500)
    address_line1: str | None = Field(default=None, max_length=200)
    address_line2: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=120)
    region: str | None = Field(default=None, max_length=120)
    postal_code: str | None = Field(default=None, max_length=30)
    country: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=254)
    website: str | None = Field(default=None, max_length=300)
    primary_color: str | None = None
    secondary_color: str | None = None
    invoice_display_name: str | None = Field(default=None, max_length=160)
    show_logo_on_documents: bool = True

    @field_validator("display_name")
    @classmethod
    def display_name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("display_name cannot be blank")
        return value

    @field_validator("primary_color", "secondary_color")
    @classmethod
    def validate_color(cls, value: str | None) -> str | None:
        if value is not None and not _COLOR_RE.fullmatch(value):
            raise ValueError("Colors must use #RRGGBB format")
        return value.upper() if value else value

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip()
            if value and ("@" not in value or value.startswith("@") or value.endswith("@")):
                raise ValueError("Invalid email address")
            return value or None
        return value

    @field_validator("website")
    @classmethod
    def validate_website(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip()
            if not value:
                return None
            parsed = urlparse(value)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ValueError("Website must be an absolute http(s) URL")
            return value
        return value


class PropertyBrandingResponse(PropertyBrandingUpdate):
    model_config = ConfigDict(from_attributes=True)
    property_id: int
    created_at: datetime
    updated_at: datetime


def _property_for_user(db: Session, property_id: int, user: User) -> Property:
    property_ = db.get(Property, property_id)
    if property_ is None:
        raise HTTPException(status_code=404, detail="Property not found")
    access = db.scalar(select(PropertyUserAccess.id).where(
        PropertyUserAccess.user_id == user.id,
        PropertyUserAccess.property_id == property_id,
    ))
    if access is None:
        raise HTTPException(status_code=403, detail="No access to this property")
    return property_


def _organization_for_user(db: Session, organization_id: int, user: User) -> Organization:
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    access = db.scalar(
        select(PropertyUserAccess.id)
        .join(Property, Property.id == PropertyUserAccess.property_id)
        .where(
            PropertyUserAccess.user_id == user.id,
            Property.organization_id == organization_id,
            PropertyUserAccess.access_scope == "organization",
        ).limit(1)
    )
    if access is None:
        raise HTTPException(status_code=403, detail="Organization-level access required")
    return organization


@router.get("/organizations/{organization_id}/settings", response_model=OrganizationSettingsResponse)
def get_organization_settings(
    organization_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _organization_for_user(db, organization_id, user)
    rows = db.scalars(select(OrganizationSetting).where(
        OrganizationSetting.organization_id == organization_id
    ).order_by(OrganizationSetting.setting_key)).all()
    return OrganizationSettingsResponse(
        organization_id=organization_id,
        settings={row.setting_key: row.setting_value for row in rows},
    )


@router.put("/organizations/{organization_id}/settings", response_model=OrganizationSettingsResponse)
def put_organization_settings(
    organization_id: int,
    payload: OrganizationSettingsUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
):
    _organization_for_user(db, organization_id, user)
    keys = [item.key for item in payload.settings]
    if len(keys) != len(set(keys)):
        raise HTTPException(status_code=422, detail="Setting keys must be unique in one request")
    for item in payload.settings:
        row = db.scalar(select(OrganizationSetting).where(
            OrganizationSetting.organization_id == organization_id,
            OrganizationSetting.setting_key == item.key,
        ))
        if row is None:
            row = OrganizationSetting(
                organization_id=organization_id,
                setting_key=item.key,
                setting_value=item.value,
            )
            db.add(row)
        else:
            row.setting_value = item.value
    db.add(AuditLog(
        user_id=user.id,
        action="update",
        entity_type="organization_settings",
        entity_id=str(organization_id),
        details=json.dumps({"keys": keys}),
    ))
    db.commit()
    rows = db.scalars(select(OrganizationSetting).where(
        OrganizationSetting.organization_id == organization_id
    ).order_by(OrganizationSetting.setting_key)).all()
    return OrganizationSettingsResponse(
        organization_id=organization_id,
        settings={row.setting_key: row.setting_value for row in rows},
    )


@router.get("/properties/{property_id}/branding", response_model=PropertyBrandingResponse)
def get_property_branding(
    property_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    property_ = _property_for_user(db, property_id, user)
    branding = db.scalar(select(PropertyBranding).where(PropertyBranding.property_id == property_id))
    if branding is None:
        # Existing properties are seeded by migration 0022; this fallback supports fresh local SQLite installs.
        branding = PropertyBranding(property_id=property_id, display_name=property_.name)
        db.add(branding)
        db.commit()
        db.refresh(branding)
    return branding


@router.put("/properties/{property_id}/branding", response_model=PropertyBrandingResponse)
def put_property_branding(
    property_id: int,
    payload: PropertyBrandingUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
):
    _property_for_user(db, property_id, user)
    branding = db.scalar(select(PropertyBranding).where(PropertyBranding.property_id == property_id))
    values = payload.model_dump()
    if branding is None:
        branding = PropertyBranding(property_id=property_id, **values)
        db.add(branding)
    else:
        for key, value in values.items():
            setattr(branding, key, value)
    db.add(AuditLog(
        user_id=user.id,
        action="update",
        entity_type="property_branding",
        entity_id=str(property_id),
        details=json.dumps({"fields": sorted(values)}),
    ))
    db.commit()
    db.refresh(branding)
    return branding
