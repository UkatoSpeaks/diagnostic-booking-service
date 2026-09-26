from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.models import BookingStatus


class BookingCreate(BaseModel):
    test_id: int
    centre_id: int
    appointment_at: datetime


class BookingResponse(BaseModel):
    id: int
    user_id: int
    test_id: int
    centre_id: int
    appointment_at: datetime
    amount: Decimal
    status: BookingStatus

    model_config = {"from_attributes": True}