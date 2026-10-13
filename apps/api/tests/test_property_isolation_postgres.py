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
from app.models import FolioItem
from datetime import date
from app.tenancy import Organization, Property, PropertyUserAccess, resolve_authorized_property
from app.pms_core import BookingGroup, GroupReservation, GroupReservationLink, Stay, get_group, list_groups, link_reservation_to_group
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


if __name__ == "__main__":
    unittest.main()
