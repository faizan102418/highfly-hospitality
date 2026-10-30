"""Make automatic checkout housekeeping creation safe under duplicate handoffs."""
from alembic import context, op
import sqlalchemy as sa

revision = "0024_housekeeping_task_conflict"
down_revision = "0023_property_date_guards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # This migration replaces a PostgreSQL trigger function; SQLite has no equivalent.
    if context.get_context().dialect.name != "postgresql":
        return
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION hms_auto_housekeeping_task_for_dirty_room()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE current_date_value date;
        BEGIN
            IF NEW.status='dirty' AND OLD.status IS DISTINCT FROM 'dirty' THEN
                SELECT current_business_date INTO current_date_value
                FROM business_date_state
                WHERE property_id = NEW.property_id
                FOR UPDATE;
                IF current_date_value IS NULL THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE=format('Business date is not initialized for property %s', NEW.property_id);
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
    """))


def downgrade() -> None:
    raise RuntimeError(
        "Housekeeping task creation is operationally authoritative; "
        "restore a verified backup instead of destructive rollback."
    )
