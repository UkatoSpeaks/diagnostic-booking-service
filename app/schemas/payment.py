from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.models import PaymentStatus


class PaymentCreate(BaseModel):
    booking_id: int


class PaymentWebhook(BaseModel):
    event_id: str = Field(min_length=1, max_length=255)
    booking_id: int
    amount: Decimal = Field(gt=0)
    status: PaymentStatus


class PaymentResponse(BaseModel):
    id: int
    booking_id: int
    amount: Decimal
    status: PaymentStatus
    provider_event_id: str | None
    created_at: datetime

    model_config = {"from_attributes": True}