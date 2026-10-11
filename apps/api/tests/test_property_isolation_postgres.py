import unittest
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import engine
from app.models import Folio, Guest, Reservation, Role, User
from app.billing import get_folio
from datetime import date
from app.tenancy import Organization, Property, PropertyUserAccess, resolve_authorized_property
from tenant_test_support import ensure_test_property


class PropertyIsolationPostgreSQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if engine.dialect.name != "postgresql":
            raise unittest.SkipTest("HMS_DATABASE_URL is not PostgreSQL")

    def test_user_cannot_resolve_an_unassigned_property(self):
        suffix = uuid4().hex[:12]
        with Session(engine) as db:
            allowed_property = ensure_test_property(db)
            organization = Organization(
                name=f"Isolation Org {suffix}",
                slug=f"isolation-org-{suffix}",
            )
            db.add(organization)
            db.flush()
            other_property = Property(
                organization_id=organization.id,
                name=f"Isolation Property {suffix}",
                code=f"ISO-{suffix[:6]}",
                slug=f"isolation-property-{suffix}",
                timezone="UTC",
                currency="PKR",
            )
            db.add(other_property)
            role = db.scalar(select(Role).where(Role.name == "admin"))
            if role is None:
                role = Role(name="admin")
                db.add(role)
                db.flush()
            user = User(
                username=f"ci-isolation-{suffix}",
                password_hash="test",
                role_id=role.id,
            )
            db.add(user)
            db.flush()
            db.add(PropertyUserAccess(
                user_id=user.id,
                property_id=allowed_property.id,
                access_scope="property",
                is_primary=True,
            ))
            db.flush()

            resolved = resolve_authorized_property(db, user.id)
            self.assertEqual(resolved.id, allowed_property.id)
            with self.assertRaises(HTTPException) as denied:
                resolve_authorized_property(db, user.id, other_property.id)
            self.assertEqual(denied.exception.status_code, 403)

            allowed_guest = Guest(property_id=allowed_property.id, full_name=f"Allowed guest {suffix}")
            other_guest = Guest(property_id=other_property.id, full_name=f"Other guest {suffix}")
            db.add_all([allowed_guest, other_guest])
            db.flush()
            allowed_reservation = Reservation(property_id=allowed_property.id, guest_id=allowed_guest.id, check_in=date(2026, 10, 1), check_out=date(2026, 10, 2), status="reserved")
            other_reservation = Reservation(property_id=other_property.id, guest_id=other_guest.id, check_in=date(2026, 10, 1), check_out=date(2026, 10, 2), status="reserved")
            db.add_all([allowed_reservation, other_reservation])
            db.flush()
            allowed_folio = Folio(reservation_id=allowed_reservation.id, status="open")
            other_folio = Folio(reservation_id=other_reservation.id, status="open")
            db.add_all([allowed_folio, other_folio])
            db.flush()

            self.assertEqual(get_folio(allowed_folio.id, db, user).id, allowed_folio.id)
            with self.assertRaises(HTTPException) as folio_denied:
                get_folio(other_folio.id, db, user)
            self.assertEqual(folio_denied.exception.status_code, 404)
            db.rollback()


if __name__ == "__main__":
    unittest.main()
