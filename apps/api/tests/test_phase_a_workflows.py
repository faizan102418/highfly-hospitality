import unittest
from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from tenant_test_support import ensure_test_property, ensure_test_property_access
from app.db import Base
import app.models  # noqa: F401
import app.pms_core  # noqa: F401
from app.main import app
from app.models import AuditLog, BusinessDateState, DepositTransaction, FinancialTransaction, Folio, Guest, LedgerEntry, Payment, Reservation, ReservationRoom, Role, Room, RoomMove, RoomType, StayOccupant, StayRateSegment, User
from app.phase_a_workflows import (
    DepositApply,
    DepositRequest,
    DepositTransfer,
    MoveRoomRequest,
    OccupantCreate,
    ReservationSplitRequest,
    add_stay_occupant,
    apply_deposit,
    move_checked_in_stay,
    receive_deposit,
    refund_deposit,
    split_reservation,
    transfer_deposit,
)
from app.pms_core import Stay
from app.tenancy import Organization, Property


class PhaseAWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    def setUp(self):
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)
        self.property = ensure_test_property(self.db)
        self.db.add(BusinessDateState(property_id=self.property.id, current_business_date=date(2026, 9, 9)))
        self.db.flush()
        role = Role(name="reception")
        self.db.add(role); self.db.flush()
        self.user = User(username="reception", password_hash="test", role_id=role.id)
        self.booking_guest = Guest(property_id=self.property.id, full_name="Booking Guest")
        self.occupant_a = Guest(property_id=self.property.id, full_name="Ahmed")
        self.occupant_b = Guest(property_id=self.property.id, full_name="Bilal")
        self.occupant_c = Guest(property_id=self.property.id, full_name="Usman")
        rt = RoomType(property_id=self.property.id, name="Standard", base_rate=12000)
        self.room1 = Room(property_id=self.property.id, number="101", room_type_id=1, status="available")
        self.room2 = Room(property_id=self.property.id, number="102", room_type_id=1, status="available")
        self.room3 = Room(property_id=self.property.id, number="103", room_type_id=1, status="available")
        self.db.add_all([self.user, self.booking_guest, self.occupant_a, self.occupant_b, self.occupant_c, rt]); self.db.flush()
        ensure_test_property_access(self.db, self.user.id, self.property.id)
        for room in (self.room1, self.room2, self.room3): room.room_type_id = rt.id
        self.db.add_all([self.room1, self.room2, self.room3]); self.db.commit()

    def tearDown(self):
        self.db.rollback(); self.db.close()

    def make_other_property(self):
        organization = Organization(name="Other Organization", slug="other-org")
        self.db.add(organization)
        self.db.flush()
        property_ = Property(
            organization_id=organization.id,
            name="Other Property",
            code="OTHER",
            slug="other-property",
            timezone="UTC",
            currency="PKR",
        )
        self.db.add(property_)
        self.db.flush()
        return property_

    def make_reservation(self, status="reserved", check_in=date(2026, 9, 8), check_out=date(2026, 9, 13), rooms=None):
        rooms = rooms or [self.room1]
        reservation = Reservation(property_id=self.property.id, guest_id=self.booking_guest.id, check_in=check_in, check_out=check_out, status=status)
        self.db.add(reservation); self.db.flush()
        self.db.add(Folio(reservation_id=reservation.id, status="open"))
        for room in rooms:
            self.db.add(ReservationRoom(reservation_id=reservation.id, room_id=room.id))
        self.db.flush()
        return reservation

    def make_stay(self, reservation, room, guest_id=None, status=None):
        stay = Stay(
            reservation_id=reservation.id,
            room_id=room.id,
            guest_id=guest_id or reservation.guest_id,
            status=status or reservation.status,
            check_in=reservation.check_in,
            check_out=reservation.check_out,
            agreed_rate=Decimal("12000.00"),
        )
        self.db.add(stay); self.db.flush(); return stay

    def test_sharing_adds_second_occupant_without_duplicate_reservation(self):
        reservation = self.make_reservation()
        stay = self.make_stay(reservation, self.room1, guest_id=self.occupant_a.id)
        result = add_stay_occupant(stay.id, OccupantCreate(guest_id=self.occupant_b.id), self.db, self.user)
        occupants = self.db.scalars(select(StayOccupant).where(StayOccupant.stay_id == stay.id).order_by(StayOccupant.id)).all()
        self.assertEqual(result["guest_id"], self.occupant_b.id)
        self.assertEqual(len(occupants), 1)
        self.assertEqual(occupants[0].guest_id, self.occupant_b.id)
        self.assertEqual(self.db.query(Reservation).count(), 1)

    def test_deposit_lifecycle_receive_refund_apply(self):
        reservation = self.make_reservation()
        stay = self.make_stay(reservation, self.room1)
        received = receive_deposit(stay.id, DepositRequest(amount=Decimal("5000"), payment_method="cash", reference="DEP-1"), self.db, self.user)
        self.assertEqual(received["balance"], Decimal("5000.00"))
        applied = apply_deposit(stay.id, DepositApply(amount=Decimal("2000")), self.db, self.user)
        self.assertEqual(applied["balance"], Decimal("3000.00"))
        refunded = refund_deposit(stay.id, DepositRequest(amount=Decimal("1000"), payment_method="cash"), self.db, self.user)
        self.assertEqual(refunded["balance"], Decimal("2000.00"))
        with self.assertRaises(HTTPException) as ctx:
            refund_deposit(stay.id, DepositRequest(amount=Decimal("2001"), payment_method="cash"), self.db, self.user)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(self.db.query(DepositTransaction).count(), 3)

    def ledger_totals(self, transaction_id):
        entries = self.db.scalars(select(LedgerEntry).where(LedgerEntry.transaction_id == transaction_id)).all()
        debits = sum((Decimal(entry.amount) for entry in entries if entry.direction == "debit"), Decimal("0.00"))
        credits = sum((Decimal(entry.amount) for entry in entries if entry.direction == "credit"), Decimal("0.00"))
        return entries, debits, credits

    def assert_deposit_ledger_balanced(self, transaction_type, amount, stay_id):
        transactions = self.db.scalars(
            select(FinancialTransaction).where(FinancialTransaction.transaction_type == transaction_type)
        ).all()
        self.assertTrue(transactions, f"expected {transaction_type} financial transaction")
        financial = transactions[-1]
        entries, debits, credits = self.ledger_totals(financial.id)
        self.assertEqual(len(entries), 2)
        self.assertEqual(debits, Decimal(amount))
        self.assertEqual(credits, Decimal(amount))
        self.assertEqual(debits, credits)
        self.assertTrue(all(entry.stay_id == stay_id for entry in entries))
        return entries

    def test_deposit_lifecycle_posts_balanced_ledger_and_folio_payment(self):
        reservation = self.make_reservation()
        stay = self.make_stay(reservation, self.room1)

        received = receive_deposit(
            stay.id, DepositRequest(amount=Decimal("5000"), payment_method="cash", reference="DEP-LEDGER-1"), self.db, self.user
        )
        received_entries = self.assert_deposit_ledger_balanced("deposit_received", "5000.00", stay.id)
        self.assertEqual({(e.account, e.direction) for e in received_entries}, {
            ("Cash", "debit"), ("Guest Deposits", "credit")
        })

        applied = apply_deposit(stay.id, DepositApply(amount=Decimal("2000")), self.db, self.user)
        applied_entries = self.assert_deposit_ledger_balanced("deposit_applied", "2000.00", stay.id)
        self.assertEqual({(e.account, e.direction) for e in applied_entries}, {
            ("Guest Deposits", "debit"), ("Guest Receivables", "credit")
        })
        payment = self.db.get(Payment, applied["payment_id"])
        self.assertIsNotNone(payment)
        self.assertEqual(payment.folio_id, applied["folio_id"])
        self.assertEqual(payment.amount, Decimal("2000.00"))
        self.assertEqual(payment.method, "deposit")
        self.assertEqual(payment.reference, f"DEPOSIT-{applied['id']}")

        refunded = refund_deposit(
            stay.id, DepositRequest(amount=Decimal("1000"), payment_method="cash", reference="DEP-REFUND-1"), self.db, self.user
        )
        refunded_entries = self.assert_deposit_ledger_balanced("deposit_refund", "1000.00", stay.id)
        self.assertEqual({(e.account, e.direction) for e in refunded_entries}, {
            ("Guest Deposits", "debit"), ("Cash", "credit")
        })
        self.assertEqual(received["balance"], Decimal("5000.00"))
        self.assertEqual(applied["balance"], Decimal("3000.00"))
        self.assertEqual(refunded["balance"], Decimal("2000.00"))
        self.assertEqual(self.db.query(AuditLog).filter(AuditLog.action.in_([
            "deposit_receive", "deposit_apply", "deposit_refund"
        ])).count(), 3)

    def test_deposit_ledger_failure_rolls_back_deposit_payment_and_audit(self):
        from unittest.mock import patch

        reservation = self.make_reservation()
        stay = self.make_stay(reservation, self.room1)
        before = {
            "deposits": self.db.query(DepositTransaction).count(),
            "financial": self.db.query(FinancialTransaction).count(),
            "ledger": self.db.query(LedgerEntry).count(),
            "payments": self.db.query(Payment).count(),
            "audit": self.db.query(AuditLog).count(),
        }
        with patch("app.phase_a_workflows.post_transaction", side_effect=RuntimeError("simulated ledger failure")):
            with self.assertRaises(RuntimeError):
                receive_deposit(
                    stay.id, DepositRequest(amount=Decimal("1750"), payment_method="cash", reference="ROLLBACK-DEP"), self.db, self.user
                )
        self.db.rollback()
        self.assertEqual(self.db.query(DepositTransaction).count(), before["deposits"])
        self.assertEqual(self.db.query(FinancialTransaction).count(), before["financial"])
        self.assertEqual(self.db.query(LedgerEntry).count(), before["ledger"])
        self.assertEqual(self.db.query(Payment).count(), before["payments"])
        self.assertEqual(self.db.query(AuditLog).count(), before["audit"])

    def test_deposit_endpoints_deny_other_property_without_writes(self):
        other_property = self.make_other_property()
        other_guest = Guest(property_id=other_property.id, full_name="Other Booking Guest")
        other_type = RoomType(property_id=other_property.id, name="Other Deposit Type", base_rate=12000)
        self.db.add_all([other_guest, other_type])
        self.db.flush()
        other_room = Room(property_id=other_property.id, number="OTHER-DEP-101", room_type_id=other_type.id, status="available")
        self.db.add(other_room)
        self.db.flush()
        foreign_reservation = Reservation(
            property_id=other_property.id, guest_id=other_guest.id, check_in=date(2026, 9, 8),
            check_out=date(2026, 9, 13), status="reserved"
        )
        self.db.add(foreign_reservation)
        self.db.flush()
        self.db.add(Folio(reservation_id=foreign_reservation.id, status="open"))
        self.db.flush()
        foreign_stay = Stay(
            reservation_id=foreign_reservation.id, room_id=other_room.id, guest_id=other_guest.id,
            status="reserved", check_in=foreign_reservation.check_in, check_out=foreign_reservation.check_out,
            agreed_rate=Decimal("12000.00")
        )
        self.db.add(foreign_stay)
        self.db.commit()
        before = (
            self.db.query(DepositTransaction).count(), self.db.query(FinancialTransaction).count(),
            self.db.query(LedgerEntry).count(), self.db.query(Payment).count(), self.db.query(AuditLog).count()
        )
        operations = (
            lambda: receive_deposit(foreign_stay.id, DepositRequest(amount=Decimal("1000"), reference="FOREIGN"), self.db, self.user),
            lambda: refund_deposit(foreign_stay.id, DepositRequest(amount=Decimal("1")), self.db, self.user),
            lambda: apply_deposit(foreign_stay.id, DepositApply(amount=Decimal("1")), self.db, self.user),
        )
        for operation in operations:
            with self.subTest(operation=operation), self.assertRaises(HTTPException) as ctx:
                operation()
            self.assertIn(ctx.exception.status_code, (403, 404))
            self.db.rollback()
        after = (
            self.db.query(DepositTransaction).count(), self.db.query(FinancialTransaction).count(),
            self.db.query(LedgerEntry).count(), self.db.query(Payment).count(), self.db.query(AuditLog).count()
        )
        self.assertEqual(after, before)

    def test_duplicate_full_balance_application_is_rejected_without_extra_postings(self):
        reservation = self.make_reservation()
        stay = self.make_stay(reservation, self.room1)
        receive_deposit(stay.id, DepositRequest(amount=Decimal("1000"), payment_method="cash", reference="DEP-REPLAY"), self.db, self.user)
        first = apply_deposit(stay.id, DepositApply(amount=Decimal("1000")), self.db, self.user)
        before = (
            self.db.query(DepositTransaction).count(), self.db.query(FinancialTransaction).count(),
            self.db.query(LedgerEntry).count(), self.db.query(Payment).count(), self.db.query(AuditLog).count()
        )
        with self.assertRaises(HTTPException) as ctx:
            apply_deposit(stay.id, DepositApply(amount=Decimal("1000")), self.db, self.user)
        self.assertEqual(ctx.exception.status_code, 409)
        after = (
            self.db.query(DepositTransaction).count(), self.db.query(FinancialTransaction).count(),
            self.db.query(LedgerEntry).count(), self.db.query(Payment).count(), self.db.query(AuditLog).count()
        )
        self.assertEqual(after, before)
        self.assertEqual(self.db.get(Payment, first["payment_id"]).amount, Decimal("1000.00"))

    def test_deposit_transfer_moves_balance_between_reservations(self):
        source_reservation = self.make_reservation(); source_stay = self.make_stay(source_reservation, self.room1)
        target_reservation = self.make_reservation(check_in=date(2026, 9, 10), check_out=date(2026, 9, 12), rooms=[self.room2]); target_stay = self.make_stay(target_reservation, self.room2)
        receive_deposit(source_stay.id, DepositRequest(amount=Decimal("4500"), payment_method="card"), self.db, self.user)
        result = transfer_deposit(source_stay.id, DepositTransfer(target_stay_id=target_stay.id, amount=Decimal("1500")), self.db, self.user)
        self.assertEqual(result["source_balance"], Decimal("3000.00"))
        self.assertEqual(result["target_balance"], Decimal("1500.00"))
        self.assertEqual(self.db.query(DepositTransaction).count(), 3)

    def test_room_move_records_history_and_preserves_single_stay(self):
        reservation = self.make_reservation(status="checked_in")
        stay = self.make_stay(reservation, self.room1, status="checked_in")
        self.room1.status = "occupied"
        result = move_checked_in_stay(stay.id, MoveRoomRequest(to_room_id=self.room2.id, reason="Guest requested quieter room"), self.db, self.user)
        self.assertEqual(result["to_room_id"], self.room2.id)
        self.assertEqual(self.db.get(Stay, stay.id).room_id, self.room2.id)
        self.assertEqual(self.db.get(Room, self.room1.id).status, "dirty")
        self.assertEqual(self.db.get(Room, self.room2.id).status, "occupied")
        self.assertEqual(self.db.query(RoomMove).count(), 1)
        self.assertEqual(self.db.query(Reservation).count(), 1)

    def test_room_move_rejects_occupied_destination(self):
        reservation = self.make_reservation(status="checked_in")
        stay = self.make_stay(reservation, self.room1, status="checked_in")
        self.room1.status = "occupied"
        other_reservation = self.make_reservation(status="checked_in", rooms=[self.room2])
        self.make_stay(other_reservation, self.room2, status="checked_in")
        self.room2.status = "occupied"
        with self.assertRaises(HTTPException) as ctx:
            move_checked_in_stay(stay.id, MoveRoomRequest(to_room_id=self.room2.id), self.db, self.user)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_reservation_split_separates_room_and_clips_stay_data(self):
        reservation = self.make_reservation(check_in=date(2026, 9, 8), check_out=date(2026, 9, 15), rooms=[self.room1, self.room2])
        stay1 = self.make_stay(reservation, self.room1, guest_id=self.occupant_a.id)
        stay2 = self.make_stay(reservation, self.room2, guest_id=self.occupant_b.id)
        self.db.add_all([
            StayOccupant(stay_id=stay2.id, guest_id=self.occupant_b.id, is_primary=True, check_in=date(2026, 9, 8), check_out=date(2026, 9, 15)),
            StayRateSegment(stay_id=stay2.id, from_date=date(2026, 9, 8), to_date=date(2026, 9, 10), rate=Decimal("12000")),
            StayRateSegment(stay_id=stay2.id, from_date=date(2026, 9, 10), to_date=date(2026, 9, 15), rate=Decimal("15000")),
        ])
        self.db.commit()
        result = split_reservation(reservation.id, ReservationSplitRequest(to_date=date(2026, 9, 11), room_stay_ids=[stay2.id], reason="Corporate room split"), self.db, self.user)
        new_reservation_id = result["new_reservation_id"]
        new_stay = self.db.scalar(select(Stay).where(Stay.reservation_id == new_reservation_id))
        source_stay = self.db.get(Stay, stay2.id)
        self.assertEqual(source_stay.check_in, date(2026, 9, 8))
        self.assertEqual(source_stay.check_out, date(2026, 9, 11))
        self.assertEqual(new_stay.check_in, date(2026, 9, 11))
        self.assertEqual(new_stay.check_out, date(2026, 9, 15))
        self.assertIsNotNone(self.db.get(ReservationRoom, {"reservation_id": reservation.id, "room_id": self.room1.id}))
        self.assertIsNotNone(self.db.get(ReservationRoom, {"reservation_id": new_reservation_id, "room_id": self.room2.id}))
        source_segments = self.db.scalars(select(StayRateSegment).where(StayRateSegment.stay_id == stay2.id)).all()
        new_segments = self.db.scalars(select(StayRateSegment).where(StayRateSegment.stay_id == new_stay.id)).all()
        self.assertTrue(all(segment.to_date <= date(2026, 9, 11) for segment in source_segments))
        self.assertTrue(any(segment.from_date == date(2026, 9, 11) and segment.to_date == date(2026, 9, 15) for segment in new_segments))
        self.assertTrue(any(item.guest_id == self.occupant_b.id for item in self.db.scalars(select(StayOccupant).where(StayOccupant.stay_id == new_stay.id)).all()))

    def test_split_rejects_checked_in_reservation(self):
        reservation = self.make_reservation(status="checked_in")
        stay = self.make_stay(reservation, self.room1, status="checked_in")
        with self.assertRaises(HTTPException) as ctx:
            split_reservation(reservation.id, ReservationSplitRequest(to_date=date(2026, 9, 10), room_stay_ids=[stay.id]), self.db, self.user)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_add_occupant_rejects_guest_from_other_property(self):
        other_property = self.make_other_property()
        other_guest = Guest(property_id=other_property.id, full_name="Foreign Guest")
        self.db.add(other_guest)
        self.db.flush()
        reservation = self.make_reservation()
        stay = self.make_stay(reservation, self.room1)
        with self.assertRaises(HTTPException) as ctx:
            add_stay_occupant(stay.id, OccupantCreate(guest_id=other_guest.id), self.db, self.user)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(self.db.query(StayOccupant).count(), 0)

    def test_room_move_rejects_destination_room_from_other_property(self):
        other_property = self.make_other_property()
        other_type = RoomType(property_id=other_property.id, name="Other Standard", base_rate=12000)
        self.db.add(other_type)
        self.db.flush()
        other_room = Room(property_id=other_property.id, number="OTHER-101", room_type_id=other_type.id, status="available")
        self.db.add(other_room)
        reservation = self.make_reservation(status="checked_in")
        stay = self.make_stay(reservation, self.room1, status="checked_in")
        self.room1.status = "occupied"
        self.db.flush()
        with self.assertRaises(HTTPException) as ctx:
            move_checked_in_stay(stay.id, MoveRoomRequest(to_room_id=other_room.id), self.db, self.user)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(self.db.get(Stay, stay.id).room_id, self.room1.id)
        self.assertEqual(self.db.query(RoomMove).count(), 0)

    def test_reservation_split_rejects_unassigned_property(self):
        other_property = self.make_other_property()
        other_guest = Guest(property_id=other_property.id, full_name="Other Booking Guest")
        other_type = RoomType(property_id=other_property.id, name="Other Split Type", base_rate=12000)
        self.db.add_all([other_guest, other_type])
        self.db.flush()
        other_room = Room(property_id=other_property.id, number="OTHER-201", room_type_id=other_type.id, status="reserved")
        reservation = Reservation(property_id=other_property.id, guest_id=other_guest.id, check_in=date(2026, 9, 8), check_out=date(2026, 9, 13), status="reserved")
        self.db.add_all([other_room, reservation])
        self.db.flush()
        stay = Stay(reservation_id=reservation.id, room_id=other_room.id, guest_id=other_guest.id, status="reserved", check_in=reservation.check_in, check_out=reservation.check_out, agreed_rate=Decimal("12000.00"))
        self.db.add(stay)
        self.db.flush()
        reservations_before = self.db.query(Reservation).count()
        with self.assertRaises(HTTPException) as ctx:
            split_reservation(reservation.id, ReservationSplitRequest(to_date=date(2026, 9, 10), room_stay_ids=[stay.id]), self.db, self.user)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(self.db.query(Reservation).count(), reservations_before)

    def test_phase_a_routes_are_mounted(self):
        paths = app.openapi().get("paths", {})
        self.assertTrue(any(path.endswith("/stays/{stay_id}/occupants") for path in paths))
        self.assertTrue(any(path.endswith("/stays/{stay_id}/deposits") for path in paths))
        self.assertTrue(any(path.endswith("/stays/{stay_id}/move") for path in paths))
        self.assertTrue(any(path.endswith("/reservations/{reservation_id}/split") for path in paths))
        self.assertFalse(any(path.endswith("/stays/{stay_id}/deposits/receive") for path in paths))


if __name__ == "__main__":
    unittest.main()
