"""Idempotently provision an organization/property and grant a user access.

Run from apps/api with the API environment configured:
    python scripts/provision_tenant.py --organization-name "Example Group" \
      --organization-slug example-group --property-name "Example Hotel" \
      --property-code EXAMPLE --property-slug example-hotel \
      --user-username admin --timezone UTC --currency USD

This is an operator command; migrations intentionally do not provision customers.
"""
from __future__ import annotations

import argparse
import re

from sqlalchemy import select

from app.db import SessionLocal
from app.models import User
from app.tenancy import Organization, Property, PropertyUserAccess


def slug(value: str) -> str:
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
        raise argparse.ArgumentTypeError("must be a lowercase URL-safe slug")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--organization-name", required=True)
    parser.add_argument("--organization-slug", required=True, type=slug)
    parser.add_argument("--property-name", required=True)
    parser.add_argument("--property-code", required=True)
    parser.add_argument("--property-slug", required=True, type=slug)
    parser.add_argument("--user-username", required=True, help="Existing user to grant access")
    parser.add_argument("--timezone", default="UTC")
    parser.add_argument("--currency", default="USD")
    args = parser.parse_args()

    if not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", args.property_code):
        parser.error("--property-code must contain only letters, numbers, underscore, or hyphen")
    if not re.fullmatch(r"[A-Za-z]{3}", args.currency):
        parser.error("--currency must be a three-letter ISO currency code")

    with SessionLocal() as db:
        organization = db.scalar(
            select(Organization).where(Organization.slug == args.organization_slug)
        )
        if organization is None:
            organization = Organization(
                name=args.organization_name.strip(),
                slug=args.organization_slug,
            )
            db.add(organization)
            db.flush()
        elif organization.name != args.organization_name.strip():
            raise SystemExit(
                "Organization slug already exists with a different name; refusing to overwrite it."
            )

        property_ = db.scalar(
            select(Property).where(
                Property.organization_id == organization.id,
                Property.slug == args.property_slug,
            )
        )
        if property_ is None:
            property_ = Property(
                organization_id=organization.id,
                name=args.property_name.strip(),
                code=args.property_code,
                slug=args.property_slug,
                timezone=args.timezone,
                currency=args.currency.upper(),
            )
            db.add(property_)
            db.flush()
        elif (
            property_.name != args.property_name.strip()
            or property_.code != args.property_code
            or property_.timezone != args.timezone
            or property_.currency != args.currency.upper()
        ):
            raise SystemExit(
                "Property slug already exists with different configuration; refusing to overwrite it."
            )

        user = db.scalar(select(User).where(User.username == args.user_username))
        if user is None:
            raise SystemExit(
                f"User {args.user_username!r} does not exist. Create the administrator first."
            )

        access = db.scalar(
            select(PropertyUserAccess).where(
                PropertyUserAccess.user_id == user.id,
                PropertyUserAccess.property_id == property_.id,
            )
        )
        if access is None:
            access = PropertyUserAccess(
                user_id=user.id,
                property_id=property_.id,
                access_scope="organization",
                is_primary=True,
            )
            db.add(access)
        else:
            access.access_scope = "organization"
            access.is_primary = True

        db.commit()
        print(
            f"Provisioned organization_id={organization.id}, "
            f"property_id={property_.id}, user_id={user.id}."
        )


if __name__ == "__main__":
    main()
