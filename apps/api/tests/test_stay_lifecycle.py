import unittest
from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from tenant_test_support import ensure_test_property, ensure_test_property_access
from app.db import Base
from app.models import FinancialTransaction, Folio, Guest, Reservation, ReservationRoom, Role, Room, RoomType, StayOccupant, User
from app.front_desk import atomic_checkout
from app.pms_core import BookingGroup, Stay
from app.tenancy import Organization, Property
from app.stay_lifecycle import (
    FolioWindowCreate,
    FolioWindowUpdate,
    OccupantUpdate,
    RoomReplacement,
    StayDatesUpdate,
    StayFolioWindow,
    cancel_stay_room,
    create_stay_folio_window,
    remove_stay_occupant,
    replace_stay_room,
    update_stay_dates,
    update_stay_occupant,
    update_stay_folio_window,
)


class StayLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=cls.engine)

    def setUp(self):
        self.db = Session(self.engine)
        self.property = ensure_test_property(self.db)
        role = Role(name=f"reception-{id(self)}")
        self.db.add(role)
        guest = Guest(property_id=self.property.id, full_name="Booking Guest")
        occupant = Guest(property_id=self.property.id, full_name="Room Occupant")
        self.db.add_all([guest, occupant])
        self.db.flush()
        user = User(username=f"reception-{id(self)}", password_hash="test", role_id=role.id)
        self.db.add(user)
        self.db.flush()
        ensure_test_property_access(self.db, user.id, self.property.id)
        room_type = RoomType(property_id=self.property.id, name=f"Standard-{guest.id}", base_rate=100)
        self.db.add(room_type)
        self.db.flush()
        room_a = Room(property_id=self.property.id, number=f"A-{guest.id}", room_type_id=room_type.id, status="reserved")
        room_b = Room(property_id=self.property.id, number=f"B-{guest.id}", room_type_id=room_type.id, status="available")
        self.db.add_all([room_a, room_b])
        self.db.flush()
        reservation = Reservation(property_id=self.property.id, guest_id=guest.id, check_in=date(2026, 9, 8), check_out=date(2026, 9, 12), status="reserved")
        self.db.add(reservation)
        self.db.flush()
        folio = Folio(reservation_id=reservation.id, status="open")
        self.db.add(folio)
        self.db.flush()
        self.folio = folio
        self.db.add(ReservationRoom(reservation_id=reservation.id, room_id=room_a.id))
        stay = Stay(reservation_id=reservation.id, room_id=room_a.id, guest_id=guest.id, status="reserved", check_in=date(2026, 9, 8), check_out=date(2026, 9, 12), agreed_rate=Decimal("100.00"))
        self.db.add(stay)
        self.db.flush()
        self.db.add(StayOccupant(stay_id=stay.id, guest_id=guest.id, role="primary", is_primary=True, check_in=stay.check_in, check_out=stay.check_out))
        self.db.add(StayOccupant(stay_id=stay.id, guest_id=occupant.id, role="occupant", is_primary=False, check_in=stay.check_in, check_out=stay.check_out))
        self.db.commit()
        self.stay = self.db.get(Stay, stay.id)
        self.user = user
        self.guest = guest
        self.occupant = occupant
        self.room_a = room_a
        self.room_b = room_b
        self.reservation = reservation

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def test_room_replacement_updates_stay_and_reservation_link(self):
        result = replace_stay_room(self.stay.id, RoomReplacement(to_room_id=self.room_b.id, reason="Guest requested alternate room"), self.db, self.user)
        self.assertEqual(result["to_room_id"], self.room_b.id)
        self.assertEqual(self.db.get(Stay, self.stay.id).room_id, self.room_b.id)
        self.assertEqual(self.db.get(Room, self.room_a.id).status, "available")
        links = self.db.scalars(select(ReservationRoom).where(ReservationRoom.reservation_id == self.reservation.id)).all()
        self.assertEqual([link.room_id for link in links], [self.room_b.id])

    def test_room_stay_dates_can_be_changed_independently(self):
        result = update_stay_dates(self.stay.id, StayDatesUpdate(check_in=date(2026, 9, 9), check_out=date(2026, 9, 11)), self.db, self.user)
        self.assertEqual(result["check_in"], date(2026, 9, 9))
        self.assertEqual(result["check_out"], date(2026, 9, 11))
        occupants = self.db.scalars(select(StayOccupant).where(StayOccupant.stay_id == self.stay.id)).all()
        self.assertTrue(all(item.check_in == date(2026, 9, 9) and item.check_out == date(2026, 9, 11) for item in occupants))

    def test_occupant_can_be_promoted_and_removed(self):
        occupants = self.db.scalars(select(StayOccupant).where(StayOccupant.stay_id == self.stay.id).order_by(StayOccupant.id)).all()
        result = update_stay_occupant(self.stay.id, occupants[1].id, OccupantUpdate(is_primary=True, role="primary"), self.db, self.user)
        self.assertTrue(result["is_primary"])
        self.db.expire_all()
        current = self.db.scalars(select(StayOccupant).where(StayOccupant.stay_id == self.stay.id).order_by(StayOccupant.id)).all()
        self.assertEqual(sum(1 for item in current if item.is_primary), 1)
        remove_stay_occupant(self.stay.id, current[1].id, self.db, self.user)
        self.assertEqual(len(self.db.scalars(select(StayOccupant).where(StayOccupant.stay_id == self.stay.id)).all()), 1)

    def test_reserved_room_stay_can_be_cancelled_without_erasing_history(self):
        result = cancel_stay_room(self.stay.id, None, self.db, self.user)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(self.db.get(Room, self.room_a.id).status, "available")
        self.assertEqual(self.db.scalars(select(ReservationRoom).where(ReservationRoom.reservation_id == self.reservation.id)).all(), [])

    def test_room_level_folio_window_is_routable(self):
        result = create_stay_folio_window(self.stay.id, FolioWindowCreate(name="Room Charges", payer_type="guest", guest_id=self.guest.id), self.db, self.user)
        self.assertEqual(result["stay_id"], self.stay.id)
        row = self.db.get(StayFolioWindow, result["id"])
        self.assertEqual(row.folio_id, self.folio.id)
        self.assertEqual(row.payer_type, "guest")

    def test_folio_window_rejects_foreign_group_on_create_and_update(self):
        organization = Organization(name=f"Foreign Group Org {id(self)}", slug=f"foreign-group-org-{id(self)}")
        self.db.add(organization)
        self.db.flush()
        foreign_property = Property(
            organization_id=organization.id,
            name="Foreign Group Property",
            code=f"FG-{id(self)}",
            slug=f"foreign-group-property-{id(self)}",
            timezone="UTC",
            currency="PKR",
        )
        self.db.add(foreign_property)
        self.db.flush()
        foreign_group = BookingGroup(
            property_id=foreign_property.id,
            code=f"FGC-{id(self)}",
            name="Foreign booking group",
        )
        self.db.add(foreign_group)
        self.db.flush()

        with self.assertRaises(HTTPException) as denied_create:
            create_stay_folio_window(
                self.stay.id,
                FolioWindowCreate(name="Foreign payer", payer_type="guest", group_id=foreign_group.id),
                self.db,
                self.user,
            )
        self.assertEqual(denied_create.exception.status_code, 409)
        self.assertEqual(self.db.scalars(select(StayFolioWindow).where(StayFolioWindow.stay_id == self.stay.id)).all(), [])

        created = create_stay_folio_window(
            self.stay.id,
            FolioWindowCreate(name="Local window", payer_type="guest", guest_id=self.guest.id),
            self.db,
            self.user,
        )
        window = self.db.get(StayFolioWindow, created["id"])
        with self.assertRaises(HTTPException) as denied_update:
            update_stay_folio_window(
                self.stay.id,
                window.id,
                FolioWindowUpdate(group_id=foreign_group.id),
                self.db,
                self.user,
            )
        self.assertEqual(denied_update.exception.status_code, 409)
        self.db.refresh(window)
        self.assertIsNone(window.group_id)
        self.assertEqual(window.payer_type, "guest")

    def test_group_payer_requires_group_linked_to_reservation(self):
        group = BookingGroup(
            property_id=self.property.id,
            code=f"UNLINKED-{id(self)}",
            name="Unlinked booking group",
        )
        self.db.add(group)
        self.db.flush()
        with self.assertRaises(HTTPException) as denied:
            create_stay_folio_window(
                self.stay.id,
                FolioWindowCreate(name="Unlinked group payer", payer_type="group", group_id=group.id),
                self.db,
                self.user,
            )
        self.assertEqual(denied.exception.status_code, 409)
        self.assertEqual(self.db.scalars(select(StayFolioWindow).where(StayFolioWindow.stay_id == self.stay.id)).all(), [])

    def _prepare_checked_in_stay(self):
        self.reservation.status = "checked_in"
        self.room_a.status = "occupied"
        self.stay.status = "checked_in"
        self.db.flush()

    def _create_foreign_room_and_guest(self):
        organization = Organization(name=f"Checkout Foreign Org {id(self)}", slug=f"checkout-foreign-org-{id(self)}")
        self.db.add(organization)
        self.db.flush()
        foreign_property = Property(
            organization_id=organization.id,
            name="Checkout Foreign Property",
            code=f"CO-{id(self)}",
            slug=f"checkout-foreign-property-{id(self)}",
            timezone="UTC",
            currency="PKR",
        )
        self.db.add(foreign_property)
        self.db.flush()
        foreign_type = RoomType(property_id=foreign_property.id, name=f"Checkout Type {id(self)}", base_rate=100)
        foreign_guest = Guest(property_id=foreign_property.id, full_name="Foreign checkout occupant")
        self.db.add_all([foreign_type, foreign_guest])
        self.db.flush()
        foreign_room = Room(property_id=foreign_property.id, number=f"CO-R-{id(self)}", room_type_id=foreign_type.id, status="occupied")
        self.db.add(foreign_room)
        self.db.flush()
        return foreign_room, foreign_guest

    def test_checkout_rejects_cross_property_room_link_without_mutations(self):
        self._prepare_checked_in_stay()
        foreign_room, _ = self._create_foreign_room_and_guest()
        self.db.add(ReservationRoom(reservation_id=self.reservation.id, room_id=foreign_room.id))
        self.db.flush()
        transaction_count = self.db.query(FinancialTransaction).count()

        with self.assertRaises(HTTPException) as denied:
            atomic_checkout(self.reservation.id, self.db, self.user)

        self.assertEqual(denied.exception.status_code, 409)
        self.assertEqual(self.reservation.status, "checked_in")
        self.assertEqual(self.folio.status, "open")
        self.assertEqual(self.stay.status, "checked_in")
        self.assertEqual(foreign_room.status, "occupied")
        self.assertEqual(self.db.query(FinancialTransaction).count(), transaction_count)

    def test_checkout_rejects_cross_property_occupant_without_mutations(self):
        self._prepare_checked_in_stay()
        _, foreign_guest = self._create_foreign_room_and_guest()
        self.db.add(
            StayOccupant(
                stay_id=self.stay.id,
                guest_id=foreign_guest.id,
                role="occupant",
                is_primary=False,
                check_in=self.stay.check_in,
                check_out=self.stay.check_out,
            )
        )
        self.db.flush()
        transaction_count = self.db.query(FinancialTransaction).count()

        with self.assertRaises(HTTPException) as denied:
            atomic_checkout(self.reservation.id, self.db, self.user)

        self.assertEqual(denied.exception.status_code, 409)
        self.assertEqual(self.reservation.status, "checked_in")
        self.assertEqual(self.folio.status, "open")
        self.assertEqual(self.stay.status, "checked_in")
        self.assertEqual(self.db.query(FinancialTransaction).count(), transaction_count)


if __name__ == "__main__":
    unittest.main()
