import unittest
from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Folio, Guest, Reservation, ReservationRoom, Role, Room, RoomType, User
from app.pms_core import (
    FolioWindow,
    Stay,
    StayCreate,
    create_folio_window,
    create_reservation_stays,
    list_folio_windows,
    list_reservation_stays,
    update_stay_discount,
)
from app.tenancy import Organization, Property
from tenant_test_support import ensure_test_property, ensure_test_property_access


class PMSCoreAuthorizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=cls.engine)

    def setUp(self):
        self.db = Session(self.engine)
        allowed = ensure_test_property(self.db)
        role = Role(name=f"pms-core-auth-{id(self)}")
        self.db.add(role)
        self.db.flush()
        self.user = User(username=f"pms-core-auth-{id(self)}", password_hash="test", role_id=role.id)
        self.db.add(self.user)
        self.db.flush()
        ensure_test_property_access(self.db, self.user.id, allowed.id)

        org = Organization(name=f"PMS Core Foreign Org {id(self)}", slug=f"pms-core-foreign-org-{id(self)}")
        self.db.add(org)
        self.db.flush()
        self.foreign = Property(
            organization_id=org.id,
            name="PMS Core Foreign Property",
            code=f"PC-{id(self)}",
            slug=f"pms-core-foreign-property-{id(self)}",
            timezone="UTC",
            currency="PKR",
        )
        self.db.add(self.foreign)
        self.db.flush()
        self.guest = Guest(property_id=self.foreign.id, full_name="Foreign Guest")
        self.room_type = RoomType(property_id=self.foreign.id, name=f"PMS Core Type {id(self)}", base_rate=100)
        self.db.add_all([self.guest, self.room_type])
        self.db.flush()
        self.room = Room(property_id=self.foreign.id, number=f"PC-{id(self)}", room_type_id=self.room_type.id, status="reserved")
        self.db.add(self.room)
        self.db.flush()
        self.reservation = Reservation(
            property_id=self.foreign.id,
            guest_id=self.guest.id,
            check_in=date(2026, 10, 1),
            check_out=date(2026, 10, 3),
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
            guest_id=self.guest.id,
            status="reserved",
            check_in=self.reservation.check_in,
            check_out=self.reservation.check_out,
            agreed_rate=Decimal("100.00"),
        )
        self.db.add(self.stay)
        self.db.commit()

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def test_foreign_pms_core_stay_and_folio_routes_are_denied_without_side_effects(self):
        original_rate = self.stay.agreed_rate
        checks = (
            lambda: list_reservation_stays(self.reservation.id, self.db, self.user),
            lambda: update_stay_discount(self.stay.id, Decimal("10"), Decimal("0"), self.db, self.user),
            lambda: list_folio_windows(self.folio.id, self.db, self.user),
            lambda: create_folio_window(self.folio.id, "Should not create", "guest", self.guest.id, None, self.db, self.user),
            lambda: create_reservation_stays(self.reservation.id, [StayCreate(room_id=self.room.id, agreed_rate=Decimal("100.00"))], self.db, self.user),
        )
        for operation in checks:
            with self.subTest(operation=operation):
                with self.assertRaises(HTTPException) as denied:
                    operation()
                self.assertEqual(denied.exception.status_code, 403)

        self.assertEqual(self.stay.agreed_rate, original_rate)
        self.assertEqual(self.db.query(FolioWindow).filter(FolioWindow.folio_id == self.folio.id).count(), 0)
        self.assertEqual(self.db.query(Stay).filter(Stay.reservation_id == self.reservation.id).count(), 1)


if __name__ == "__main__":
    unittest.main()
