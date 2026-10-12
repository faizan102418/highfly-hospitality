import unittest
from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Guest, Reservation, ReservationRoom, Role, Room, RoomType, StayOccupant, User, DepositTransaction
from app.pms_core import Stay
from app.pms_domain import (
    OccupantCreate,
    ReservationSplitCreate,
    RoomMoveCreate,
    add_stay_occupant,
    list_deposits,
    list_stay_occupants,
    move_stay_room,
    split_reservation,
)
from tenant_test_support import ensure_test_property, ensure_test_property_access
from app.tenancy import Organization, Property


class PMSDomainAuthorizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=cls.engine)

    def setUp(self):
        self.db = Session(self.engine)
        self.allowed_property = ensure_test_property(self.db)
        role = self.db.scalar(select(Role).where(Role.name == "admin"))
        if role is None:
            role = Role(name="admin")
            self.db.add(role)
            self.db.flush()
        self.user = User(username=f"pms-domain-auth-{id(self)}", password_hash="test", role_id=role.id)
        self.db.add(self.user)
        self.db.flush()
        ensure_test_property_access(self.db, self.user.id, self.allowed_property.id)

        organization = Organization(name=f"Foreign Org {id(self)}", slug=f"foreign-org-{id(self)}")
        self.db.add(organization)
        self.db.flush()
        self.foreign_property = Property(
            organization_id=organization.id,
            name="Foreign Property",
            code=f"F-{id(self)}",
            slug=f"foreign-property-{id(self)}",
            timezone="UTC",
            currency="PKR",
        )
        self.db.add(self.foreign_property)
        self.db.flush()

        self.guest = Guest(property_id=self.foreign_property.id, full_name="Foreign Guest")
        self.room_type = RoomType(property_id=self.foreign_property.id, name=f"Foreign Type {id(self)}", base_rate=100)
        self.db.add_all([self.guest, self.room_type])
        self.db.flush()
        self.room = Room(property_id=self.foreign_property.id, number=f"FOREIGN-{id(self)}", room_type_id=self.room_type.id, status="occupied")
        self.target_room = Room(property_id=self.foreign_property.id, number=f"FOREIGN-T-{id(self)}", room_type_id=self.room_type.id, status="available")
        self.db.add_all([self.room, self.target_room])
        self.db.flush()
        self.reservation = Reservation(
            property_id=self.foreign_property.id,
            guest_id=self.guest.id,
            check_in=date(2026, 10, 1),
            check_out=date(2026, 10, 3),
            status="checked_in",
        )
        self.db.add(self.reservation)
        self.db.flush()
        self.db.add(ReservationRoom(reservation_id=self.reservation.id, room_id=self.room.id))
        self.stay = Stay(
            reservation_id=self.reservation.id,
            room_id=self.room.id,
            guest_id=self.guest.id,
            status="checked_in",
            check_in=self.reservation.check_in,
            check_out=self.reservation.check_out,
            agreed_rate=Decimal("100.00"),
        )
        self.db.add(self.stay)
        self.db.flush()
        self.db.add(StayOccupant(stay_id=self.stay.id, guest_id=self.guest.id, role="primary", is_primary=True, check_in=self.stay.check_in, check_out=self.stay.check_out))
        self.db.commit()
        self.db.refresh(self.user)
        self.db.refresh(self.stay)

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def test_foreign_stay_reads_and_mutations_are_denied_without_side_effects(self):
        occupant_count = self.db.scalar(select(StayOccupant.id).where(StayOccupant.stay_id == self.stay.id))
        original_room_id = self.stay.room_id

        checks = (
            lambda: list_stay_occupants(self.stay.id, self.db, self.user),
            lambda: list_deposits(self.stay.id, self.db, self.user),
            lambda: add_stay_occupant(self.stay.id, OccupantCreate(guest_id=self.guest.id), self.db, self.user),
            lambda: move_stay_room(self.stay.id, RoomMoveCreate(to_room_id=self.target_room.id), self.db, self.user),
            lambda: split_reservation(self.reservation.id, ReservationSplitCreate(room_ids=[self.room.id]), self.db, self.user),
        )
        for operation in checks:
            with self.subTest(operation=operation):
                with self.assertRaises(HTTPException) as denied:
                    operation()
                self.assertEqual(denied.exception.status_code, 403)

        self.assertEqual(self.stay.room_id, original_room_id)
        self.assertEqual(self.db.scalar(select(StayOccupant.id).where(StayOccupant.stay_id == self.stay.id)), occupant_count)
        self.assertEqual(self.room.status, "occupied")
        self.assertEqual(self.target_room.status, "available")
        self.assertEqual(self.db.query(DepositTransaction).filter(DepositTransaction.stay_id == self.stay.id).count(), 0)


if __name__ == "__main__":
    unittest.main()
