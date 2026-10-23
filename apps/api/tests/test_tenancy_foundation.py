import unittest
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Role, User
from app.tenancy import (
    Organization,
    Property,
    PropertyUserAccess,
    resolve_authorized_property,
)


class TenancyFoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(bind=cls.engine)

    def test_property_access_is_explicit(self):
        suffix = uuid4().hex[:10]
        with Session(self.engine) as db:
            role = Role(name=f"admin-{suffix}")
            db.add(role)
            db.flush()
            user = User(
                username=f"hq-admin-{suffix}",
                password_hash="test",
                role_id=role.id,
            )
            db.add(user)
            org = Organization(name=f"HighFly {suffix}", slug=f"highfly-{suffix}")
            db.add(org)
            db.flush()
            la_serene = Property(
                organization_id=org.id,
                name=f"La Serene {suffix}",
                code=f"LS-{suffix}",
                slug=f"la-serene-{suffix}",
            )
            hotel_b = Property(
                organization_id=org.id,
                name=f"Hotel B {suffix}",
                code=f"HB-{suffix}",
                slug=f"hotel-b-{suffix}",
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
            self.assertEqual(
                resolve_authorized_property(db, user.id, la_serene.id).id,
                la_serene.id,
            )

            # Sharing an organization does not implicitly grant access to every
            # property: each selected property must have an explicit access row.
            with self.assertRaises(HTTPException) as raised:
                resolve_authorized_property(db, user.id, hotel_b.id)
            self.assertEqual(raised.exception.status_code, 403)

    def test_inactive_organization_cannot_resolve_property(self):
        suffix = uuid4().hex[:10]
        with Session(self.engine) as db:
            role = Role(name=f"admin-{suffix}")
            db.add(role)
            db.flush()
            user = User(
                username=f"inactive-org-user-{suffix}",
                password_hash="test",
                role_id=role.id,
            )
            org = Organization(
                name=f"Inactive organization {suffix}",
                slug=f"inactive-org-{suffix}",
                status="inactive",
            )
            db.add_all([user, org])
            db.flush()
            property_ = Property(
                organization_id=org.id,
                name=f"Inactive property {suffix}",
                code=f"IP-{suffix}",
                slug=f"inactive-property-{suffix}",
            )
            db.add(property_)
            db.flush()
            db.add(PropertyUserAccess(
                user_id=user.id,
                property_id=property_.id,
                access_scope="property",
                is_primary=True,
            ))
            db.commit()

            with self.assertRaises(HTTPException) as raised:
                resolve_authorized_property(db, user.id, property_.id)
            self.assertEqual(raised.exception.status_code, 403)


    def test_inactive_property_cannot_be_resolved(self):
        suffix = uuid4().hex[:10]
        with Session(self.engine) as db:
            role = Role(name=f"admin-{suffix}")
            db.add(role)
            db.flush()
            user = User(
                username=f"inactive-property-user-{suffix}",
                password_hash="test",
                role_id=role.id,
            )
            org = Organization(
                name=f"Active organization {suffix}",
                slug=f"active-org-{suffix}",
            )
            db.add_all([user, org])
            db.flush()
            property_ = Property(
                organization_id=org.id,
                name=f"Inactive property {suffix}",
                code=f"IP-{suffix}",
                slug=f"inactive-property-{suffix}",
                status="inactive",
            )
            db.add(property_)
            db.flush()
            db.add(PropertyUserAccess(
                user_id=user.id,
                property_id=property_.id,
                access_scope="property",
                is_primary=True,
            ))
            db.commit()

            # Membership alone must not grant access after a property is disabled.
            with self.assertRaises(HTTPException) as raised:
                resolve_authorized_property(db, user.id, property_.id)
            self.assertEqual(raised.exception.status_code, 403)


    def test_revoked_property_access_cannot_resolve_property(self):
        suffix = uuid4().hex[:10]
        with Session(self.engine) as db:
            role = Role(name=f"revoked-admin-{suffix}")
            db.add(role)
            db.flush()
            user = User(
                username=f"revoked-access-user-{suffix}",
                password_hash="test",
                role_id=role.id,
            )
            org = Organization(
                name=f"Revocation organization {suffix}",
                slug=f"revocation-org-{suffix}",
            )
            db.add_all([user, org])
            db.flush()
            property_ = Property(
                organization_id=org.id,
                name=f"Revocation property {suffix}",
                code=f"RV-{suffix}",
                slug=f"revocation-property-{suffix}",
            )
            db.add(property_)
            db.flush()
            access = PropertyUserAccess(
                user_id=user.id,
                property_id=property_.id,
                access_scope="property",
                is_primary=True,
            )
            db.add(access)
            db.commit()

            self.assertEqual(
                resolve_authorized_property(db, user.id, property_.id).id,
                property_.id,
            )

            # Membership revocation takes effect on the next authorization check;
            # a previously valid user/property pair must not remain authorized.
            db.delete(access)
            db.commit()
            with self.assertRaises(HTTPException) as raised:
                resolve_authorized_property(db, user.id, property_.id)
            self.assertEqual(raised.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
