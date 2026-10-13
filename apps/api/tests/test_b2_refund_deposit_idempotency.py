import unittest
from unittest.mock import patch
from datetime import date, datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from tenant_test_support import ensure_test_property, ensure_test_property_access
from app.db import Base
import app.financial_authority  # noqa: F401
import app.financial_models  # noqa: F401
import app.models  # noqa: F401
import app.pms_core  # noqa: F401
from app.financial_authority import post_folio_charge_authoritative
from app.financial_models import PaymentRefund
from app.financial_ops import RefundCreate, create_deposit_with_ledger, refund_payment
from app.ledger import post_folio_payment, scoped_idempotency_key
from app.models import (
    AuditLog,
    BusinessDateState,
    DepositTransaction,
    FinancialTransaction,
    Folio,
    FolioItem,
    LedgerEntry,
    Guest,
    Payment,
    Reservation,
    ReservationRoom,
    Role,
    Room,
    RoomType,
    User,
)
from app.pms_core import Stay
from app.tenancy import Organization, Property


class PhaseB2RefundDepositIdempotencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    def setUp(self):
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)

        self.property = ensure_test_property(self.db)
        role = Role(name="admin")
        self.db.add(role)
        self.db.flush()
        self.user = User(username="admin", password_hash="test", role_id=role.id)
        guest = Guest(property_id=self.property.id, full_name="Refund Guest")
        room_type = RoomType(property_id=self.property.id, name="Standard", base_rate=100)
        self.db.add_all([self.user, guest, room_type])
        self.db.flush()
        ensure_test_property_access(self.db, self.user.id, self.property.id)

        room = Room(property_id=self.property.id, number="301", room_type_id=room_type.id, status="occupied")
        reservation = Reservation(property_id=self.property.id, 
            guest_id=guest.id,
            check_in=date(2026, 9, 8),
            check_out=date(2026, 9, 10),
            status="checked_in",
        )
        self.db.add_all([room, reservation])
        self.db.flush()
        self.db.add(ReservationRoom(reservation_id=reservation.id, room_id=room.id))

        folio = Folio(reservation_id=reservation.id, status="open")
        self.db.add(folio)
        self.db.add(BusinessDateState(property_id=self.property.id, current_business_date=date(2026, 9, 8), opened_at=datetime(2026, 9, 8, 8, 0)))
        self.db.flush()

        stay = Stay(
            reservation_id=reservation.id,
            room_id=room.id,
            status="in_house",
            check_in=reservation.check_in,
            check_out=reservation.check_out,
            deposit_required=200,
            deposit_received=0,
        )
        item = FolioItem(folio_id=folio.id, description="Room charge", category="room", quantity=1, unit_price=100, discount=0)
        payment = Payment(folio_id=folio.id, amount=100, method="cash")
        self.db.add_all([stay, item, payment])
        self.db.flush()
        post_folio_charge_authoritative(
            self.db,
            folio_id=folio.id,
            reservation_id=reservation.id,
            item_id=item.id,
            amount=Decimal("100.00"),
            stay_id=stay.id,
            category="room",
            created_by=self.user.id,
            gross_amount=Decimal("100.00"),
            discount_amount=Decimal("0.00"),
        )
        post_folio_payment(
            self.db,
            folio_id=folio.id,
            reservation_id=reservation.id,
            payment_id=payment.id,
            amount=Decimal("100.00"),
            method="cash",
            created_by=self.user.id,
        )
        self.db.commit()
        self.db.refresh(folio)
        self.db.refresh(payment)
        self.db.refresh(stay)
        self.folio = folio
        self.payment = payment
        self.stay = stay
        self.reservation = reservation

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def test_refund_is_idempotent_and_same_key_rejects_different_amount(self):
        payload = RefundCreate(
            payment_id=self.payment.id,
            amount=Decimal("40.00"),
            method="cash",
            reference="R-1",
            reason="Guest request",
        )
        first = refund_payment(self.folio.id, payload, "refund-001", self.db, self.user)
        replay = refund_payment(self.folio.id, payload, "refund-001", self.db, self.user)

        self.assertEqual(first["id"], replay["id"])
        self.assertFalse(first["replayed"])
        self.assertTrue(replay["replayed"])
        self.assertEqual(
            self.db.scalar(select(func.count()).select_from(PaymentRefund).where(PaymentRefund.payment_id == self.payment.id)),
            1,
        )
        self.assertEqual(
            self.db.scalar(select(func.count()).select_from(FinancialTransaction).where(FinancialTransaction.idempotency_key == scoped_idempotency_key(self.property.id, "refund-001"))),
            1,
        )

        conflicting = payload.model_copy(update={"amount": Decimal("35.00")})
        with self.assertRaisesRegex(HTTPException, "different refund parameters"):
            refund_payment(self.folio.id, conflicting, "refund-001", self.db, self.user)

    def test_deposit_application_is_idempotent_and_uses_ledger_balance(self):
        received = create_deposit_with_ledger(
            self.stay.id,
            {"transaction_type": "received", "amount": Decimal("100.00"), "payment_method": "cash"},
            None,
            self.db,
            self.user,
        )
        self.assertEqual(received["balance"], Decimal("100.00"))

        self.stay.deposit_received = Decimal("999.00")
        applied = create_deposit_with_ledger(
            self.stay.id,
            {"transaction_type": "applied", "amount": Decimal("40.00"), "reference": "APP-1"},
            "deposit-apply-001",
            self.db,
            self.user,
        )
        replay = create_deposit_with_ledger(
            self.stay.id,
            {"transaction_type": "applied", "amount": Decimal("40.00"), "reference": "APP-1"},
            "deposit-apply-001",
            self.db,
            self.user,
        )

        self.assertEqual(applied["balance"], Decimal("60.00"))
        self.assertEqual(replay["balance"], Decimal("60.00"))
        self.assertFalse(applied["replayed"])
        self.assertTrue(replay["replayed"])
        self.assertIsNotNone(applied["payment_id"])
        self.assertEqual(applied["payment_id"], replay["payment_id"])
        self.assertEqual(
            self.db.scalar(
                select(func.count()).select_from(Payment).where(
                    Payment.folio_id == self.folio.id,
                    Payment.reference == "deposit-apply-001",
                    Payment.method == "deposit",
                )
            ),
            1,
        )
        self.assertEqual(
            self.db.scalar(
                select(func.count()).select_from(FinancialTransaction).where(FinancialTransaction.transaction_type == "deposit_applied")
            ),
            1,
        )
        self.assertEqual(
            self.db.scalar(
                select(func.count()).select_from(DepositTransaction).where(DepositTransaction.reference == "deposit-apply-001")
            ),
            1,
        )


    def test_deposit_receive_replay_is_idempotent(self):
        payload = {"transaction_type": "received", "amount": Decimal("25.00"), "payment_method": "cash", "reference": "RECEIVE-REPLAY"}
        first = create_deposit_with_ledger(self.stay.id, payload, "deposit-receive-001", self.db, self.user)
        replay = create_deposit_with_ledger(self.stay.id, payload, "deposit-receive-001", self.db, self.user)

        self.assertFalse(first["replayed"])
        self.assertTrue(replay["replayed"])
        self.assertEqual(first["id"], replay["id"])
        self.assertEqual(
            self.db.scalar(select(func.count()).select_from(DepositTransaction).where(DepositTransaction.stay_id == self.stay.id, DepositTransaction.transaction_type == "received")),
            1,
        )
        self.assertEqual(
            self.db.scalar(select(func.count()).select_from(FinancialTransaction).where(FinancialTransaction.transaction_type == "deposit_received", FinancialTransaction.reservation_id == self.reservation.id)),
            1,
        )

    def test_deposit_refund_replay_is_idempotent_and_partial_application_replay_is_safe(self):
        receive_payload = {"transaction_type": "received", "amount": Decimal("100.00"), "payment_method": "cash"}
        create_deposit_with_ledger(self.stay.id, receive_payload, "deposit-seed-001", self.db, self.user)

        refund_payload = {"transaction_type": "refunded", "amount": Decimal("20.00"), "payment_method": "cash", "reference": "REFUND-REPLAY"}
        refund_first = create_deposit_with_ledger(self.stay.id, refund_payload, "deposit-refund-001", self.db, self.user)
        refund_replay = create_deposit_with_ledger(self.stay.id, refund_payload, "deposit-refund-001", self.db, self.user)
        self.assertFalse(refund_first["replayed"])
        self.assertTrue(refund_replay["replayed"])
        self.assertEqual(refund_first["id"], refund_replay["id"])

        apply_payload = {"transaction_type": "applied", "amount": Decimal("30.00"), "reference": "APPLY-PARTIAL"}
        apply_first = create_deposit_with_ledger(self.stay.id, apply_payload, "deposit-partial-apply-001", self.db, self.user)
        apply_replay = create_deposit_with_ledger(self.stay.id, apply_payload, "deposit-partial-apply-001", self.db, self.user)
        self.assertFalse(apply_first["replayed"])
        self.assertTrue(apply_replay["replayed"])
        self.assertEqual(apply_first["id"], apply_replay["id"])
        self.assertEqual(apply_first["balance"], Decimal("50.00"))
        self.assertEqual(apply_replay["balance"], Decimal("50.00"))

        for transaction_type, expected in (("deposit_received", 1), ("deposit_refund", 1), ("deposit_applied", 1)):
            self.assertEqual(
                self.db.scalar(select(func.count()).select_from(FinancialTransaction).where(FinancialTransaction.transaction_type == transaction_type, FinancialTransaction.reservation_id == self.reservation.id)),
                expected,
            )
        self.assertEqual(
            self.db.scalar(select(func.count()).select_from(DepositTransaction).where(DepositTransaction.stay_id == self.stay.id)),
            3,
        )

    def test_deposit_idempotency_key_rejects_replay_with_changed_amount(self):
        payload = {"transaction_type": "received", "amount": Decimal("25.00"), "payment_method": "cash"}
        create_deposit_with_ledger(self.stay.id, payload, "deposit-receive-conflict-001", self.db, self.user)
        with self.assertRaisesRegex(HTTPException, "different deposit parameters"):
            create_deposit_with_ledger(
                self.stay.id,
                {"transaction_type": "received", "amount": Decimal("26.00"), "payment_method": "cash"},
                "deposit-receive-conflict-001",
                self.db,
                self.user,
            )


    def test_ledger_posting_failure_rolls_back_canonical_deposit_receive(self):
        before = {
            "deposits": self.db.scalar(select(func.count()).select_from(DepositTransaction)),
            "financial": self.db.scalar(select(func.count()).select_from(FinancialTransaction)),
            "ledger": self.db.scalar(select(func.count()).select_from(LedgerEntry)),
            "audit": self.db.scalar(select(func.count()).select_from(AuditLog)),
        }
        with patch("app.financial_ops.post_deposit_received", side_effect=RuntimeError("simulated ledger outage")):
            with self.assertRaisesRegex(RuntimeError, "simulated ledger outage"):
                create_deposit_with_ledger(
                    self.stay.id,
                    {"transaction_type": "received", "amount": Decimal("25.00"), "payment_method": "cash"},
                    "deposit-rollback-001",
                    self.db,
                    self.user,
                )
        self.db.rollback()
        self.assertEqual(self.db.scalar(select(func.count()).select_from(DepositTransaction)), before["deposits"])
        self.assertEqual(self.db.scalar(select(func.count()).select_from(FinancialTransaction)), before["financial"])
        self.assertEqual(self.db.scalar(select(func.count()).select_from(LedgerEntry)), before["ledger"])
        self.assertEqual(self.db.scalar(select(func.count()).select_from(AuditLog)), before["audit"])

    def test_cross_property_deposit_request_is_denied_without_writes(self):
        organization = Organization(name="Isolated Organization", slug="isolated-org")
        self.db.add(organization)
        self.db.flush()
        other_property = Property(
            organization_id=organization.id,
            name="Isolated Property",
            code="ISO",
            slug="isolated-property",
            timezone="UTC",
            currency="PKR",
        )
        self.db.add(other_property)
        self.db.flush()
        other_guest = Guest(property_id=other_property.id, full_name="Other Property Guest")
        other_room_type = RoomType(property_id=other_property.id, name="Other Standard", base_rate=100)
        self.db.add_all([other_guest, other_room_type])
        self.db.flush()
        other_room = Room(property_id=other_property.id, number="ISO-1", room_type_id=other_room_type.id, status="occupied")
        other_reservation = Reservation(
            property_id=other_property.id,
            guest_id=other_guest.id,
            check_in=date(2026, 9, 8),
            check_out=date(2026, 9, 10),
            status="checked_in",
        )
        self.db.add_all([other_room, other_reservation])
        self.db.flush()
        other_stay = Stay(
            reservation_id=other_reservation.id,
            room_id=other_room.id,
            status="checked_in",
            check_in=other_reservation.check_in,
            check_out=other_reservation.check_out,
            deposit_required=Decimal("200.00"),
            deposit_received=Decimal("0.00"),
        )
        self.db.add(other_stay)
        self.db.commit()

        before = (
            self.db.scalar(select(func.count()).select_from(DepositTransaction)),
            self.db.scalar(select(func.count()).select_from(FinancialTransaction)),
            self.db.scalar(select(func.count()).select_from(LedgerEntry)),
            self.db.scalar(select(func.count()).select_from(AuditLog)),
        )
        with self.assertRaises(HTTPException) as ctx:
            create_deposit_with_ledger(
                other_stay.id,
                {"transaction_type": "received", "amount": Decimal("25.00"), "payment_method": "cash"},
                "cross-property-deposit-001",
                self.db,
                self.user,
            )
        self.assertIn(ctx.exception.status_code, (403, 404))
        self.db.rollback()
        after = (
            self.db.scalar(select(func.count()).select_from(DepositTransaction)),
            self.db.scalar(select(func.count()).select_from(FinancialTransaction)),
            self.db.scalar(select(func.count()).select_from(LedgerEntry)),
            self.db.scalar(select(func.count()).select_from(AuditLog)),
        )
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
