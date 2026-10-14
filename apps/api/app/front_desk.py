from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .auth import require_roles
from .db import get_db
from .business_date import get_current_business_date
from .financial_authority import folio_ledger_summary
from .ledger import post_deposit_received
from .models import AuditLog, DepositTransaction, Folio, FolioItem, Guest, Reservation, ReservationRoom, Room, RoomType, StayOccupant, StayRateSegment, User
from .pms_core import Stay
from .tenancy import resolve_authorized_property

router = APIRouter(tags=["front-desk-2"])
MONEY = Decimal("0.01")


class WalkInRoom(BaseModel):
    room_id: int
    occupant_guest_id: int | None = None
    agreed_rate: Decimal = Field(ge=0)
    discount_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    fixed_discount: Decimal = Field(default=Decimal("0"), ge=0)


class WalkInCreate(BaseModel):
    guest_id: int
    rooms: list[WalkInRoom] = Field(min_length=1)
    check_out: date
    payment_policy: str = Field(default="at_checkout", pattern="^(at_checkin|at_checkout|partial)$")
    deposit_received: Decimal = Field(default=Decimal("0"), ge=0)
    deposit_method: str = Field(default="cash", max_length=30)
    notes: str | None = Field(default=None, max_length=1000)


def money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def audit(db: Session, user_id: int, action: str, entity_type: str, entity_id: int | str, details: dict) -> None:
    db.add(AuditLog(user_id=user_id, action=action, entity_type=entity_type, entity_id=str(entity_id), details=json.dumps(details)))


def folio_balance(db: Session, folio: Folio) -> Decimal:
    return folio_ledger_summary(db, folio.id).balance


def available_for_walk_in(db: Session, room_id: int, business_date: date) -> bool:
    room = db.get(Room, room_id)
    if not room or room.status in ("dirty", "out_of_order", "occupied", "reserved"):
        return False
    conflict = db.scalar(select(ReservationRoom.reservation_id).join(Reservation, Reservation.id == ReservationRoom.reservation_id).where(ReservationRoom.room_id == room_id, Reservation.status.in_(("reserved", "checked_in")), Reservation.check_in <= business_date, Reservation.check_out > business_date).limit(1))
    return conflict is None


def room_stay_ids(db: Session, reservation_id: int) -> list[int]:
    return db.scalars(select(Stay.id).where(Stay.reservation_id == reservation_id).order_by(Stay.id)).all()



def atomic_checkout(
    reservation_id: int,
    db: Session,
    user: User,
) -> dict:
    """Authoritative checkout state transition shared by the API checkout route."""
    reservation = db.get(Reservation, reservation_id)
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")
    # Checkout mutates the reservation, folio, stay records, and rooms. Resolve
    # explicit property access before checking state or posting any charges.
    property_ = resolve_authorized_property(db, user.id, reservation.property_id)
    if reservation.status != "checked_in":
        raise HTTPException(status_code=409, detail="Reservation is not checked in")

    folio = db.scalar(
        select(Folio)
        .where(Folio.reservation_id == reservation.id)
        .order_by(Folio.id)
        .limit(1)
    )
    if not folio:
        raise HTTPException(status_code=409, detail="Reservation has no folio")
    if folio.status != "open":
        raise HTTPException(status_code=409, detail="Folio is already closed")

    # Validate every room and guest reference before posting charges or mutating
    # checkout state. Legacy/imported ReservationRoom and Stay rows may otherwise
    # point at records owned by another property.
    room_ids = db.scalars(
        select(ReservationRoom.room_id).where(ReservationRoom.reservation_id == reservation.id)
    ).all()
    stays = db.scalars(
        select(Stay).where(Stay.reservation_id == reservation.id).order_by(Stay.id)
    ).all()
    referenced_room_ids = set(room_ids) | {stay.room_id for stay in stays}
    if not room_ids or not referenced_room_ids:
        raise HTTPException(status_code=409, detail="Reservation has an invalid room assignment")
    rooms = db.scalars(select(Room).where(Room.id.in_(referenced_room_ids))).all()
    rooms_by_id = {room.id: room for room in rooms}
    if len(rooms_by_id) != len(referenced_room_ids) or any(
        room.property_id != property_.id for room in rooms
    ):
        raise HTTPException(status_code=409, detail="Reservation has an invalid room assignment")

    stay_ids = [stay.id for stay in stays]
    guest_ids = {reservation.guest_id}
    guest_ids.update(stay.guest_id for stay in stays if stay.guest_id is not None)
    if stay_ids:
        guest_ids.update(
            db.scalars(
                select(StayOccupant.guest_id).where(StayOccupant.stay_id.in_(stay_ids))
            ).all()
        )
    guest_ids.discard(None)
    guests = db.scalars(select(Guest).where(Guest.id.in_(guest_ids))).all() if guest_ids else []
    if len({guest.id for guest in guests}) != len(guest_ids) or any(
        guest.property_id != property_.id for guest in guests
    ):
        raise HTTPException(status_code=409, detail="Reservation has an invalid guest assignment")

    # Final checkout must first reconcile any room night that belongs to the
    # current hotel business date. The reconciler is idempotent and uses the
    # existing authoritative financial ledger.
    business_date = get_current_business_date(db)
    post_accrued_room_charges(db, reservation, folio, business_date, user.id)

    balance = folio_balance(db, folio)
    if balance != Decimal("0.00"):
        raise HTTPException(
            status_code=409,
            detail=f"Guest must settle the folio before checkout; outstanding balance is {balance}",
        )

    checkout_at = datetime.utcnow()

    folio.status = "closed"
    reservation.status = "checked_out"

    for stay in stays:
        stay.status = "completed"
        stay.actual_check_out = stay.actual_check_out or checkout_at

    for room_id in room_ids:
        room = rooms_by_id[room_id]
        if room.status == "occupied":
            room.status = "dirty"

    audit(
        db,
        user.id,
        "atomic_checkout",
        "reservation",
        reservation.id,
        {
            "folio_id": folio.id,
            "room_ids": room_ids,
            "business_date": str(business_date),
            "checked_out_at": checkout_at.isoformat(),
        },
    )
    db.commit()

    return {
        "reservation_id": reservation.id,
        "folio_id": folio.id,
        "status": reservation.status,
        "folio_status": folio.status,
        "room_ids": room_ids,
        "room_status": "dirty",
    }


def post_accrued_room_charges(
    db: Session,
    reservation: Reservation,
    folio: Folio,
    business_date: date,
    user_id: int,
) -> int:
    """Delegate checkout room-night posting to the exact stay/date reconciler."""
    from .room_charge_integrity import post_accrued_room_charges as reconcile_room_charges
    return reconcile_room_charges(db, reservation, folio, business_date, user_id)

