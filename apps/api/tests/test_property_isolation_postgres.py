import unittest
from uuid import uuid4

from fastapi import HTTPException
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import engine
from app.models import Folio, Guest, Reservation, Role, Room, RoomType, User
from app.billing import (
    add_folio_deposit,
    add_folio_item,
    add_payment,
    close_folio,
    get_folio,
    FolioDepositCreate,
    remove_folio_item,
    update_folio_item,
)
from app.schemas import FolioItemCreate, FolioItemUpdate, PaymentCreate
from app.models import AuditLog, FinancialTransaction, FolioItem
from app.folio_corrections import FolioItemCorrection, correct_folio_item, reverse_folio_item
from app.financial_ops import WindowCreate as FinancialWindowCreate, create_folio_window as create_financial_folio_window
from app.pms_core import create_folio_window as create_core_folio_window
from app.financial_ops import AdjustmentCreate, create_adjustment
from datetime import date
from app.tenancy import Organization, Property, PropertyUserAccess, resolve_authorized_property
from app.pms_core import BookingGroup, FolioWindow, GroupReservation, GroupReservationLink, Stay, get_group, list_groups, link_reservation_to_group
from app.phase_a_workflows import stay_or_404 as workflow_stay_or_404
from app.phase_a_completion import stay_or_404 as completion_stay_or_404
from app.reservation_workflows import (
    ActionReason,
    ReservationRoomSetup,
    ReservationUpdate,
    ReservationWorkflowCreate,
    cancel_reservation,
    create_reservation_workflow,
    mark_no_show,
    reservation_availability_check,
    update_reservation,
)
from app.reservation_workflows import (
    ActionReason,
    ReservationRoomSetup,
    ReservationUpdate,
    ReservationWorkflowCreate,
    cancel_reservation,
    create_reservation_workflow,
    mark_no_show,
    reservation_availability_check,
    update_reservation,
)
from tenant_test_support import ensure_test_property


class PropertyIsolationPostgreSQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if engine.dialect.name != "postgresql":
            raise unittest.SkipTest("HMS_DATABASE_URL is not PostgreSQL")

    def test_legacy_stay_helpers_deny_cross_property_access(self):
        suffix = uuid4().hex[:12]
        with Session(engine) as db:
            allowed_property = ensure_test_property(db)
            organization = Organization(name=f"Legacy Isolation Org {suffix}", slug=f"legacy-isolation-org-{suffix}")
            db.add(organization)
            db.flush()
            other_property = Property(
                organization_id=organization.id,
                name=f"Legacy Isolation Property {suffix}",
                code=f"LGC-{suffix[:6]}",
                slug=f"legacy-isolation-property-{suffix}",
                timezone="UTC",
                currency="PKR",
            )
            db.add(other_property)
            role = db.scalar(select(Role).where(Role.name == "admin"))
            if role is None:
                role = Role(name="admin")
                db.add(role)
                db.flush()
            user = User(username=f"legacy-isolation-{suffix}", password_hash="test", role_id=role.id)
            db.add(user)
            db.flush()
            db.add(PropertyUserAccess(user_id=user.id, property_id=allowed_property.id, access_scope="property", is_primary=True))
            guest = Guest(property_id=other_property.id, full_name=f"Other guest {suffix}")
            room_type = RoomType(property_id=other_property.id, name=f"Other type {suffix}", base_rate=100)
            db.add_all([guest, room_type])
            db.flush()
            room = Room(property_id=other_property.id, number=f"X-{suffix}", room_type_id=room_type.id, status="available")
            reservation = Reservation(property_id=other_property.id, guest_id=guest.id, check_in=date(2026, 10, 1), check_out=date(2026, 10, 2), status="reserved")
            db.add_all([room, reservation])
            db.flush()
            stay = Stay(reservation_id=reservation.id, room_id=room.id, guest_id=guest.id, status="reserved", check_in=date(2026, 10, 1), check_out=date(2026, 10, 2), agreed_rate=Decimal("100.00"))
            db.add(stay)
            db.flush()

            for helper in (workflow_stay_or_404, completion_stay_or_404):
                with self.assertRaises(HTTPException) as denied:
                    helper(db, stay.id, user.id)
                self.assertEqual(denied.exception.status_code, 403)
            db.rollback()

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

            foreign_item = FolioItem(
                folio_id=other_folio.id,
                description="Foreign charge",
                category="other",
                quantity=Decimal("1.00"),
                unit_price=Decimal("100.00"),
                discount=Decimal("0.00"),
            )
            db.add(foreign_item)
            db.flush()
            original_description = foreign_item.description
            original_item_count = db.scalar(select(FolioItem.id).where(FolioItem.folio_id == other_folio.id))
            denied_calls = (
                lambda: add_folio_item(other_folio.id, FolioItemCreate(description="Unauthorized", category="other", unit_price=Decimal("10.00")), db, user),
                lambda: update_folio_item(other_folio.id, foreign_item.id, FolioItemUpdate(description="Tampered", category="other", quantity=Decimal("1"), unit_price=Decimal("1")), db, user),
                lambda: remove_folio_item(other_folio.id, foreign_item.id, db, user),
                lambda: add_payment(other_folio.id, PaymentCreate(amount=Decimal("1.00"), method="cash"), None, db, user),
                lambda: add_folio_deposit(other_folio.id, FolioDepositCreate(amount=Decimal("1.00"), method="cash"), db, user),
                lambda: close_folio(other_folio.id, db, user),
            )
            for call in denied_calls:
                with self.subTest(call=call):
                    with self.assertRaises(HTTPException) as mutation_denied:
                        call()
                    self.assertEqual(mutation_denied.exception.status_code, 404)
            db.flush()
            self.assertEqual(foreign_item.description, original_description)
            self.assertEqual(db.scalar(select(FolioItem.id).where(FolioItem.folio_id == other_folio.id)), original_item_count)

            original_dates = (other_reservation.check_in, other_reservation.check_out)
            original_status = other_reservation.status
            reservation_calls = (
                lambda: update_reservation(other_reservation.id, ReservationUpdate(notes="unauthorized"), db, user),
                lambda: cancel_reservation(other_reservation.id, ActionReason(reason="unauthorized"), db, user),
                lambda: mark_no_show(other_reservation.id, ActionReason(reason="unauthorized"), db, user),
                lambda: reservation_availability_check(other_reservation.id, db, user),
            )
            for call in reservation_calls:
                with self.subTest(call=call):
                    with self.assertRaises(HTTPException) as reservation_denied:
                        call()
                    self.assertEqual(reservation_denied.exception.status_code, 403)
            self.assertEqual((other_reservation.check_in, other_reservation.check_out), original_dates)
            self.assertEqual(other_reservation.status, original_status)

            with self.assertRaises(HTTPException) as create_denied:
                create_reservation_workflow(
                    ReservationWorkflowCreate(
                        guest_id=other_guest.id,
                        check_in=date(2026, 10, 1),
                        check_out=date(2026, 10, 2),
                        rooms=[ReservationRoomSetup(room_id=1, agreed_rate=Decimal("100.00"))],
                    ),
                    db,
                    user,
                )
            self.assertEqual(create_denied.exception.status_code, 409)

            db.rollback()


    def test_booking_groups_are_property_scoped_and_links_cannot_cross_properties(self):
        suffix = uuid4().hex[:12]
        with Session(engine) as db:
            allowed_property = ensure_test_property(db)
            organization = Organization(name=f"Group Isolation Org {suffix}", slug=f"group-isolation-org-{suffix}")
            db.add(organization)
            db.flush()
            other_property = Property(
                organization_id=organization.id,
                name=f"Group Isolation Property {suffix}",
                code=f"GRP-{suffix[:6]}",
                slug=f"group-isolation-property-{suffix}",
                timezone="UTC",
                currency="PKR",
            )
            db.add(other_property)
            role = db.scalar(select(Role).where(Role.name == "admin"))
            if role is None:
                role = Role(name="admin")
                db.add(role)
                db.flush()
            user = User(username=f"group-isolation-{suffix}", password_hash="test", role_id=role.id)
            db.add(user)
            db.flush()
            db.add(PropertyUserAccess(user_id=user.id, property_id=allowed_property.id, access_scope="property", is_primary=True))
            allowed_guest = Guest(property_id=allowed_property.id, full_name=f"Allowed group guest {suffix}")
            foreign_guest = Guest(property_id=other_property.id, full_name=f"Foreign group guest {suffix}")
            db.add_all([allowed_guest, foreign_guest])
            db.flush()
            allowed_reservation = Reservation(property_id=allowed_property.id, guest_id=allowed_guest.id, check_in=date(2026, 10, 1), check_out=date(2026, 10, 2), status="reserved")
            foreign_reservation = Reservation(property_id=other_property.id, guest_id=foreign_guest.id, check_in=date(2026, 10, 1), check_out=date(2026, 10, 2), status="reserved")
            db.add_all([allowed_reservation, foreign_reservation])
            db.flush()
            allowed_group = BookingGroup(property_id=allowed_property.id, code=f"AG-{suffix}", name=f"Allowed group {suffix}")
            foreign_group = BookingGroup(property_id=other_property.id, code=f"FG-{suffix}", name=f"Foreign group {suffix}")
            db.add_all([allowed_group, foreign_group])
            db.flush()
            db.add(GroupReservation(group_id=foreign_group.id, reservation_id=foreign_reservation.id, role="member"))
            db.flush()

            visible_groups = list_groups(db, user)
            self.assertIn(allowed_group.id, {group.id for group in visible_groups})
            self.assertNotIn(foreign_group.id, {group.id for group in visible_groups})
            with self.assertRaises(HTTPException) as get_denied:
                get_group(foreign_group.id, db, user)
            self.assertEqual(get_denied.exception.status_code, 403)

            with self.assertRaises(HTTPException) as foreign_link_denied:
                link_reservation_to_group(allowed_group.id, GroupReservationLink(reservation_id=foreign_reservation.id, role="member", notes=None), db, user)
            self.assertEqual(foreign_link_denied.exception.status_code, 403)

            with self.assertRaises(HTTPException) as foreign_group_link_denied:
                link_reservation_to_group(foreign_group.id, GroupReservationLink(reservation_id=allowed_reservation.id, role="member", notes=None), db, user)
            self.assertEqual(foreign_group_link_denied.exception.status_code, 403)

            with self.assertRaises(HTTPException) as workflow_group_denied:
                create_reservation_workflow(
                    ReservationWorkflowCreate(
                        guest_id=allowed_guest.id,
                        check_in=date(2026, 10, 1),
                        check_out=date(2026, 10, 2),
                        group_id=foreign_group.id,
                        rooms=[ReservationRoomSetup(room_id=1, agreed_rate=Decimal("100.00"))],
                    ),
                    db,
                    user,
                )
            self.assertEqual(workflow_group_denied.exception.status_code, 409)
            db.rollback()



    def test_adjustment_rejects_foreign_property_stay_reference_without_side_effects(self):
        suffix = uuid4().hex[:12]
        with Session(engine) as db:
            allowed_property = ensure_test_property(db)
            organization = Organization(
                name=f"Ledger Stay Isolation Org {suffix}",
                slug=f"ledger-stay-isolation-org-{suffix}",
            )
            db.add(organization)
            db.flush()
            foreign_property = Property(
                organization_id=organization.id,
                name=f"Ledger Stay Foreign Property {suffix}",
                code=f"LSI-{suffix[:6]}",
                slug=f"ledger-stay-foreign-property-{suffix}",
                timezone="UTC",
                currency="PKR",
            )
            db.add(foreign_property)
            role = db.scalar(select(Role).where(Role.name == "admin"))
            if role is None:
                role = Role(name="admin")
                db.add(role)
                db.flush()
            user = User(
                username=f"ledger-stay-isolation-{suffix}",
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
            guest = Guest(property_id=foreign_property.id, full_name=f"Foreign ledger guest {suffix}")
            room_type = RoomType(property_id=foreign_property.id, name=f"Foreign type {suffix}", base_rate=100)
            db.add_all([guest, room_type])
            db.flush()
            room = Room(
                property_id=foreign_property.id,
                number=f"LS-{suffix[:6]}",
                room_type_id=room_type.id,
                status="available",
            )
            reservation = Reservation(
                property_id=foreign_property.id,
                guest_id=guest.id,
                check_in=date(2026, 10, 1),
                check_out=date(2026, 10, 2),
                status="checked_in",
            )
            db.add_all([room, reservation])
            db.flush()
            stay = Stay(
                reservation_id=reservation.id,
                room_id=room.id,
                guest_id=guest.id,
                status="checked_in",
                check_in=date(2026, 10, 1),
                check_out=date(2026, 10, 2),
                agreed_rate=Decimal("100.00"),
            )
            db.add(stay)
            db.flush()

            transaction_count = db.query(FinancialTransaction).count()
            audit_count = db.query(AuditLog).count()
            payload = AdjustmentCreate(
                description="Invalid cross-property stay reference",
                lines=[
                    {"account": "Cash", "direction": "debit", "amount": "10.00", "stay_id": stay.id},
                    {"account": "Revenue", "direction": "credit", "amount": "10.00"},
                ],
            )
            with self.assertRaises(HTTPException) as denied:
                create_adjustment(payload, db, user)
            self.assertEqual(denied.exception.status_code, 400)
            self.assertEqual(db.query(FinancialTransaction).count(), transaction_count)
            self.assertEqual(db.query(AuditLog).count(), audit_count)
            db.rollback()

    def test_folio_window_rejects_foreign_group_reference_in_both_routes(self):
        suffix = uuid4().hex[:12]
        with Session(engine) as db:
            allowed_property = ensure_test_property(db)
            organization = Organization(
                name=f"Folio Window Isolation Org {suffix}",
                slug=f"folio-window-isolation-org-{suffix}",
            )
            db.add(organization)
            db.flush()
            foreign_property = Property(
                organization_id=organization.id,
                name=f"Folio Window Foreign Property {suffix}",
                code=f"FWI-{suffix[:6]}",
                slug=f"folio-window-foreign-property-{suffix}",
                timezone="UTC",
                currency="PKR",
            )
            db.add(foreign_property)
            role = db.scalar(select(Role).where(Role.name == "admin"))
            if role is None:
                role = Role(name="admin")
                db.add(role)
                db.flush()
            user = User(username=f"folio-window-isolation-{suffix}", password_hash="test", role_id=role.id)
            db.add(user)
            db.flush()
            db.add(PropertyUserAccess(
                user_id=user.id,
                property_id=allowed_property.id,
                access_scope="property",
                is_primary=True,
            ))
            allowed_guest = Guest(property_id=allowed_property.id, full_name=f"Allowed window guest {suffix}")
            db.add(allowed_guest)
            db.flush()
            reservation = Reservation(
                property_id=allowed_property.id,
                guest_id=allowed_guest.id,
                check_in=date(2026, 10, 1),
                check_out=date(2026, 10, 2),
                status="reserved",
            )
            db.add(reservation)
            db.flush()
            folio = Folio(reservation_id=reservation.id, status="open")
            foreign_group = BookingGroup(
                property_id=foreign_property.id,
                code=f"FWG-{suffix}",
                name=f"Foreign group {suffix}",
            )
            db.add_all([folio, foreign_group])
            db.flush()
            initial_count = db.query(FolioWindow).count()

            with self.assertRaises(HTTPException) as financial_denied:
                create_financial_folio_window(
                    folio.id,
                    FinancialWindowCreate(name="Foreign group window", group_id=foreign_group.id),
                    db,
                    user,
                )
            self.assertEqual(financial_denied.exception.status_code, 409)
            self.assertEqual(db.query(FolioWindow).count(), initial_count)

            with self.assertRaises(HTTPException) as core_denied:
                create_core_folio_window(
                    folio.id,
                    name="Foreign group window",
                    payer_type="guest",
                    group_id=foreign_group.id,
                    db=db,
                    user=user,
                )
            self.assertEqual(core_denied.exception.status_code, 409)
            self.assertEqual(db.query(FolioWindow).count(), initial_count)
            db.rollback()

    def test_folio_corrections_deny_foreign_property_without_financial_side_effects(self):
        suffix = uuid4().hex[:12]
        with Session(engine) as db:
            allowed_property = ensure_test_property(db)
            organization = Organization(name=f"Correction Isolation Org {suffix}", slug=f"correction-isolation-org-{suffix}")
            db.add(organization)
            db.flush()
            foreign_property = Property(
                organization_id=organization.id,
                name=f"Correction Foreign Property {suffix}",
                code=f"COR-{suffix[:6]}",
                slug=f"correction-foreign-property-{suffix}",
                timezone="UTC",
                currency="PKR",
            )
            db.add(foreign_property)
            role = db.scalar(select(Role).where(Role.name == "admin"))
            if role is None:
                role = Role(name="admin")
                db.add(role)
                db.flush()
            user = User(username=f"correction-isolation-{suffix}", password_hash="test", role_id=role.id)
            db.add(user)
            db.flush()
            db.add(PropertyUserAccess(user_id=user.id, property_id=allowed_property.id, access_scope="property", is_primary=True))
            guest = Guest(property_id=foreign_property.id, full_name=f"Foreign correction guest {suffix}")
            db.add(guest)
            db.flush()
            reservation = Reservation(
                property_id=foreign_property.id,
                guest_id=guest.id,
                check_in=date(2026, 10, 1),
                check_out=date(2026, 10, 2),
                status="checked_in",
            )
            db.add(reservation)
            db.flush()
            folio = Folio(reservation_id=reservation.id, status="open")
            db.add(folio)
            db.flush()
            item = FolioItem(
                folio_id=folio.id,
                description="Foreign charge",
                category="other",
                quantity=Decimal("1.00"),
                unit_price=Decimal("100.00"),
                discount=Decimal("0.00"),
            )
            db.add(item)
            db.flush()

            transaction_count = db.query(FinancialTransaction).count()
            audit_count = db.query(AuditLog).count()
            original_item_count = db.query(FolioItem).count()
            original_description = item.description

            denied_calls = (
                lambda: reverse_folio_item(folio.id, item.id, "unauthorized correction", db, user),
                lambda: correct_folio_item(
                    folio.id,
                    item.id,
                    FolioItemCorrection(
                        description="Tampered charge",
                        category="other",
                        quantity=Decimal("1.00"),
                        unit_price=Decimal("1.00"),
                        reason="unauthorized correction",
                    ),
                    db,
                    user,
                ),
            )
            for call in denied_calls:
                with self.subTest(call=call):
                    with self.assertRaises(HTTPException) as denied:
                        call()
                    self.assertEqual(denied.exception.status_code, 403)
                    self.assertEqual(db.query(FinancialTransaction).count(), transaction_count)
                    self.assertEqual(db.query(AuditLog).count(), audit_count)
                    self.assertEqual(db.query(FolioItem).count(), original_item_count)
                    self.assertEqual(item.description, original_description)

            db.rollback()


if __name__ == "__main__":
    unittest.main()
