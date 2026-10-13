import unittest
from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.main import app  # noqa: F401 - register all API models before creating test metadata
from app.configuration import get_property_settings
from app.db import Base
from app.models import Guest, Reservation, Role, Room, RoomType, User
from app.pms_core import Stay
from app.reservation_workflows import ReservationRoomSetup, ReservationWorkflowCreate, create_reservation_workflow
from app.tenancy import (
    Organization,
    OrganizationSetting,
    Property,
    PropertySetting,
    PropertyUserAccess,
)


class ReservationScheduleSemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=cls.engine)

    def test_reservation_creation_keeps_dates_and_does_not_fake_actual_arrival_times(self):
        with Session(self.engine) as db:
            role = Role(name="reservation-schedule-admin")
            db.add(role)
            db.flush()
            user = User(username="reservation-schedule-user", password_hash="test", role_id=role.id)
            organization = Organization(name="Schedule Org", slug="schedule-org")
            db.add_all([user, organization])
            db.flush()
            property_ = Property(
                organization_id=organization.id,
                name="Schedule Hotel",
                code="SCHEDULE",
                slug="schedule-hotel",
            )
            db.add(property_)
            db.flush()
            db.add(PropertyUserAccess(
                user_id=user.id,
                property_id=property_.id,
                access_scope="organization",
                is_primary=True,
            ))
            guest = Guest(property_id=property_.id, full_name="Test Guest")
            room_type = RoomType(property_id=property_.id, name="Schedule Room", base_rate=Decimal("100.00"))
            db.add_all([guest, room_type])
            db.flush()
            room = Room(property_id=property_.id, number="S-01", room_type_id=room_type.id, status="available")
            db.add_all([
                room,
                OrganizationSetting(
                    organization_id=organization.id,
                    setting_key="default_check_in_time",
                    setting_value="15:00",
                ),
                OrganizationSetting(
                    organization_id=organization.id,
                    setting_key="default_check_out_time",
                    setting_value="11:00",
                ),
                PropertySetting(
                    property_id=property_.id,
                    setting_key="check_in_time",
                    setting_value="16:00",
                ),
            ])
            db.commit()
            db.refresh(guest)
            db.refresh(room)

            effective = get_property_settings(property_.id, db, user)
            self.assertEqual(effective["settings"]["check_in_time"], "16:00")
            self.assertEqual(effective["settings"]["check_out_time"], "11:00")

            check_in = date(2030, 1, 10)
            check_out = date(2030, 1, 12)
            result = create_reservation_workflow(
                ReservationWorkflowCreate(
                    guest_id=guest.id,
                    check_in=check_in,
                    check_out=check_out,
                    rooms=[ReservationRoomSetup(room_id=room.id, agreed_rate=Decimal("100.00"))],
                ),
                db,
                user,
            )

            reservation = db.get(Reservation, result["id"])
            stay = db.scalar(select(Stay).where(Stay.reservation_id == reservation.id))
            self.assertEqual(reservation.check_in, check_in)
            self.assertEqual(reservation.check_out, check_out)
            self.assertEqual(stay.check_in, check_in)
            self.assertEqual(stay.check_out, check_out)
            self.assertIsNone(reservation.checked_in_at)
            self.assertIsNone(reservation.checked_out_at)
            self.assertIsNone(stay.actual_check_in)
            self.assertIsNone(stay.actual_check_out)
            self.assertEqual(reservation.status, "reserved")
            self.assertEqual(stay.status, "reserved")


if __name__ == "__main__":
    unittest.main()
