import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Role, User
from app.tenancy import Organization, Property, PropertyUserAccess


class TenancyFoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(bind=cls.engine)

    def test_property_access_is_explicit(self):
        with Session(self.engine) as db:
            role = Role(name="admin")
            db.add(role)
            db.flush()
            user = User(
                username="hq-admin",
                password_hash="test",
                role_id=role.id,
            )
            db.add(user)
            org = Organization(name="HighFly Hospitality", slug="highfly")
            db.add(org)
            db.flush()
            la_serene = Property(
                organization_id=org.id,
                name="La Serene Hotel & Resort",
                code="LA-SERENE",
                slug="la-serene",
            )
            hotel_b = Property(
                organization_id=org.id,
                name="Hotel B",
                code="HOTEL-B",
                slug="hotel-b",
            )
            db.add_all([la_serene, hotel_b])
            db.flush()
            db.add(PropertyUserAccess(
                user_id=user.id,
                property_id=la_serene.id,
                access_scope="organization",
                is_primary=True,
            ))
            db.commit()

            access = db.scalars(
                select(PropertyUserAccess).where(PropertyUserAccess.user_id == user.id)
            ).all()

            self.assertEqual(len(access), 1)
            self.assertEqual(access[0].property_id, la_serene.id)
            self.assertNotEqual(access[0].property_id, hotel_b.id)


if __name__ == "__main__":
    unittest.main()
