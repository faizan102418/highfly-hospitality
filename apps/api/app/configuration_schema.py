"""Typed setting registry and deterministic organization -> property inheritance.

Persisted values remain strings for compatibility with the existing schema.
Validators normalize accepted values before persistence.
"""
import re
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ORG_TO_PROPERTY = {
    "default_language": "language",
    "default_date_format": "date_format",
    "default_time_format": "time_format",
    "default_check_in_time": "check_in_time",
    "default_check_out_time": "check_out_time",
    "default_cancellation_hours": "cancellation_hours",
    "default_tax_rate_percent": "tax_rate_percent",
    "default_service_charge_percent": "service_charge_percent",
    "default_discount_approval_threshold": "discount_approval_threshold",
}

PLATFORM_DEFAULTS = {
    "language": "en",
    "date_format": "ISO",
    "time_format": "24h",
    "timezone": "Asia/Karachi",
    "currency": "PKR",
    "check_in_time": "14:00",
    "check_out_time": "12:00",
    "cancellation_hours": "24",
    "tax_rate_percent": "0",
    "service_charge_percent": "0",
    "discount_approval_threshold": "0",
    "enabled_modules": "front_desk,finance,reporting",
    "housekeeping_workflow": "standard",
    "billing_rounding": "two_decimals",
}

ORGANIZATION_KEYS = frozenset(ORG_TO_PROPERTY)
PROPERTY_KEYS = frozenset(PLATFORM_DEFAULTS)


def _enum(value: str, choices: set[str], key: str) -> str:
    normalized = value.strip()
    if normalized not in choices:
        raise ValueError(f"{key} must be one of: {', '.join(sorted(choices))}")
    return normalized


def _time(value: str, key: str) -> str:
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value.strip()):
        raise ValueError(f"{key} must use 24-hour HH:MM format")
    return value.strip()


def _integer(value: str, key: str, minimum: int, maximum: int) -> str:
    raw = value.strip()
    if not re.fullmatch(r"\d+", raw):
        raise ValueError(f"{key} must be an integer")
    parsed = int(raw)
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return str(parsed)


def _decimal(value: str, key: str, minimum: Decimal, maximum: Decimal | None = None) -> str:
    raw = value.strip()
    try:
        parsed = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"{key} must be a decimal number") from exc
    if not parsed.is_finite() or parsed < minimum or (maximum is not None and parsed > maximum):
        if maximum is None:
            raise ValueError(f"{key} must be at least {minimum}")
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return format(parsed.normalize(), "f")


def validate_setting(scope: str, key: str, value: str) -> str:
    """Validate and normalize a registered setting for its owning scope."""
    allowed = ORGANIZATION_KEYS if scope == "organization" else PROPERTY_KEYS if scope == "property" else frozenset()
    if key not in allowed:
        raise ValueError(f"Unknown {scope} setting: {key}")
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")

    if key.endswith("language") or key == "language":
        return _enum(value, {"en", "ur"}, key)
    if key.endswith("date_format") or key == "date_format":
        return _enum(value, {"ISO", "DMY", "MDY"}, key)
    if key.endswith("time_format") or key == "time_format":
        return _enum(value, {"12h", "24h"}, key)
    if key.endswith("check_in_time") or key.endswith("check_out_time") or key in {"check_in_time", "check_out_time"}:
        return _time(value, key)
    if key.endswith("cancellation_hours") or key == "cancellation_hours":
        return _integer(value, key, 0, 8760)
    if key.endswith("tax_rate_percent") or key.endswith("service_charge_percent") or key in {"tax_rate_percent", "service_charge_percent"}:
        return _decimal(value, key, Decimal("0"), Decimal("100"))
    if key.endswith("discount_approval_threshold") or key == "discount_approval_threshold":
        return _decimal(value, key, Decimal("0"))
    if key == "timezone":
        zone = value.strip()
        try:
            ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return zone
    if key == "currency":
        currency = value.strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise ValueError("currency must be a three-letter ISO-style code")
        return currency
    if key == "enabled_modules":
        modules = [item.strip() for item in value.split(",") if item.strip()]
        valid = {"front_desk", "housekeeping", "restaurant", "inventory", "finance", "reporting"}
        if not modules or any(item not in valid for item in modules):
            raise ValueError(f"enabled_modules must be a comma-separated list from: {', '.join(sorted(valid))}")
        return ",".join(sorted(set(modules)))
    if key == "housekeeping_workflow":
        return _enum(value, {"standard", "inspection_required"}, key)
    if key == "billing_rounding":
        return _enum(value, {"none", "whole", "two_decimals"}, key)
    raise ValueError(f"No validator registered for {key}")


def resolve_effective_settings(organization_values: dict[str, str | None], property_values: dict[str, str | None]) -> dict:
    """Return effective values, explicit overrides, and the winning source per key."""
    org_defaults = {
        property_key: organization_values[organization_key]
        for organization_key, property_key in ORG_TO_PROPERTY.items()
        if organization_values.get(organization_key) is not None
    }
    effective = {}
    sources = {}
    for key, platform_value in PLATFORM_DEFAULTS.items():
        if property_values.get(key) is not None:
            effective[key] = property_values[key]
            sources[key] = "property"
        elif key in org_defaults:
            effective[key] = org_defaults[key]
            sources[key] = "organization"
        else:
            effective[key] = platform_value
            sources[key] = "platform"
    return {
        "settings": effective,
        "overrides": {key: value for key, value in property_values.items() if value is not None},
        "sources": sources,
    }
