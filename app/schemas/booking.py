from datetime import datetime
from decimal import Decimal

from pydantic import AwareDatetime, BaseModel

from app.models.models import BookingStatus


class BookingCreate(BaseModel):
    test_id: int
    centre_id: int
    # Timezone-aware ISO 8601 timestamp; naive values are rejected.
    appointment_at: AwareDatetime


class BookingResponse(BaseModel):
    id: int
    user_id: int
    test_id: int
    centre_id: int
    appointment_at: datetime
    amount: Decimal
    status: BookingStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
