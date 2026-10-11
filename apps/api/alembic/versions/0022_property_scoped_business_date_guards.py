"""Make operational business-date guards tenant-aware.

Revision ID: 0022_property_scoped_business_date_guards
Revises: 0021_property_ownership
"""

from alembic import op
import sqlalchemy as sa


revision = "0022_property_scoped_business_date_guards"
down_revision = "0021_property_ownership"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # Every guard resolves the owning property from the row being written or
    # from its authoritative parent. Never assume a global singleton row (id=1).
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION hms_guard_financial_posting_business_date()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            v_current_date date;
            v_last_closed_business_date date;
        BEGIN
            SELECT current_business_date, last_closed_business_date
              INTO v_current_date, v_last_closed_business_date
              FROM business_date_state
             WHERE property_id = NEW.property_id
             FOR UPDATE;

            IF NOT FOUND THEN
                RAISE EXCEPTION USING ERRCODE='55000',
                    MESSAGE=format('Business date is not initialized for property %s', NEW.property_id);
            END IF;
            IF NEW.business_date <> v_current_date THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE=format('Financial posting date %s is not the current business date %s for property %s',
                                   NEW.business_date, v_current_date, NEW.property_id);
            END IF;
            IF v_last_closed_business_date IS NOT NULL
               AND v_last_closed_business_date >= NEW.business_date THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE=format('Business date %s is closed for financial posting for property %s',
                                   NEW.business_date, NEW.property_id);
            END IF;
            RETURN NEW;
        END; $$;
    """))

    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION hms_guard_restaurant_order_business_date()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE v_current_date date;
        BEGIN
            SELECT current_business_date INTO v_current_date
              FROM business_date_state WHERE property_id = NEW.property_id FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION USING ERRCODE='55000',
                    MESSAGE=format('Business date is not initialized for property %s', NEW.property_id);
            END IF;
            IF NEW.business_date <> v_current_date THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE=format('Restaurant order date %s is not the current business date %s for property %s',
                                   NEW.business_date, v_current_date, NEW.property_id);
            END IF;
            RETURN NEW;
        END; $$;
    """))

    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION hms_guard_stock_movement_business_date()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE v_property_id integer; v_current_date date;
        BEGIN
            SELECT property_id INTO v_property_id FROM stock_items WHERE id = NEW.stock_item_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION USING ERRCODE='23503', MESSAGE='Stock item does not exist';
            END IF;
            SELECT current_business_date INTO v_current_date
              FROM business_date_state WHERE property_id = v_property_id FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION USING ERRCODE='55000',
                    MESSAGE=format('Business date is not initialized for property %s', v_property_id);
            END IF;
            IF NEW.business_date <> v_current_date THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE=format('Stock movement date %s is not the current business date %s for property %s',
                                   NEW.business_date, v_current_date, v_property_id);
            END IF;
            RETURN NEW;
        END; $$;
    """))

    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION hms_guard_stock_operation_business_date()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE v_property_id integer; v_current_date date;
        BEGIN
            SELECT property_id INTO v_property_id FROM stock_items WHERE id = NEW.stock_item_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION USING ERRCODE='23503', MESSAGE='Stock item does not exist';
            END IF;
            SELECT current_business_date INTO v_current_date
              FROM business_date_state WHERE property_id = v_property_id FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION USING ERRCODE='55000',
                    MESSAGE=format('Business date is not initialized for property %s', v_property_id);
            END IF;
            IF NEW.business_date <> v_current_date THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE=format('Stock operation date %s is not the current business date %s for property %s',
                                   NEW.business_date, v_current_date, v_property_id);
            END IF;
            RETURN NEW;
        END; $$;
    """))

    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION hms_guard_purchase_order_business_date()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE v_current_date date;
        BEGIN
            SELECT current_business_date INTO v_current_date
              FROM business_date_state WHERE property_id = NEW.property_id FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION USING ERRCODE='55000',
                    MESSAGE=format('Business date is not initialized for property %s', NEW.property_id);
            END IF;
            IF NEW.business_date <> v_current_date THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE=format('Purchase order date %s is not the current business date %s for property %s',
                                   NEW.business_date, v_current_date, NEW.property_id);
            END IF;
            RETURN NEW;
        END; $$;
    """))

    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION hms_guard_purchase_receipt_business_date()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE v_property_id integer; v_current_date date;
        BEGIN
            SELECT property_id INTO v_property_id
              FROM purchase_orders WHERE id = NEW.purchase_order_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION USING ERRCODE='23503', MESSAGE='Purchase order does not exist';
            END IF;
            SELECT current_business_date INTO v_current_date
              FROM business_date_state WHERE property_id = v_property_id FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION USING ERRCODE='55000',
                    MESSAGE=format('Business date is not initialized for property %s', v_property_id);
            END IF;
            IF NEW.business_date <> v_current_date THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE=format('Goods receipt date %s is not the current business date %s for property %s',
                                   NEW.business_date, v_current_date, v_property_id);
            END IF;
            RETURN NEW;
        END; $$;
    """))

    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION hms_guard_housekeeping_business_date()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE v_property_id integer; v_current_date date;
        BEGIN
            SELECT property_id INTO v_property_id FROM rooms WHERE id = NEW.room_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION USING ERRCODE='23503', MESSAGE='Room does not exist';
            END IF;
            SELECT current_business_date INTO v_current_date
              FROM business_date_state WHERE property_id = v_property_id FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION USING ERRCODE='55000',
                    MESSAGE=format('Business date is not initialized for property %s', v_property_id);
            END IF;
            IF NEW.business_date <> v_current_date THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE=format('Housekeeping task date %s is not current business date %s for property %s',
                                   NEW.business_date, v_current_date, v_property_id);
            END IF;
            RETURN NEW;
        END; $$;
    """))

    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION hms_guard_maintenance_business_date()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE v_property_id integer; v_current_date date;
        BEGIN
            SELECT property_id INTO v_property_id FROM rooms WHERE id = NEW.room_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION USING ERRCODE='23503', MESSAGE='Room does not exist';
            END IF;
            SELECT current_business_date INTO v_current_date
              FROM business_date_state WHERE property_id = v_property_id FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION USING ERRCODE='55000',
                    MESSAGE=format('Business date is not initialized for property %s', v_property_id);
            END IF;
            IF NEW.business_date <> v_current_date THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE=format('Maintenance block date %s is not current business date %s for property %s',
                                   NEW.business_date, v_current_date, v_property_id);
            END IF;
            RETURN NEW;
        END; $$;
    """))

    # The dirty-room automation must use the room's property as well.
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION hms_auto_housekeeping_task_for_dirty_room()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE v_current_date date;
        BEGIN
            IF NEW.status='dirty' AND OLD.status IS DISTINCT FROM 'dirty' THEN
                SELECT current_business_date INTO v_current_date
                  FROM business_date_state WHERE property_id = NEW.property_id;
                IF v_current_date IS NULL THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE=format('Business date is not initialized for property %s', NEW.property_id);
                END IF;
                INSERT INTO housekeeping_tasks (
                    task_no, room_id, business_date, task_type, status, priority, reason, created_at, updated_at
                ) VALUES (
                    'HK-' || to_char(v_current_date, 'YYYYMMDD') || '-' || NEW.id,
                    NEW.id, v_current_date, 'cleaning', 'pending', 'normal',
                    'Automatically created when room became dirty', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                );
            END IF;
            RETURN NEW;
        END; $$;
    """))


def downgrade() -> None:
    raise RuntimeError(
        "Property-scoped business-date guards must not be downgraded to singleton behavior."
    )
