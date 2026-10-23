"""Release-readiness regressions for front-desk tenant boundaries.

These integration tests run only against the disposable PostgreSQL CI database.
"""
import unittest
from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import engine
from app.main import check_in_reservation, check_out_reservation, create_reservation, transfer_room
from app.models import Folio, Guest, Reservation, ReservationRoom, Role, Room, RoomType, User
from app.schemas import ReservationCreate, RoomTransferRequest
from app.billing import PaymentCreate, add_payment, get_folio
from app.reservation_workflows import (
    ReservationRoomSetup,
    ReservationWorkflowCreate,
    create_reservation_workflow,
    update_reservation,
    ReservationUpdate,
)
from app.pms_core import Stay
from app.tenancy import Organization, Property, PropertyUserAccess
from tenant_test_support import ensure_test_property


class FrontDeskReleaseRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if engine.dialect.name != "postgresql":
            raise unittest.SkipTest("HMS_DATABASE_URL is not PostgreSQL")

    def test_cross_property_frontdesk_reads_writes_and_references_are_denied(self):
        suffix = uuid4().hex[:10]
        with Session(engine) as db:
            allowed_property = ensure_test_property(db)
            organization = Organization(
                name=f"Release isolation org {suffix}",
                slug=f"release-isolation-org-{suffix}",
            )
            db.add(organization)
            db.flush()
            other_property = Property(
                organization_id=organization.id,
                name=f"Release isolation property {suffix}",
                code=f"RLS-{suffix}",
                slug=f"release-isolation-property-{suffix}",
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
                username=f"release-isolation-{suffix}",
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

            allowed_guest = Guest(property_id=allowed_property.id, full_name=f"Allowed {suffix}")
            foreign_guest = Guest(property_id=other_property.id, full_name=f"Foreign {suffix}")
            allowed_type = RoomType(property_id=allowed_property.id, name=f"Allowed type {suffix}", base_rate=Decimal("100.00"))
            foreign_type = RoomType(property_id=other_property.id, name=f"Foreign type {suffix}", base_rate=Decimal("100.00"))
            db.add_all([allowed_guest, foreign_guest, allowed_type, foreign_type])
            db.flush()
            allowed_room = Room(property_id=allowed_property.id, number=f"A-{suffix}", room_type_id=allowed_type.id, status="available")
            foreign_room = Room(property_id=other_property.id, number=f"F-{suffix}", room_type_id=foreign_type.id, status="available")
            db.add_all([allowed_room, foreign_room])
            db.flush()

            foreign_reservation = Reservation(
                property_id=other_property.id,
                guest_id=foreign_guest.id,
                check_in=date(2026, 10, 1),
                check_out=date(2026, 10, 3),
                status="reserved",
            )
            db.add(foreign_reservation)
            db.flush()
            foreign_link = ReservationRoom(reservation_id=foreign_reservation.id, room_id=foreign_room.id)
            foreign_folio = Folio(reservation_id=foreign_reservation.id, status="open")
            db.add_all([foreign_link, foreign_folio])
            db.flush()

            reservation_count_before = db.scalar(select(__import__("sqlalchemy").func.count(Reservation.id)))
            denied_calls = (
                ("foreign reservation read/check-in", lambda: check_in_reservation(foreign_reservation.id, db, user), 404),
                ("foreign reservation checkout", lambda: check_out_reservation(foreign_reservation.id, db, user), 404),
                ("foreign folio read", lambda: get_folio(foreign_folio.id, db, user), 404),
                ("foreign folio payment", lambda: add_payment(foreign_folio.id, PaymentCreate(amount=Decimal("1.00"), method="cash"), None, db, user), 404),
                (
                    "foreign guest reference on reservation create",
                    lambda: create_reservation(
                        ReservationCreate(
                            guest_id=foreign_guest.id,
                            check_in=date(2026, 10, 1),
                            check_out=date(2026, 10, 2),
                            room_ids=[allowed_room.id],
                        ),
                        db,
                        user,
                    ),
                    400,
                ),
                (
                    "foreign room reference on reservation create",
                    lambda: create_reservation(
                        ReservationCreate(
                            guest_id=allowed_guest.id,
                            check_in=date(2026, 10, 1),
                            check_out=date(2026, 10, 2),
                            room_ids=[foreign_room.id],
                        ),
                        db,
                        user,
                    ),
                    400,
                ),
                (
                    "foreign occupant reference on workflow create",
                    lambda: create_reservation_workflow(
                        ReservationWorkflowCreate(
                            guest_id=allowed_guest.id,
                            check_in=date(2026, 10, 1),
                            check_out=date(2026, 10, 2),
                            rooms=[ReservationRoomSetup(room_id=allowed_room.id, occupant_guest_id=foreign_guest.id, agreed_rate=Decimal("100.00"))],
                        ),
                        db,
                        user,
                    ),
                    409,
                ),
                (
                    "foreign reservation update",
                    lambda: update_reservation(foreign_reservation.id, ReservationUpdate(notes="cross-tenant"), db, user),
                    403,
                ),
                (
                    "foreign destination room transfer",
                    lambda: transfer_room(
                        foreign_reservation.id,
                        RoomTransferRequest(from_room_id=foreign_room.id, to_room_id=allowed_room.id),
                        db,
                        user,
                    ),
                    404,
                ),
            )
            for label, call, expected_status in denied_calls:
                with self.subTest(action=label):
                    with self.assertRaises(HTTPException) as denied:
                        call()
                    self.assertEqual(denied.exception.status_code, expected_status)

            db.flush()
            self.assertEqual(
                db.scalar(select(__import__("sqlalchemy").func.count(Reservation.id))),
                reservation_count_before,
                "denied front-desk actions must not create reservations",
            )
            self.assertEqual(foreign_reservation.status, "reserved")
            self.assertEqual(foreign_room.status, "available")
            self.assertEqual(
                db.scalar(select(Folio.id).where(Folio.id == foreign_folio.id)),
                foreign_folio.id,
            )
            db.rollback()


if __name__ == "__main__":
    unittest.main()
