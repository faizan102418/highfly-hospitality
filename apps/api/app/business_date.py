from __future__ import annotations

from datetime import date

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import BusinessDateState


def _require_property_id(property_id: int | None) -> int:
    if property_id is None:
        raise HTTPException(status_code=409, detail="An authorized property must be selected before using business-date state")
    return property_id


def get_current_business_date(db: Session, *, property_id: int | None = None, fallback_to_today: bool = False) -> date:
    property_id = _require_property_id(property_id)
    state = db.scalar(select(BusinessDateState).where(BusinessDateState.property_id == property_id))
    if state and state.current_business_date:
        return state.current_business_date
    if fallback_to_today:
        return date.today()
    raise HTTPException(status_code=503, detail="Business date is not initialized for this property")


def lock_current_business_date(db: Session, *, property_id: int | None = None) -> BusinessDateState:
    """Lock the business-date row belonging to the selected property."""
    property_id = _require_property_id(property_id)
    state = db.scalar(select(BusinessDateState).where(BusinessDateState.property_id == property_id).with_for_update())
    if state is None or state.current_business_date is None:
        raise HTTPException(status_code=503, detail="Business date is not initialized for this property")
    return state
