import unittest
from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import inspect, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db import engine
# Register the full PMS model metadata before exercising ledger ORM mappers.
# Stay lives in pms_core.py rather than models.py and LedgerEntry references it.
from app.pms_core import Stay  # noqa: F401
from app.ledger import post_transaction, reverse_transaction
from app.models import BusinessDateState, FinancialTransaction, LedgerEntry, Room, RoomType
from app.tenancy import Organization, Property
from tenant_test_support import ensure_test_property


class PostgreSQLSmokeTest(unittest.TestCase):
    def _ensure_business_date(self, db, property_):
        if db.scalar(select(BusinessDateState).where(BusinessDateState.property_id == property_.id)) is None:
            db.add(BusinessDateState(property_id=property_.id, current_business_date=date.today()))
            db.flush()

    @classmethod
    def setUpClass(cls):
        if engine.dialect.name != "postgresql":
            raise unittest.SkipTest("HMS_DATABASE_URL is not PostgreSQL")

    def test_dirty_room_housekeeping_uses_its_own_property_business_date(self):
        """A room in property B must not inherit property A's business date."""
        with Session(engine) as db:
            first_state = db.get(BusinessDateState, 1)
            if first_state is None:
                first_suffix = "first"
                first_org = Organization(
                    name=f"CI Housekeeping First {first_suffix}",
                    slug=f"ci-housekeeping-first-{first_suffix}",
                )
                db.add(first_org)
                db.flush()
                first_property = Property(
                    organization_id=first_org.id,
                    name="CI Housekeeping First",
                    code="HK-FIRST",
                    slug="ci-housekeeping-first",
                    timezone="UTC",
                    currency="PKR",
                )
                db.add(first_property)
                db.flush()
                first_state = BusinessDateState(
                    property_id=first_property.id,
                    current_business_date=date(2026, 10, 1),
                )
                db.add(first_state)
                db.flush()
            else:
                first_state.current_business_date = date(2026, 10, 1)

            suffix = uuid4().hex[:10]
            organization = Organization(
                name=f"CI Housekeeping Tenant {suffix}",
                slug=f"ci-housekeeping-tenant-{suffix}",
            )
            db.add(organization)
            db.flush()
            property_ = Property(
                organization_id=organization.id,
                name=f"CI Housekeeping Property {suffix}",
                code=f"HK-{suffix}",
                slug=f"ci-housekeeping-property-{suffix}",
                timezone="UTC",
                currency="PKR",
            )
            db.add(property_)
            db.flush()

            target_date = date(2026, 10, 2)
            db.add(
                BusinessDateState(
                    property_id=property_.id,
                    current_business_date=target_date,
                )
            )
            room_type = RoomType(
                property_id=property_.id,
                name=f"CI Housekeeping Room Type {suffix}",
                base_rate=Decimal("100.00"),
            )
            db.add(room_type)
            db.flush()
            room = Room(
                property_id=property_.id,
                number=f"HK-{suffix}",
                room_type_id=room_type.id,
                status="available",
            )
            db.add(room)
            db.flush()

            room.status = "dirty"
            db.flush()

            generated_date = db.execute(
                text("SELECT business_date FROM housekeeping_tasks WHERE room_id = :room_id"),
                {"room_id": room.id},
            ).scalar_one()
            self.assertEqual(first_state.current_business_date, date(2026, 10, 1))
            self.assertEqual(generated_date, target_date)

    def test_expected_tables_exist(self):
        names = set(inspect(engine).get_table_names())
        for expected in (
            "stays", "stay_occupants", "stay_rate_segments", "deposit_transactions",
            "room_moves", "reservation_splits", "business_date_state",
            "financial_transactions", "ledger_entries",
        ):
            self.assertIn(expected, names)

    def test_ledger_transaction_is_balanced_and_persistent(self):
        with Session(engine) as db:
            property_ = ensure_test_property(db)
            self._ensure_business_date(db, property_)
            tx = post_transaction(
                db,
                transaction_type="ci_smoke",
                description="CI PostgreSQL ledger smoke test",
                created_by=None,
                property_id=property_.id,
                lines=[
                    {"account": "Cash", "direction": "debit", "amount": Decimal("10.00")},
                    {"account": "Test Revenue", "direction": "credit", "amount": Decimal("10.00")},
                ],
            )
            transaction_id = tx.id
            db.commit()

        with Session(engine) as db:
            tx = db.get(FinancialTransaction, transaction_id)
            self.assertIsNotNone(tx)
            entries = db.scalars(select(LedgerEntry).where(LedgerEntry.transaction_id == transaction_id)).all()
            self.assertEqual(len(entries), 2)
            self.assertEqual(sum((e.amount for e in entries if e.direction == "debit"), Decimal("0.00")), Decimal("10.00"))
            self.assertEqual(sum((e.amount for e in entries if e.direction == "credit"), Decimal("0.00")), Decimal("10.00"))

    def test_postgresql_rejects_unbalanced_ledger_transaction(self):
        with Session(engine) as db:
            property_ = ensure_test_property(db)
            self._ensure_business_date(db, property_)
            tx = post_transaction(
                db,
                transaction_type="ci_balance_guard",
                description="CI PostgreSQL ledger balance guard test",
                created_by=None,
                property_id=property_.id,
                lines=[
                    {"account": "Cash", "direction": "debit", "amount": Decimal("11.00")},
                    {"account": "Test Revenue", "direction": "credit", "amount": Decimal("11.00")},
                ],
            )
            db.commit()

            db.add(
                LedgerEntry(
                    transaction_id=tx.id,
                    account="Cash",
                    direction="debit",
                    amount=Decimal("1.00"),
                    currency="PKR",
                )
            )
            with self.assertRaises(DBAPIError):
                db.commit()
            db.rollback()

    def test_postgresql_rejects_mixed_currency_ledger_transaction(self):
        with Session(engine) as db:
            property_ = ensure_test_property(db)
            self._ensure_business_date(db, property_)
            tx = post_transaction(
                db,
                transaction_type="ci_currency_guard",
                description="CI PostgreSQL ledger currency guard test",
                created_by=None,
                property_id=property_.id,
                lines=[
                    {"account": "Cash", "direction": "debit", "amount": Decimal("12.00")},
                    {"account": "Test Revenue", "direction": "credit", "amount": Decimal("12.00")},
                ],
            )
            db.commit()

            # Keep the transaction numerically balanced so only the mixed-currency
            # database guard can reject it.
            db.add_all(
                [
                    LedgerEntry(
                        transaction_id=tx.id,
                        account="Cash",
                        direction="debit",
                        amount=Decimal("1.00"),
                        currency="USD",
                    ),
                    LedgerEntry(
                        transaction_id=tx.id,
                        account="Test Revenue",
                        direction="credit",
                        amount=Decimal("1.00"),
                        currency="USD",
                    ),
                ]
            )
            with self.assertRaises(DBAPIError):
                db.commit()
            db.rollback()

    def test_ledger_entries_cannot_be_updated_or_deleted(self):
        with Session(engine) as db:
            property_ = ensure_test_property(db)
            self._ensure_business_date(db, property_)
            tx = post_transaction(
                db,
                transaction_type="ci_immutability",
                description="CI PostgreSQL ledger immutability test",
                created_by=None,
                property_id=property_.id,
                lines=[
                    {"account": "Cash", "direction": "debit", "amount": Decimal("7.00")},
                    {"account": "Test Revenue", "direction": "credit", "amount": Decimal("7.00")},
                ],
            )
            db.commit()
            entry = db.scalars(select(LedgerEntry).where(LedgerEntry.transaction_id == tx.id).order_by(LedgerEntry.id)).first()
            self.assertIsNotNone(entry)

            entry.amount = Decimal("8.00")
            with self.assertRaises(DBAPIError):
                db.flush()
            db.rollback()

            entry = db.get(LedgerEntry, entry.id)
            db.delete(entry)
            with self.assertRaises(DBAPIError):
                db.flush()
            db.rollback()

    def test_financial_transaction_can_only_transition_to_reversed(self):
        with Session(engine) as db:
            property_ = ensure_test_property(db)
            self._ensure_business_date(db, property_)
            tx = post_transaction(
                db,
                transaction_type="ci_reversal",
                description="CI PostgreSQL reversal test",
                created_by=None,
                property_id=property_.id,
                lines=[
                    {"account": "Cash", "direction": "debit", "amount": Decimal("5.00")},
                    {"account": "Test Revenue", "direction": "credit", "amount": Decimal("5.00")},
                ],
            )
            db.commit()
            tx_id = tx.id

            reversal = reverse_transaction(db, transaction_id=tx_id, created_by=None, reason="CI test correction")
            db.commit()
            db.refresh(tx)
            self.assertEqual(tx.status, "reversed")
            self.assertEqual(reversal.reversal_of_id, tx_id)

            tx.description = "tampered"
            with self.assertRaises(DBAPIError):
                db.flush()
            db.rollback()


if __name__ == "__main__":
    unittest.main()
