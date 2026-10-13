"""Organization defaults, property overrides, and property branding endpoints."""
import json
import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import get_current_user, require_roles
from .configuration_schema import (
    ORGANIZATION_KEYS,
    ORG_TO_PROPERTY,
    resolve_effective_settings,
    validate_setting,
)
from .db import get_db
from .models import AuditLog, User
from .tenancy import (
    Organization,
    OrganizationSetting,
    Property,
    PropertyBranding,
    PropertySetting,
    PropertyUserAccess,
)

router = APIRouter(prefix="/api", tags=["configuration"])


class SettingsUpdate(BaseModel):
    settings: dict[str, str | None] = Field(max_length=100)

    @field_validator("settings")
    @classmethod
    def validate_settings(cls, value: dict[str, str | None]) -> dict[str, str | None]:
        for key, setting_value in value.items():
            if not key.strip() or len(key) > 120:
                raise ValueError("Setting keys must be 1-120 characters")
            if setting_value is not None and len(setting_value) > 10000:
                raise ValueError("Setting values must not exceed 10000 characters")
        return value


class BrandingUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=160)
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
    primary_color: str | None = Field(default=None, max_length=7)
    secondary_color: str | None = Field(default=None, max_length=7)
    invoice_display_name: str | None = Field(default=None, max_length=160)
    show_logo_on_documents: bool = True

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("display_name must not be blank")
        return value.strip() if value is not None else None

    @field_validator("primary_color", "secondary_color")
    @classmethod
    def validate_color(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            raise ValueError("Colors must use #RRGGBB format")
        return value

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value is not None and value.strip() and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Invalid email address")
        return value.strip() if value is not None else None

    @field_validator("website")
    @classmethod
    def validate_website(cls, value: str | None) -> str | None:
        if value is not None and value.strip() and not re.match(r"^https?://", value, re.IGNORECASE):
            raise ValueError("Website must start with http:// or https://")
        return value.strip() if value is not None else None


class BrandingResponse(BrandingUpdate):
    model_config = ConfigDict(from_attributes=True)

    property_id: int
    created_at: datetime
    updated_at: datetime


def _require_property_access(db: Session, user: User, property_: Property) -> PropertyUserAccess:
    access = db.scalar(
        select(PropertyUserAccess).where(
            PropertyUserAccess.user_id == user.id,
            PropertyUserAccess.property_id == property_.id,
        )
    )
    if access is None:
        raise HTTPException(status_code=403, detail="No access to this property")
    return access


def _require_organization_access(db: Session, user: User, organization_id: int) -> None:
    access = db.scalar(
        select(PropertyUserAccess)
        .join(Property, Property.id == PropertyUserAccess.property_id)
        .where(
            PropertyUserAccess.user_id == user.id,
            PropertyUserAccess.access_scope == "organization",
            Property.organization_id == organization_id,
        )
    )
    if access is None:
        raise HTTPException(status_code=403, detail="Organization-level access required")


def _organization_audit_property(db: Session, user: User, organization_id: int) -> int:
    """Anchor organization-level audit entries to a deterministic authorized property."""
    property_id = db.scalar(
        select(Property.id)
        .join(PropertyUserAccess, PropertyUserAccess.property_id == Property.id)
        .where(
            Property.organization_id == organization_id,
            PropertyUserAccess.user_id == user.id,
            PropertyUserAccess.access_scope == "organization",
        )
        .order_by(Property.id)
        .limit(1)
    )
    if property_id is None:
        raise HTTPException(status_code=403, detail="Organization-level audit scope is unavailable")
    return property_id


def _audit(
    db: Session,
    user: User,
    property_id: int,
    action: str,
    entity_type: str,
    entity_id: int,
    details: dict[str, Any],
) -> None:
    db.add(
        AuditLog(
            property_id=property_id,
            user_id=user.id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            details=json.dumps(details, ensure_ascii=False, sort_keys=True),
        )
    )


def _validate_scope_settings(scope: str, settings: dict[str, str | None]) -> dict[str, str | None]:
    validated: dict[str, str | None] = {}
    for key, value in settings.items():
        if value is None:
            # Null is the explicit "remove this override/default" operation.
            validated[key] = None
            continue
        try:
            validated[key] = validate_setting(scope, key, value)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return validated


@router.get("/organizations/{organization_id}/settings")
def get_organization_settings(
    organization_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    _require_organization_access(db, user, organization_id)
    rows = db.scalars(
        select(OrganizationSetting)
        .where(OrganizationSetting.organization_id == organization_id)
        .order_by(OrganizationSetting.setting_key)
    ).all()
    return {
        "organization_id": organization_id,
        "settings": {row.setting_key: row.setting_value for row in rows if row.setting_value is not None},
        "allowed_keys": sorted(ORGANIZATION_KEYS),
    }


@router.put("/organizations/{organization_id}/settings")
def update_organization_settings(
    organization_id: int,
    payload: SettingsUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
):
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    _require_organization_access(db, user, organization_id)
    settings = _validate_scope_settings("organization", payload.settings)
    audit_property_id = _organization_audit_property(db, user, organization_id)
    changed: list[str] = []
    for key, value in settings.items():
        row = db.scalar(
            select(OrganizationSetting).where(
                OrganizationSetting.organization_id == organization_id,
                OrganizationSetting.setting_key == key,
            )
        )
        if value is None:
            if row is not None:
                db.delete(row)
                changed.append(key)
        elif row is None:
            db.add(OrganizationSetting(organization_id=organization_id, setting_key=key, setting_value=value))
            changed.append(key)
        elif row.setting_value != value:
            row.setting_value = value
            changed.append(key)
    if changed:
        _audit(db, user, audit_property_id, "update", "organization_settings", organization_id, {"keys": sorted(changed)})
    db.commit()
    return get_organization_settings(organization_id, db, user)


@router.get("/properties/{property_id}/settings")
def get_property_settings(
    property_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    property_ = db.get(Property, property_id)
    if property_ is None:
        raise HTTPException(status_code=404, detail="Property not found")
    _require_property_access(db, user, property_)
    organization_rows = db.scalars(
        select(OrganizationSetting).where(OrganizationSetting.organization_id == property_.organization_id)
    ).all()
    property_rows = db.scalars(
        select(PropertySetting).where(PropertySetting.property_id == property_id)
    ).all()
    organization_values = {row.setting_key: row.setting_value for row in organization_rows}
    property_values = {row.setting_key: row.setting_value for row in property_rows}
    resolved = resolve_effective_settings(organization_values, property_values)
    return {
        "property_id": property_id,
        **resolved,
        "allowed_keys": sorted(resolved["settings"].keys()),
        "inherited_from_organization": {
            property_key: organization_values[organization_key]
            for organization_key, property_key in ORG_TO_PROPERTY.items()
            if organization_values.get(organization_key) is not None
        },
    }


@router.put("/properties/{property_id}/settings")
def update_property_settings(
    property_id: int,
    payload: SettingsUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
):
    property_ = db.get(Property, property_id)
    if property_ is None:
        raise HTTPException(status_code=404, detail="Property not found")
    _require_property_access(db, user, property_)
    settings = _validate_scope_settings("property", payload.settings)
    changed: list[str] = []
    for key, value in settings.items():
        row = db.scalar(
            select(PropertySetting).where(
                PropertySetting.property_id == property_id,
                PropertySetting.setting_key == key,
            )
        )
        if value is None:
            if row is not None:
                db.delete(row)
                changed.append(key)
        elif row is None:
            db.add(PropertySetting(property_id=property_id, setting_key=key, setting_value=value))
            changed.append(key)
        elif row.setting_value != value:
            row.setting_value = value
            changed.append(key)
    if changed:
        _audit(db, user, property_id, "update", "property_settings", property_id, {"keys": sorted(changed)})
    db.commit()
    return get_property_settings(property_id, db, user)


@router.get("/properties/{property_id}/branding", response_model=BrandingResponse)
def get_property_branding(
    property_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    property_ = db.get(Property, property_id)
    if property_ is None:
        raise HTTPException(status_code=404, detail="Property not found")
    _require_property_access(db, user, property_)
    branding = db.scalar(select(PropertyBranding).where(PropertyBranding.property_id == property_id))
    if branding is None:
        branding = PropertyBranding(property_id=property_id, display_name=property_.name)
        db.add(branding)
        db.commit()
        db.refresh(branding)
    return branding


@router.put("/properties/{property_id}/branding", response_model=BrandingResponse)
def update_property_branding(
    property_id: int,
    payload: BrandingUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
):
    property_ = db.get(Property, property_id)
    if property_ is None:
        raise HTTPException(status_code=404, detail="Property not found")
    _require_property_access(db, user, property_)
    branding = db.scalar(select(PropertyBranding).where(PropertyBranding.property_id == property_id))
    supplied = payload.model_dump(exclude_unset=True)
    if branding is None:
        if not supplied.get("display_name"):
            raise HTTPException(status_code=422, detail="display_name is required when creating branding")
        branding = PropertyBranding(property_id=property_id, display_name=supplied["display_name"])
        db.add(branding)
        before_values: dict[str, Any] = {}
    else:
        before_values = {key: getattr(branding, key) for key in supplied}
    for key, value in supplied.items():
        setattr(branding, key, value)
    after_values = {key: getattr(branding, key) for key in supplied}
    _audit(db, user, property_id, "update", "property_branding", property_id, {"from": before_values, "to": after_values})
    db.commit()
    db.refresh(branding)
    return branding
