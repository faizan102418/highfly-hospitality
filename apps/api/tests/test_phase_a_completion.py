import unittest
from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, select
from fastapi import HTTPException
from sqlalchemy.orm import Session

from tenant_test_support import ensure_test_property, ensure_test_property_access
from app.db import Base
from app.ledger import post_deposit_received
from app.financial_ops import create_deposit_with_ledger
from app.billing import add_folio_item, add_payment
from app.front_desk import atomic_checkout, post_accrued_room_charges
from app.reports import report_summary
from app.schemas import FolioItemCreate, PaymentCreate
from app.models import AuditLog, BusinessDateState, DepositTransaction, FinancialTransaction, Folio, FolioItem, Guest, LedgerEntry, Payment, Reservation, ReservationRoom, Role, Room, RoomType, StayOccupant, User
from app.phase_a_completion import (
    DepositApplyCreate,
    DepositRefundCreate,
    DepositTransferCreate,
    FolioItemRouteCreate,
    FolioItemRouting,
    FolioWindowUpdatePayload,
    OccupantGuestChange,
    StayCheckInPayload,
    apply_deposit,
    change_stay_occupant_guest,
    check_in_stay,
    refund_deposit,
    route_folio_item,
    share_stay_with_occupant,
    transfer_deposit,
    update_folio_window,
)
from app.pms_core import Stay
from app.stay_lifecycle import StayFolioWindow
from app.tenancy import Organization, Property


class PhaseACompletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=cls.engine)

    def setUp(self):
        self.db = Session(self.engine)
        self.property = ensure_test_property(self.db)
        role = Role(name=f"phase-a-{id(self)}")
        self.db.add(role)
        self.db.flush()
        self.user = User(username=f"phase-a-{id(self)}", password_hash="test", role_id=role.id)
        self.db.add(self.user)
        self.db.flush()
        ensure_test_property_access(self.db, self.user.id, self.property.id)

        guests = [Guest(property_id=self.property.id, full_name="Booking Guest"), Guest(property_id=self.property.id, full_name="Ahmed"), Guest(property_id=self.property.id, full_name="Bilal"), Guest(property_id=self.property.id, full_name="Usman")]
        self.db.add_all(guests)
        self.db.flush()
        room_type = RoomType(property_id=self.property.id, name=f"PhaseRoom-{id(self)}", base_rate=150)
        self.db.add(room_type)
        self.db.flush()
        rooms = [Room(property_id=self.property.id, number=f"PA-{id(self)}-101", room_type_id=room_type.id, status="reserved"), Room(property_id=self.property.id, number=f"PA-{id(self)}-102", room_type_id=room_type.id, status="occupied"), Room(property_id=self.property.id, number=f"PA-{id(self)}-103", room_type_id=room_type.id, status="available")]
        self.db.add_all(rooms)
        self.db.flush()
        reservation = Reservation(property_id=self.property.id, guest_id=guests[0].id, check_in=date(2026, 9, 8), check_out=date(2026, 9, 12), status="reserved")
        self.db.add(reservation)
        self.db.flush()
        folio = Folio(reservation_id=reservation.id, status="open")
        self.db.add(folio)
        self.db.flush()
        self.db.add(ReservationRoom(reservation_id=reservation.id, room_id=rooms[0].id))
        stay = Stay(reservation_id=reservation.id, room_id=rooms[0].id, guest_id=guests[1].id, status="reserved", check_in=reservation.check_in, check_out=reservation.check_out, agreed_rate=Decimal("150.00"), deposit_required=Decimal("300.00"), deposit_received=Decimal("200.00"))
        self.db.add(stay)
        self.db.flush()
        self.db.add(StayOccupant(stay_id=stay.id, guest_id=guests[1].id, role="primary", is_primary=True, check_in=stay.check_in, check_out=stay.check_out))
        window = StayFolioWindow(folio_id=folio.id, stay_id=stay.id, name="Room charges", payer_type="guest", guest_id=guests[1].id, status="open")
        self.db.add(window)
        seed_deposit = DepositTransaction(stay_id=stay.id, folio_id=folio.id, transaction_type="received", amount=Decimal("200.00"), payment_method="cash", reference="DEP-SEED", created_by=self.user.id)
        self.db.add(seed_deposit)
        self.db.flush()
        business_date_state = self.db.scalar(select(BusinessDateState).where(BusinessDateState.property_id == self.property.id))
        if business_date_state is None:
            self.db.add(BusinessDateState(property_id=self.property.id, current_business_date=date(2026, 9, 8)))
        else:
            business_date_state.current_business_date = date(2026, 9, 8)
            business_date_state.last_closed_at = None
        post_deposit_received(
            self.db,
            stay_id=stay.id,
            folio_id=folio.id,
            reservation_id=reservation.id,
            deposit_id=seed_deposit.id,
            amount=Decimal("200.00"),
            method="cash",
            created_by=self.user.id,
        )
        self.db.commit()
        self.db.expire_all()
        self.reservation = self.db.get(Reservation, reservation.id)
        self.stay = self.db.get(Stay, stay.id)
        self.room = self.db.get(Room, rooms[0].id)
        self.room_2 = self.db.get(Room, rooms[2].id)
        self.folio = self.db.get(Folio, folio.id)
        self.window = self.db.scalar(select(StayFolioWindow).where(StayFolioWindow.stay_id == stay.id))
        self.guest_ahmed = self.db.get(Guest, guests[1].id)
        self.guest_bilal = self.db.get(Guest, guests[2].id)
        self.guest_usman = self.db.get(Guest, guests[3].id)
        self.user = self.db.get(User, self.user.id)

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def test_room_level_checkin_and_room_sharing(self):
        result = check_in_stay(self.stay.id, StayCheckInPayload(reason="Room 101 arrival"), self.db, self.user)
        self.assertEqual(result["status"], "checked_in")
        self.assertEqual(self.db.get(Room, self.room.id).status, "occupied")
        share = share_stay_with_occupant(self.stay.id, OccupantGuestChange(guest_id=self.guest_bilal.id), self.db, self.user)
        self.assertFalse(share["is_primary"])
        occupants = self.db.scalars(select(StayOccupant).where(StayOccupant.stay_id == self.stay.id).order_by(StayOccupant.id)).all()
        self.assertEqual(len(occupants), 2)
        changed = change_stay_occupant_guest(self.stay.id, share["id"], OccupantGuestChange(guest_id=self.guest_usman.id, reason="Guest replacement"), self.db, self.user)
        self.assertEqual(changed["guest_id"], self.guest_usman.id)

    def test_deposit_transfer_refund_and_apply_to_folio(self):
        other_reservation = Reservation(property_id=self.property.id, guest_id=self.guest_ahmed.id, check_in=date(2026, 9, 8), check_out=date(2026, 9, 12), status="reserved")
        self.db.add(other_reservation)
        self.db.flush()
        other_folio = Folio(reservation_id=other_reservation.id, status="open")
        self.db.add(other_folio)
        self.db.flush()
        other_stay = Stay(reservation_id=other_reservation.id, room_id=self.room_2.id, guest_id=self.guest_ahmed.id, status="reserved", check_in=other_reservation.check_in, check_out=other_reservation.check_out, agreed_rate=Decimal("180.00"))
        self.db.add(other_stay)
        self.db.commit()
        self.db.expire_all()
        other_stay = self.db.get(Stay, other_stay.id)

        transferred = transfer_deposit(
            self.stay.id,
            DepositTransferCreate(target_stay_id=other_stay.id, amount=Decimal("50.00"), reason="Room split"),
            idempotency_key="phase-a-transfer-001",
            db=self.db,
            user=self.user,
        )
        self.assertEqual(transferred["source_balance"], Decimal("150.00"))
        self.assertEqual(transferred["destination_balance"], Decimal("50.00"))
        refunded = refund_deposit(
            self.stay.id,
            DepositRefundCreate(amount=Decimal("25.00"), payment_method="cash", reason="Guest request"),
            idempotency_key="phase-a-refund-001",
            db=self.db,
            user=self.user,
        )
        self.assertEqual(refunded["balance"], Decimal("125.00"))
        self.assertTrue(self.db.scalar(select(FinancialTransaction.id).where(FinancialTransaction.transaction_type == "deposit_refund")))
        apply_result = apply_deposit(
            self.stay.id,
            DepositApplyCreate(folio_id=self.folio.id, amount=Decimal("100.00"), reason="Apply on arrival"),
            idempotency_key="phase-a-apply-001",
            db=self.db,
            user=self.user,
        )
        self.assertEqual(apply_result["balance"], Decimal("25.00"))
        payment = self.db.scalar(select(Payment).where(Payment.folio_id == self.folio.id))
        self.assertIsNotNone(payment)
        self.assertEqual(payment.amount, Decimal("100.00"))
        self.assertEqual(payment.method, "deposit")
        self.assertTrue(self.db.scalar(select(FinancialTransaction.id).where(FinancialTransaction.transaction_type == "deposit_applied")))

    def test_occupant_change_rejects_foreign_property_guest_without_side_effects(self):
        other_organization = Organization(name=f"Occupant Isolation Org {id(self)}", slug=f"occupant-isolation-org-{id(self)}")
        self.db.add(other_organization)
        self.db.flush()
        other_property = Property(
            organization_id=other_organization.id,
            name=f"Occupant Isolation Property {id(self)}",
            code=f"OCC-{id(self)}",
            slug=f"occupant-isolation-property-{id(self)}",
            timezone="UTC",
            currency="PKR",
        )
        self.db.add(other_property)
        self.db.flush()
        foreign_guest = Guest(property_id=other_property.id, full_name=f"Foreign occupant {id(self)}")
        self.db.add(foreign_guest)
        self.db.flush()
        occupant = self.db.scalar(
            select(StayOccupant).where(StayOccupant.stay_id == self.stay.id, StayOccupant.is_primary.is_(True))
        )
        original_guest_id = occupant.guest_id
        before_audits = self.db.query(AuditLog).count()

        with self.assertRaises(HTTPException) as raised:
            change_stay_occupant_guest(
                self.stay.id,
                occupant.id,
                OccupantGuestChange(guest_id=foreign_guest.id, reason="Cross-property attempt"),
                self.db,
                self.user,
            )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(self.db.get(StayOccupant, occupant.id).guest_id, original_guest_id)
        self.assertEqual(self.db.query(AuditLog).count(), before_audits)

    def test_folio_item_routing_and_window_lifecycle(self):
        item = FolioItem(folio_id=self.folio.id, stay_id=self.stay.id, description="Room minibar", category="minibar", quantity=Decimal("1"), unit_price=Decimal("40.00"), discount=Decimal("0.00"))
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        routed = route_folio_item(item.id, FolioItemRouteCreate(window_id=self.window.id, notes="Primary room window"), self.db, self.user)
        self.assertEqual(routed["window_id"], self.window.id)
        updated = update_folio_window(self.stay.id, self.window.id, FolioWindowUpdatePayload(name="Incidentals", status="closed"), self.db, self.user)
        self.assertEqual(updated["name"], "Incidentals")
        self.assertEqual(updated["status"], "closed")

    def test_folio_item_routing_rejects_cross_property_window_without_side_effects(self):
        other_property = ensure_test_property(self.db)
        other_guest = Guest(property_id=other_property.id, full_name="Other Property Guest")
        self.db.add(other_guest)
        other_room_type = RoomType(property_id=other_property.id, name=f"OtherType-{id(self)}", base_rate=100)
        self.db.add(other_room_type)
        self.db.flush()
        other_room = Room(property_id=other_property.id, number=f"OTHER-{id(self)}", room_type_id=other_room_type.id, status="available")
        self.db.add(other_room)
        self.db.flush()
        other_reservation = Reservation(property_id=other_property.id, guest_id=other_guest.id, check_in=date(2026, 9, 8), check_out=date(2026, 9, 12), status="reserved")
        self.db.add(other_reservation)
        self.db.flush()
        other_folio = Folio(reservation_id=other_reservation.id, status="open")
        self.db.add(other_folio)
        self.db.flush()
        other_stay = Stay(reservation_id=other_reservation.id, room_id=other_room.id, guest_id=other_guest.id, status="reserved", check_in=other_reservation.check_in, check_out=other_reservation.check_out, agreed_rate=Decimal("100.00"))
        self.db.add(other_stay)
        self.db.flush()
        other_window = StayFolioWindow(folio_id=other_folio.id, stay_id=other_stay.id, name="Other property", payer_type="guest", guest_id=other_guest.id, status="open")
        item = FolioItem(folio_id=self.folio.id, stay_id=self.stay.id, description="Minibar", category="minibar", quantity=Decimal("1"), unit_price=Decimal("20.00"), discount=Decimal("0.00"))
        self.db.add_all([other_window, item])
        self.db.commit()
        self.db.refresh(item)
        self.db.refresh(other_window)
        before_audits = self.db.query(AuditLog).count()
        with self.assertRaises(HTTPException) as raised:
            route_folio_item(item.id, FolioItemRouteCreate(window_id=other_window.id), self.db, self.user)
        self.assertEqual(raised.exception.status_code, 409)
        self.assertIsNone(self.db.scalar(select(FolioItemRouting).where(FolioItemRouting.folio_item_id == item.id)))
        self.assertEqual(self.db.query(AuditLog).count(), before_audits)

    def test_folio_window_rejects_guest_from_another_property_without_side_effects(self):
        other_organization = Organization(name=f"Foreign Org {id(self)}", slug=f"foreign-org-{id(self)}")
        self.db.add(other_organization)
        self.db.flush()
        foreign_property = Property(organization_id=other_organization.id, name="Foreign Property", code=f"FOREIGN-{id(self)}", slug=f"foreign-property-{id(self)}", timezone="UTC", currency="PKR")
        self.db.add(foreign_property)
        self.db.flush()
        foreign_guest = Guest(property_id=foreign_property.id, full_name="Foreign Payer")
        self.db.add(foreign_guest)
        self.db.commit()
        before_name = self.window.name
        before_audits = self.db.query(AuditLog).count()
        with self.assertRaises(HTTPException) as raised:
            update_folio_window(self.stay.id, self.window.id, FolioWindowUpdatePayload(name="Should not apply", guest_id=foreign_guest.id), self.db, self.user)
        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(self.db.get(StayFolioWindow, self.window.id).name, before_name)
        self.assertEqual(self.db.query(AuditLog).count(), before_audits)

    def test_deposit_refund_rejects_foreign_folio_without_partial_writes(self):
        organization = Organization(name=f"Foreign Deposit Org {id(self)}", slug=f"foreign-deposit-org-{id(self)}")
        self.db.add(organization)
        self.db.flush()
        foreign_property = Property(
            organization_id=organization.id,
            name="Foreign Deposit Property",
            code=f"FD-{id(self)}",
            slug=f"foreign-deposit-property-{id(self)}",
            timezone="UTC",
            currency="PKR",
        )
        self.db.add(foreign_property)
        self.db.flush()
        foreign_guest = Guest(property_id=foreign_property.id, full_name="Foreign deposit guest")
        self.db.add(foreign_guest)
        self.db.flush()
        foreign_reservation = Reservation(
            property_id=foreign_property.id,
            guest_id=foreign_guest.id,
            check_in=date(2026, 9, 8),
            check_out=date(2026, 9, 12),
            status="reserved",
        )
        self.db.add(foreign_reservation)
        self.db.flush()
        foreign_folio = Folio(reservation_id=foreign_reservation.id, status="open")
        self.db.add(foreign_folio)
        self.db.flush()

        before = (
            self.db.query(DepositTransaction).count(),
            self.db.query(FinancialTransaction).count(),
            self.db.query(AuditLog).count(),
        )
        with self.assertRaises(HTTPException) as denied:
            create_deposit_with_ledger(
                self.stay.id,
                {
                    "transaction_type": "refunded",
                    "amount": Decimal("10.00"),
                    "payment_method": "cash",
                    "folio_id": foreign_folio.id,
                    "reference": "foreign-folio-refund",
                    "notes": "must be rejected",
                },
                "foreign-folio-refund-key",
                self.db,
                self.user,
            )

        self.assertEqual(denied.exception.status_code, 404)
        after = (
            self.db.query(DepositTransaction).count(),
            self.db.query(FinancialTransaction).count(),
            self.db.query(AuditLog).count(),
        )
        self.assertEqual(after, before)

    def test_end_to_end_reservation_checkin_charges_payment_checkout_reporting(self):
        checked_in = check_in_stay(
            self.stay.id,
            StayCheckInPayload(reason="End-to-end journey"),
            self.db,
            self.user,
        )
        self.assertEqual(checked_in["status"], "checked_in")
        self.assertEqual(self.reservation.status, "checked_in")

        post_accrued_room_charges(
            self.db,
            self.reservation,
            self.folio,
            date(2026, 9, 8),
            self.user.id,
        )
        add_folio_item(
            self.folio.id,
            FolioItemCreate(
                description="Minibar",
                category="other",
                quantity=Decimal("1"),
                unit_price=Decimal("20.00"),
                discount=Decimal("0.00"),
            ),
            self.db,
            self.user,
        )
        add_payment(
            self.folio.id,
            PaymentCreate(amount=Decimal("170.00"), method="cash", reference="E2E-CASH"),
            "pms-journey-payment",
            self.db,
            self.user,
        )

        checkout = atomic_checkout(self.reservation.id, self.db, self.user)
        self.assertEqual(checkout["status"], "checked_out")
        self.assertEqual(checkout["folio_status"], "closed")
        self.assertEqual(self.db.get(Room, self.room.id).status, "dirty")
        self.assertEqual(self.db.get(Stay, self.stay.id).status, "completed")

        transactions = self.db.scalars(
            select(FinancialTransaction).where(
                FinancialTransaction.property_id == self.property.id,
                FinancialTransaction.business_date == date(2026, 9, 8),
                FinancialTransaction.status == "posted",
            )
        ).all()
        transaction_ids = [transaction.id for transaction in transactions]
        entries = self.db.scalars(
            select(LedgerEntry).where(LedgerEntry.transaction_id.in_(transaction_ids))
        ).all()
        debits = sum((Decimal(entry.amount) for entry in entries if entry.direction == "debit"), Decimal("0.00"))
        credits = sum((Decimal(entry.amount) for entry in entries if entry.direction == "credit"), Decimal("0.00"))
        self.assertEqual(debits, credits)

        report = report_summary(date(2026, 9, 8), date(2026, 9, 8), self.db, self.user)
        self.assertEqual(report["revenue"]["net"], 170.0)
        self.assertEqual(report["revenue"]["payments_received"], 370.0)
        self.assertEqual(report["revenue"]["outstanding_balance"], 0.0)
        self.assertIn("Booking Guest", [guest["guest_name"] for guest in report["top_guests"]])

    def test_rejected_unsettled_checkout_rolls_back_room_night_ledger_writes(self):
        check_in_stay(
            self.stay.id,
            StayCheckInPayload(reason="Unsettled checkout rollback"),
            self.db,
            self.user,
        )
        before_transactions = self.db.query(FinancialTransaction).count()
        before_items = self.db.query(FolioItem).count()

        with self.assertRaises(HTTPException) as denied:
            atomic_checkout(self.reservation.id, self.db, self.user)

        self.assertEqual(denied.exception.status_code, 409)
        self.assertIn("outstanding balance", denied.exception.detail)
        self.assertEqual(self.db.query(FinancialTransaction).count(), before_transactions)
        self.assertEqual(self.db.query(FolioItem).count(), before_items)
        self.assertEqual(self.db.get(Reservation, self.reservation.id).status, "checked_in")
        self.assertEqual(self.db.get(Folio, self.folio.id).status, "open")
        self.assertEqual(self.db.get(Room, self.room.id).status, "occupied")
        self.assertEqual(self.db.get(Stay, self.stay.id).status, "checked_in")


if __name__ == "__main__":
    unittest.main()
