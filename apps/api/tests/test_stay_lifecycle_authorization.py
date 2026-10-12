import unittest
from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Folio, Guest, Reservation, ReservationRoom, Role, Room, RoomType, StayOccupant, User
from app.pms_core import Stay
from app.stay_lifecycle import (
    FolioWindowCreate,
    FolioWindowUpdate,
    OccupantUpdate,
    RoomReplacement,
    StayDatesUpdate,
    StayFolioWindow,
    cancel_stay_room,
    create_stay_folio_window,
    get_stay_lifecycle,
    list_stay_folio_windows,
    remove_stay_occupant,
    replace_stay_room,
    update_stay_dates,
    update_stay_folio_window,
    update_stay_occupant,
)
from app.tenancy import Organization, Property
from tenant_test_support import ensure_test_property, ensure_test_property_access


class StayLifecycleAuthorizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=cls.engine)

    def setUp(self):
        self.db = Session(self.engine)
        self.allowed_property = ensure_test_property(self.db)
        role = Role(name=f"lifecycle-auth-{id(self)}")
        self.db.add(role)
        self.db.flush()
        self.user = User(username=f"lifecycle-auth-{id(self)}", password_hash="test", role_id=role.id)
        self.db.add(self.user)
        self.db.flush()
        ensure_test_property_access(self.db, self.user.id, self.allowed_property.id)

        organization = Organization(name=f"Lifecycle Foreign Org {id(self)}", slug=f"lifecycle-foreign-org-{id(self)}")
        self.db.add(organization)
        self.db.flush()
        self.foreign_property = Property(
            organization_id=organization.id,
            name="Lifecycle Foreign Property",
            code=f"LF-{id(self)}",
            slug=f"lifecycle-foreign-property-{id(self)}",
            timezone="UTC",
            currency="PKR",
        )
        self.db.add(self.foreign_property)
        self.db.flush()
        guest = Guest(property_id=self.foreign_property.id, full_name="Foreign Guest")
        occupant_guest = Guest(property_id=self.foreign_property.id, full_name="Foreign Occupant")
        room_type = RoomType(property_id=self.foreign_property.id, name=f"Lifecycle Type {id(self)}", base_rate=100)
        self.db.add_all([guest, occupant_guest, room_type])
        self.db.flush()
        self.room = Room(property_id=self.foreign_property.id, number=f"LF-A-{id(self)}", room_type_id=room_type.id, status="reserved")
        self.target_room = Room(property_id=self.foreign_property.id, number=f"LF-B-{id(self)}", room_type_id=room_type.id, status="available")
        self.db.add_all([self.room, self.target_room])
        self.db.flush()
        self.reservation = Reservation(
            property_id=self.foreign_property.id,
            guest_id=guest.id,
            check_in=date(2026, 10, 1),
            check_out=date(2026, 10, 5),
            status="reserved",
        )
        self.db.add(self.reservation)
        self.db.flush()
        self.folio = Folio(reservation_id=self.reservation.id, status="open")
        self.db.add(self.folio)
        self.db.flush()
        self.db.add(ReservationRoom(reservation_id=self.reservation.id, room_id=self.room.id))
        self.stay = Stay(
            reservation_id=self.reservation.id,
            room_id=self.room.id,
            guest_id=guest.id,
            status="reserved",
            check_in=self.reservation.check_in,
            check_out=self.reservation.check_out,
            agreed_rate=Decimal("100.00"),
        )
        self.db.add(self.stay)
        self.db.flush()
        self.occupant = StayOccupant(
            stay_id=self.stay.id,
            guest_id=occupant_guest.id,
            role="primary",
            is_primary=True,
            check_in=self.stay.check_in,
            check_out=self.stay.check_out,
        )
        self.db.add(self.occupant)
        self.db.flush()
        self.window = StayFolioWindow(folio_id=self.folio.id, stay_id=self.stay.id, name="Foreign window", payer_type="guest", guest_id=guest.id, status="open")
        self.db.add(self.window)
        self.db.commit()

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def test_foreign_stay_lifecycle_reads_and_mutations_are_denied(self):
        original_room_id = self.stay.room_id
        original_dates = (self.stay.check_in, self.stay.check_out)
        original_window_name = self.window.name
        original_occupant_role = self.occupant.role

        checks = (
            lambda: get_stay_lifecycle(self.stay.id, self.db, self.user),
            lambda: update_stay_dates(self.stay.id, StayDatesUpdate(check_in=date(2026, 10, 2), check_out=date(2026, 10, 4)), self.db, self.user),
            lambda: update_stay_occupant(self.stay.id, self.occupant.id, OccupantUpdate(role="changed"), self.db, self.user),
            lambda: remove_stay_occupant(self.stay.id, self.occupant.id, self.db, self.user),
            lambda: replace_stay_room(self.stay.id, RoomReplacement(to_room_id=self.target_room.id), self.db, self.user),
            lambda: cancel_stay_room(self.stay.id, None, self.db, self.user),
            lambda: list_stay_folio_windows(self.stay.id, self.db, self.user),
            lambda: create_stay_folio_window(self.stay.id, FolioWindowCreate(name="Should not exist"), self.db, self.user),
            lambda: update_stay_folio_window(self.stay.id, self.window.id, FolioWindowUpdate(name="Should not change"), self.db, self.user),
        )
        for operation in checks:
            with self.subTest(operation=operation):
                with self.assertRaises(HTTPException) as denied:
                    operation()
                self.assertEqual(denied.exception.status_code, 403)

        self.assertEqual(self.stay.room_id, original_room_id)
        self.assertEqual((self.stay.check_in, self.stay.check_out), original_dates)
        self.assertEqual(self.window.name, original_window_name)
        self.assertEqual(self.occupant.role, original_occupant_role)
        self.assertEqual(self.db.query(StayFolioWindow).filter(StayFolioWindow.stay_id == self.stay.id).count(), 1)
        self.assertEqual(self.db.query(ReservationRoom).filter(ReservationRoom.reservation_id == self.reservation.id).count(), 1)


if __name__ == "__main__":
    unittest.main()
