import os
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

API_ROOT = Path(__file__).resolve().parents[1]
PREVIOUS_REVISION = "0024_housekeeping_task_conflict"
LATEST_REVISION = "0025_housekeeping_property_date"

APPLICATION_SCHEMA_OBJECTS_SQL = text("""
    WITH candidates(schema_name, object_type, object_name, classid, object_id) AS (
        SELECT n.nspname, 'schema', n.nspname,
               'pg_namespace'::regclass, n.oid
        FROM pg_namespace AS n
        WHERE n.nspname NOT IN ('pg_catalog', 'information_schema', 'public')
          AND n.nspname NOT LIKE 'pg_%'
          AND NOT EXISTS (
              SELECT 1 FROM pg_extension AS e WHERE e.extnamespace = n.oid
          )
        UNION ALL
        SELECT n.nspname, 'relation', c.relname, 'pg_class'::regclass, c.oid
        FROM pg_class AS c JOIN pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg_%'
        UNION ALL
        SELECT n.nspname, 'routine', p.proname, 'pg_proc'::regclass, p.oid
        FROM pg_proc AS p JOIN pg_namespace AS n ON n.oid = p.pronamespace
        WHERE n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg_%'
        UNION ALL
        SELECT n.nspname, 'type', t.typname, 'pg_type'::regclass, t.oid
        FROM pg_type AS t JOIN pg_namespace AS n ON n.oid = t.typnamespace
        WHERE n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg_%'
        UNION ALL
        SELECT n.nspname, 'operator', o.oprname,
               'pg_operator'::regclass, o.oid
        FROM pg_operator AS o JOIN pg_namespace AS n ON n.oid = o.oprnamespace
        WHERE n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg_%'
        UNION ALL
        SELECT n.nspname, 'operator class', o.opcname,
               'pg_opclass'::regclass, o.oid
        FROM pg_opclass AS o JOIN pg_namespace AS n ON n.oid = o.opcnamespace
        WHERE n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg_%'
        UNION ALL
        SELECT n.nspname, 'operator family', o.opfname,
               'pg_opfamily'::regclass, o.oid
        FROM pg_opfamily AS o JOIN pg_namespace AS n ON n.oid = o.opfnamespace
        WHERE n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg_%'
        UNION ALL
        SELECT n.nspname, 'collation', c.collname,
               'pg_collation'::regclass, c.oid
        FROM pg_collation AS c JOIN pg_namespace AS n ON n.oid = c.collnamespace
        WHERE n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg_%'
        UNION ALL
        SELECT n.nspname, 'conversion', c.conname,
               'pg_conversion'::regclass, c.oid
        FROM pg_conversion AS c JOIN pg_namespace AS n ON n.oid = c.connamespace
        WHERE n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg_%'
        UNION ALL
        SELECT n.nspname, 'text search config', c.cfgname,
               'pg_ts_config'::regclass, c.oid
        FROM pg_ts_config AS c JOIN pg_namespace AS n ON n.oid = c.cfgnamespace
        WHERE n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg_%'
        UNION ALL
        SELECT n.nspname, 'text search dictionary', d.dictname,
               'pg_ts_dict'::regclass, d.oid
        FROM pg_ts_dict AS d JOIN pg_namespace AS n ON n.oid = d.dictnamespace
        WHERE n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg_%'
        UNION ALL
        SELECT n.nspname, 'text search parser', p.prsname,
               'pg_ts_parser'::regclass, p.oid
        FROM pg_ts_parser AS p JOIN pg_namespace AS n ON n.oid = p.prsnamespace
        WHERE n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg_%'
        UNION ALL
        SELECT n.nspname, 'text search template', t.tmplname,
               'pg_ts_template'::regclass, t.oid
        FROM pg_ts_template AS t JOIN pg_namespace AS n ON n.oid = t.tmplnamespace
        WHERE n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg_%'
        UNION ALL
        SELECT n.nspname, 'extended statistic', s.stxname,
               'pg_statistic_ext'::regclass, s.oid
        FROM pg_statistic_ext AS s
        JOIN pg_namespace AS n ON n.oid = s.stxnamespace
        WHERE n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg_%'
    )
    SELECT schema_name, object_type, object_name
    FROM candidates AS c
    WHERE NOT EXISTS (
        SELECT 1 FROM pg_depend AS d
        WHERE d.classid = c.classid
          AND d.objid = c.object_id
          AND d.refclassid = 'pg_extension'::regclass
          AND d.deptype = 'e'
    )
    LIMIT 1
    """)


def _require_empty_application_schema(connection):
    existing_object = connection.execute(APPLICATION_SCHEMA_OBJECTS_SQL).first()
    if existing_object:
        schema_name, object_type, object_name = existing_object
        raise RuntimeError(
            "Migration tests require no application schema objects; found "
            f"{object_type} {schema_name}.{object_name}"
        )


