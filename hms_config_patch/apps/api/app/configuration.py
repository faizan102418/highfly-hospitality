"""Organization settings and property branding API.

All access decisions are made server-side from the authenticated user and
explicit PropertyUserAccess records. No configuration is accepted from JWT claims.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import get_current_user, require_roles
from .db import get_db
from .models import AuditLog, User
from .tenancy import (
    Organization,
    OrganizationSetting,
    Property,
    PropertyBranding,
    PropertyUserAccess,
)

router = APIRouter(prefix="/api", tags=["configuration"])


class SettingItem(BaseModel):
    key: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_.-]+$")
    value: str | None = Field(default=None, max_length=10000)


class OrganizationSettingsResponse(BaseModel):
    organization_id: int
    settings: dict[str, str | None]


class OrganizationSettingsUpdate(BaseModel):
    settings: list[SettingItem] = Field(min_length=1, max_length=100)


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

    @field_validator("primary_color", "secondary_color")
    @classmethod
    def validate_color(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
            raise ValueError("Color must be a six-digit hex value such as #1A2B3C")
        return value

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value is not None and ("@" not in value or value.startswith("@") or value.endswith("@")):
            raise ValueError("Enter a valid email address")
        return value

    @field_validator("website")
    @classmethod
    def validate_website(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"https?://[^\s]+", value, re.IGNORECASE):
            raise ValueError("Website must start with http:// or https://")
        return value


class PropertyBrandingResponse(PropertyBrandingUpdate):
    model_config = ConfigDict(from_attributes=True)
    property_id: int
    created_at: datetime
    updated_at: datetime


def _accessible_organization_ids(db: Session, user: User) -> set[int]:
    rows = db.execute(
        select(Property.organization_id)
        .join(PropertyUserAccess, PropertyUserAccess.property_id == Property.id)
        .where(PropertyUserAccess.user_id == user.id)
    ).all()
    return {row[0] for row in rows}


def _require_organization_access(db: Session, user: User, organization_id: int) -> Organization:
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    if organization_id not in _accessible_organization_ids(db, user):
        raise HTTPException(status_code=403, detail="No access to this organization")
    return organization


def _require_property_access(db: Session, user: User, property_id: int) -> Property:
    property_ = db.get(Property, property_id)
    if property_ is None:
        raise HTTPException(status_code=404, detail="Property not found")
    access = db.scalar(
        select(PropertyUserAccess.id).where(
            PropertyUserAccess.user_id == user.id,
            PropertyUserAccess.property_id == property_id,
        )
    )
    if access is None:
        raise HTTPException(status_code=403, detail="No access to this property")
    return property_


def _audit(db: Session, user: User, action: str, entity_type: str, entity_id: int, details: dict) -> None:
    db.add(AuditLog(
        user_id=user.id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        details=json.dumps(details, sort_keys=True),
    ))


@router.get("/organizations/{organization_id}/settings", response_model=OrganizationSettingsResponse)
def get_organization_settings(
    organization_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_organization_access(db, user, organization_id)
    rows = db.scalars(
        select(OrganizationSetting)
        .where(OrganizationSetting.organization_id == organization_id)
        .order_by(OrganizationSetting.setting_key)
    ).all()
    return OrganizationSettingsResponse(
        organization_id=organization_id,
        settings={row.setting_key: row.setting_value for row in rows},
    )


@router.put("/organizations/{organization_id}/settings", response_model=OrganizationSettingsResponse)
def update_organization_settings(
    organization_id: int,
    payload: OrganizationSettingsUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
):
    _require_organization_access(db, user, organization_id)
    keys = [item.key for item in payload.settings]
    if len(keys) != len(set(keys)):
        raise HTTPException(status_code=422, detail="Each setting key may appear only once per request")
    for item in payload.settings:
        row = db.scalar(select(OrganizationSetting).where(
            OrganizationSetting.organization_id == organization_id,
            OrganizationSetting.setting_key == item.key,
        ))
        if row is None:
            row = OrganizationSetting(organization_id=organization_id, setting_key=item.key, setting_value=item.value)
            db.add(row)
        else:
            row.setting_value = item.value
    _audit(db, user, "update", "organization_settings", organization_id, {"keys": keys})
    db.commit()
    rows = db.scalars(select(OrganizationSetting).where(
        OrganizationSetting.organization_id == organization_id
    ).order_by(OrganizationSetting.setting_key)).all()
    return OrganizationSettingsResponse(organization_id=organization_id, settings={r.setting_key: r.setting_value for r in rows})


@router.get("/properties/{property_id}/branding", response_model=PropertyBrandingResponse)
def get_property_branding(
    property_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_property_access(db, user, property_id)
    branding = db.scalar(select(PropertyBranding).where(PropertyBranding.property_id == property_id))
    if branding is None:
        raise HTTPException(status_code=404, detail="Property branding is not configured")
    return branding


@router.put("/properties/{property_id}/branding", response_model=PropertyBrandingResponse)
def update_property_branding(
    property_id: int,
    payload: PropertyBrandingUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
):
    _require_property_access(db, user, property_id)
    branding = db.scalar(select(PropertyBranding).where(PropertyBranding.property_id == property_id))
    if branding is None:
        branding = PropertyBranding(property_id=property_id, **payload.model_dump())
        db.add(branding)
    else:
        for key, value in payload.model_dump().items():
            setattr(branding, key, value)
    _audit(db, user, "update", "property_branding", property_id, {"display_name": payload.display_name})
    db.commit()
    db.refresh(branding)
    return branding
