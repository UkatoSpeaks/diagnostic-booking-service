from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.models.models import BookingStatus, PaymentStatus


class PaymentCreate(BaseModel):
    booking_id: int
    simulate: PaymentStatus | None = Field(
        default=None,
        description="Force the mock outcome. Random (weighted) when omitted.",
    )


class PaymentWebhook(BaseModel):
    event_id: str = Field(min_length=1, max_length=255)
    booking_id: int
    amount: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    status: PaymentStatus


class PaymentResponse(BaseModel):
    id: int
    booking_id: int
    amount: Decimal
    status: PaymentStatus
    source: str
    created_at: datetime

    model_config = {"from_attributes": True}


class WebhookResponse(BaseModel):
    event_id: str
    booking_id: int
    booking_status: BookingStatus
    payment_id: int | None
    outcome: Literal["PROCESSED", "IGNORED"]
    duplicate: bool = False