LEGACY_HOUSEKEEPING_FUNCTION = """
CREATE OR REPLACE FUNCTION hms_auto_housekeeping_task_for_dirty_room()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE current_date_value date;
BEGIN
    IF NEW.status='dirty' AND OLD.status IS DISTINCT FROM 'dirty' THEN
        SELECT current_business_date INTO current_date_value
        FROM business_date_state WHERE id=1;
        IF current_date_value IS NULL THEN
            RAISE EXCEPTION USING ERRCODE='55000',
                MESSAGE='Business date is not initialized';
        END IF;

        INSERT INTO housekeeping_tasks (
            task_no, room_id, business_date, task_type, status,
            priority, reason, created_at, updated_at
        )
        VALUES (
            'HK-' || to_char(current_date_value, 'YYYYMMDD') || '-' ||
                upper(substr(md5(random()::text || NEW.id::text), 1, 8)),
            NEW.id, current_date_value, 'checkout_clean', 'pending',
            'normal', 'Room requires cleaning after checkout',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        ON CONFLICT (room_id) WHERE status IN ('pending','in_progress')
        DO NOTHING;
    END IF;
    RETURN NEW;
END; $$;
"""


class HousekeepingMigrationTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        database_url = os.environ.get("HMS_TEST_DATABASE_URL", "").strip()
        if not database_url:
            raise unittest.SkipTest("HMS_TEST_DATABASE_URL is not set")
        if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
            raise unittest.SkipTest("HMS_TEST_DATABASE_URL must point to PostgreSQL")

        test_database = make_url(database_url).database
        ci_database = (
            os.environ.get("CI", "").lower() == "true"
            and test_database == "la_serene_hms_ci"
        )
        local_database = bool(
            test_database and test_database.startswith("la_serene_hms_pg_integrity_")
        )
        if not (ci_database or local_database):
            raise RuntimeError(
                "Migration tests require a disposable PostgreSQL test database"
            )
        configured_database = os.environ.get("HMS_DATABASE_URL", "").strip()
        configured_url = make_url(configured_database)
        test_url = make_url(database_url)
        if configured_url != test_url:
            raise RuntimeError(
                "HMS_DATABASE_URL must match the disposable test database URL"
            )
        if test_url.host not in {"localhost", "127.0.0.1", "::1"}:
            raise RuntimeError(
                "Migration tests may only connect to a local PostgreSQL service"
            )

        cls.engine = create_engine(database_url, future=True)
        if cls.engine.dialect.name != "postgresql":
            raise unittest.SkipTest("HMS_TEST_DATABASE_URL must point to PostgreSQL")
        with cls.engine.connect() as connection:
            _require_empty_application_schema(connection)
            if (
                connection.execute(
                    text("SELECT to_regclass('public.alembic_version')")
                ).scalar_one()
                is not None
            ):
                raise RuntimeError(
                    "Migration tests require a fresh disposable database"
                )

        cls.config = Config(str(API_ROOT / "alembic.ini"))
        cls.config.set_main_option("script_location", str(API_ROOT / "alembic"))
        cls.scripts = ScriptDirectory.from_config(cls.config)
        cls.organization_ids = []
        cls.property_ids = []
        cls.room_ids = []
        from app.models import BusinessDateState, Room, RoomType
        from app.tenancy import Organization, Property

        cls.BusinessDateState = BusinessDateState
        cls.Room = Room
        cls.RoomType = RoomType
        cls.Organization = Organization
        cls.Property = Property

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "engine"):
            cls.engine.dispose()

    def tearDown(self):
        with self.engine.begin() as connection:
            for room_id in self.room_ids:
                connection.execute(
                    text("DELETE FROM housekeeping_tasks WHERE room_id = :room_id"),
                    {"room_id": room_id},
                )
                connection.execute(
                    text("DELETE FROM rooms WHERE id = :room_id"),
                    {"room_id": room_id},
                )
            for property_id in self.property_ids:
                connection.execute(
                    text("DELETE FROM room_types WHERE property_id = :property_id"),
                    {"property_id": property_id},
                )
                connection.execute(
                    text(
                        "DELETE FROM business_date_state WHERE property_id = :property_id"
                    ),
                    {"property_id": property_id},
                )
                connection.execute(
                    text("DELETE FROM properties WHERE id = :property_id"),
                    {"property_id": property_id},
                )
            for organization_id in self.organization_ids:
                connection.execute(
                    text("DELETE FROM organizations WHERE id = :organization_id"),
                    {"organization_id": organization_id},
                )
            connection.execute(
                text(
                    "SELECT setval(pg_get_serial_sequence('business_date_state', 'id'), 1, false)"
                )
            )

    def test_fresh_install_and_existing_0024_upgrade_use_property_date(self):
        self.assertEqual(self.scripts.get_heads(), [LATEST_REVISION])
        self._assert_schema_guard_rejects_application_objects()

        command.upgrade(self.config, PREVIOUS_REVISION)
        self.assertEqual(self._current_revision(), PREVIOUS_REVISION)
        self._assert_property_scoped_function()

        first_property_id, first_room_type_id = self._create_property(
            "First", date(2026, 10, 1)
        )
        target_property_id, target_room_type_id = self._create_property(
            "Target", date(2026, 10, 2)
        )
        first_state_id = self._business_date_state_id(first_property_id)
        self.assertEqual(first_state_id, 1)

        fresh_room_id = self._create_room(target_property_id, target_room_type_id)
        self._set_room_dirty(fresh_room_id)
        self.assertEqual(self._task_business_date(fresh_room_id), date(2026, 10, 2))

        command.upgrade(self.config, "head")
        self.assertEqual(self._current_revision(), LATEST_REVISION)
        self._assert_property_scoped_function()

        # Model a database whose old 0024 was already applied before the PR.
        with self.engine.begin() as connection:
            connection.execute(text(LEGACY_HOUSEKEEPING_FUNCTION))
            connection.execute(
                text("UPDATE alembic_version SET version_num = :revision"),
                {"revision": PREVIOUS_REVISION},
            )

        legacy_room_id = self._create_room(target_property_id, target_room_type_id)
        with self.assertRaises(IntegrityError):
            self._set_room_dirty(legacy_room_id)
        self.assertEqual(self._task_count(legacy_room_id), 0)

        command.upgrade(self.config, "head")
        self.assertEqual(self._current_revision(), LATEST_REVISION)
        self._assert_property_scoped_function()

        self._set_room_dirty(legacy_room_id)
        self._set_room_available(legacy_room_id)
        self._set_room_dirty(legacy_room_id)
        self.assertEqual(self._task_business_date(legacy_room_id), date(2026, 10, 2))
        self.assertEqual(self._task_count(legacy_room_id), 1)

    def _current_revision(self):
        with self.engine.connect() as connection:
            return connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()

    def _assert_schema_guard_rejects_application_objects(self):
        table_name = f"migration_guard_probe_{uuid4().hex[:10]}"
        with self.engine.begin() as connection:
            connection.execute(text(f'CREATE TABLE public."{table_name}" (id integer)'))
        try:
            with self.assertRaisesRegex(RuntimeError, "no application schema objects"):
                with self.engine.connect() as connection:
                    _require_empty_application_schema(connection)
        finally:
            with self.engine.begin() as connection:
                connection.execute(text(f'DROP TABLE public."{table_name}"'))

    def _assert_property_scoped_function(self):
        with self.engine.connect() as connection:
            definition = (
                connection.execute(
                    text(
                        "SELECT pg_get_functiondef('hms_auto_housekeeping_task_for_dirty_room()'::regprocedure)"
                    )
                )
                .scalar_one()
                .lower()
            )
        self.assertIn("where property_id = new.property_id", definition)
        self.assertIn("for update", definition)
        self.assertIn("on conflict (room_id)", definition)

    def _create_property(self, label, business_date):
        suffix = uuid4().hex[:10]
        with Session(self.engine) as db:
            organization = self.Organization(
                name=f"Migration {label} {suffix}",
                slug=f"migration-{label.lower()}-{suffix}",
            )
            db.add(organization)
            db.flush()
            self.organization_ids.append(organization.id)
            property_ = self.Property(
                organization_id=organization.id,
                name=f"Migration {label}",
                code=f"MIG-{suffix}",
                slug=f"migration-{label.lower()}-{suffix}",
                timezone="UTC",
                currency="PKR",
            )
            db.add(property_)
            db.flush()
            self.property_ids.append(property_.id)
            state = self.BusinessDateState(
                property_id=property_.id,
                current_business_date=business_date,
            )
            room_type = self.RoomType(
                property_id=property_.id,
                name=f"Migration {label} room type {suffix}",
                base_rate=Decimal("100.00"),
            )
            db.add_all([state, room_type])
            db.flush()
            db.commit()
            return property_.id, room_type.id

    def _business_date_state_id(self, property_id):
        with self.engine.connect() as connection:
            return connection.execute(
                text(
                    "SELECT id FROM business_date_state WHERE property_id = :property_id"
                ),
                {"property_id": property_id},
            ).scalar_one()

    def _create_room(self, property_id, room_type_id):
        with Session(self.engine) as db:
            room = self.Room(
                property_id=property_id,
                number=f"MIG-{uuid4().hex[:10]}",
                room_type_id=room_type_id,
                status="available",
            )
            db.add(room)
            db.flush()
            self.room_ids.append(room.id)
            db.commit()
            return room.id

    def _set_room_dirty(self, room_id):
        with self.engine.begin() as connection:
            connection.execute(
                text("UPDATE rooms SET status = 'dirty' WHERE id = :room_id"),
                {"room_id": room_id},
            )

    def _set_room_available(self, room_id):
        with self.engine.begin() as connection:
            connection.execute(
                text("UPDATE rooms SET status = 'available' WHERE id = :room_id"),
                {"room_id": room_id},
            )

    def _task_business_date(self, room_id):
        with self.engine.connect() as connection:
            return connection.execute(
                text(
                    "SELECT business_date FROM housekeeping_tasks WHERE room_id = :room_id"
                ),
                {"room_id": room_id},
            ).scalar_one()

    def _task_count(self, room_id):
        with self.engine.connect() as connection:
            return connection.execute(
                text(
                    "SELECT count(*) FROM housekeeping_tasks WHERE room_id = :room_id"
                ),
                {"room_id": room_id},
            ).scalar_one()


if __name__ == "__main__":
    unittest.main()
