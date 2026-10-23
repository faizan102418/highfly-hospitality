"""Release-readiness regressions for front-desk tenant boundaries.

These integration tests run only against the disposable PostgreSQL CI database.
"""
import unittest
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import engine
from app.main import check_in_reservation, check_out_reservation, create_reservation, transfer_room
from app.models import BusinessDateState, Folio, FolioItem, FinancialTransaction, Guest, Payment, Reservation, ReservationRoom, Role, Room, RoomType, User
from app.schemas import ReservationCreate, RoomTransferRequest
from app.housekeeping_control import HousekeepingTaskCreate, create_task, start_task, complete_task
from app.billing import PaymentCreate, FolioItemCreate, add_folio_item, add_payment, get_folio
from app.reservation_workflows import (
    ReservationRoomSetup,
    ReservationWorkflowCreate,
    create_reservation_workflow,
    update_reservation,
    ReservationUpdate,
)
from app.pms_core import Stay
from app.phase_a_workflows import stay_or_404 as authorized_stay_or_404
from app.tenancy import Organization, Property, PropertyUserAccess
from tenant_test_support import ensure_test_property


class FrontDeskReleaseRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if engine.dialect.name != "postgresql":
            raise unittest.SkipTest("HMS_DATABASE_URL is not PostgreSQL")

    def test_synthetic_reservation_payment_checkout_and_housekeeping_flow(self):
        suffix = uuid4().hex[:10]
        with Session(engine) as db:
            property_ = ensure_test_property(db)
            role = db.scalar(select(Role).where(Role.name == "admin"))
            if role is None:
                role = Role(name="admin")
                db.add(role)
                db.flush()
            user = User(username=f"frontdesk-e2e-{suffix}", password_hash="test", role_id=role.id)
            db.add(user)
            db.flush()
            db.add(PropertyUserAccess(
                user_id=user.id,
                property_id=property_.id,
                access_scope="property",
                is_primary=True,
            ))
            if db.scalar(select(BusinessDateState.id).where(BusinessDateState.property_id == property_.id)) is None:
                db.add(BusinessDateState(property_id=property_.id, current_business_date=date.today()))
            guest = Guest(property_id=property_.id, full_name=f"Synthetic E2E {suffix}", phone=f"030{suffix[:8]}")
            room_type = RoomType(property_id=property_.id, name=f"E2E type {suffix}", base_rate=Decimal("100.00"))
            db.add_all([guest, room_type])
            db.flush()
            room = Room(property_id=property_.id, number=f"E2E-{suffix}", room_type_id=room_type.id, status="available")
            db.add(room)
            db.commit()

            reservation = create_reservation(
                ReservationCreate(
                    guest_id=guest.id,
                    check_in=date.today(),
                    check_out=date.today() + timedelta(days=1),
                    room_ids=[room.id],
                ),
                db,
                user,
            )
            reservation_id = reservation.id
            folio_id = reservation.folio_id
            self.assertEqual(reservation.status, "reserved")

            checked_in = check_in_reservation(reservation_id, db, user)
            self.assertEqual(checked_in.status, "checked_in")
            with self.assertRaises(HTTPException) as repeated_checkin:
                check_in_reservation(reservation_id, db, user)
            self.assertEqual(repeated_checkin.exception.status_code, 409)

            charge = add_folio_item(
                folio_id,
                FolioItemCreate(
                    description="Synthetic room service",
                    category="other",
                    quantity=Decimal("1.00"),
                    unit_price=Decimal("100.00"),
                    discount=Decimal("0.00"),
                ),
                db,
                user,
            )
            self.assertEqual(Decimal(charge.line_total), Decimal("100.00"))

            with self.assertRaises(HTTPException) as unsettled_checkout:
                check_out_reservation(reservation_id, db, user)
            self.assertEqual(unsettled_checkout.exception.status_code, 409)
            self.assertEqual(db.get(Reservation, reservation_id).status, "checked_in")
            self.assertEqual(db.get(Folio, folio_id).status, "open")

            payment_payload = PaymentCreate(amount=Decimal("100.00"), method="cash", reference=f"SYN-{suffix}")
            payment = add_payment(folio_id, payment_payload, f"e2e-{suffix}", db, user)
            replay = add_payment(folio_id, payment_payload, f"e2e-{suffix}", db, user)
            self.assertEqual(payment.id, replay.id)
            self.assertEqual(
                db.scalar(select(func.count(Payment.id)).where(Payment.folio_id == folio_id)),
                1,
            )
            summary = get_folio(folio_id, db, user)
            self.assertEqual(Decimal(summary.total), Decimal("100.00"))
            self.assertEqual(Decimal(summary.paid), Decimal("100.00"))
            self.assertEqual(Decimal(summary.balance), Decimal("0.00"))

            checked_out = check_out_reservation(reservation_id, db, user)
            self.assertEqual(checked_out.status, "checked_out")
            self.assertEqual(db.get(Folio, folio_id).status, "closed")
            self.assertEqual(db.get(Room, room.id).status, "dirty")
            with self.assertRaises(HTTPException) as repeated_checkout:
                check_out_reservation(reservation_id, db, user)
            self.assertEqual(repeated_checkout.exception.status_code, 409)
            self.assertEqual(
                db.scalar(select(func.count(Payment.id)).where(Payment.folio_id == folio_id)),
                1,
            )

            task = create_task(
                room.id,
                HousekeepingTaskCreate(task_type="checkout_clean", reason="Synthetic checkout handoff"),
                db,
                user,
            )
            started = start_task(task["id"], db, user)
            self.assertEqual(started["status"], "in_progress")
            completed = complete_task(task["id"], db, user)
            self.assertEqual(completed["status"], "completed")
            self.assertEqual(db.get(Room, room.id).status, "available")

            ledger_transactions = db.scalars(
                select(FinancialTransaction).where(FinancialTransaction.folio_id == folio_id)
            ).all()
            self.assertTrue(ledger_transactions, "charge/payment must post to the authoritative ledger")
            self.assertEqual(
                db.scalar(select(func.count(FolioItem.id)).where(FolioItem.folio_id == folio_id)),
                1,
            )
            db.rollback()

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

            allowed_reservation = Reservation(
                property_id=allowed_property.id,
                guest_id=allowed_guest.id,
                check_in=date(2026, 10, 1),
                check_out=date(2026, 10, 3),
                status="checked_in",
            )
            db.add(allowed_reservation)
            db.flush()
            db.add(ReservationRoom(reservation_id=allowed_reservation.id, room_id=allowed_room.id))
            db.add(Stay(
                reservation_id=allowed_reservation.id,
                room_id=allowed_room.id,
                guest_id=allowed_guest.id,
                status="checked_in",
                check_in=date(2026, 10, 1),
                check_out=date(2026, 10, 3),
                agreed_rate=Decimal("100.00"),
            ))
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
            foreign_stay = Stay(
                reservation_id=foreign_reservation.id,
                room_id=foreign_room.id,
                guest_id=foreign_guest.id,
                status="reserved",
                check_in=date(2026, 10, 1),
                check_out=date(2026, 10, 3),
                agreed_rate=Decimal("100.00"),
            )
            foreign_folio = Folio(reservation_id=foreign_reservation.id, status="open")
            db.add_all([foreign_link, foreign_stay, foreign_folio])
            db.flush()

            reservation_count_before = db.scalar(select(__import__("sqlalchemy").func.count(Reservation.id)))
            denied_calls = (
                ("foreign reservation read/check-in", lambda: check_in_reservation(foreign_reservation.id, db, user), 404),
                ("foreign reservation checkout", lambda: check_out_reservation(foreign_reservation.id, db, user), 403),
                ("foreign stay read", lambda: authorized_stay_or_404(foreign_stay.id, db, user.id), 403),
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
                        allowed_reservation.id,
                        RoomTransferRequest(from_room_id=allowed_room.id, to_room_id=foreign_room.id),
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
