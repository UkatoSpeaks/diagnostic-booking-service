"""Payment state transitions shared by the mock endpoint and the webhook."""
import hashlib
import hmac
import random
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.models import Booking, BookingStatus, Payment, PaymentStatus

# A booking can be paid while PENDING, or retried after a FAILED attempt.
PAYABLE_STATUSES = {BookingStatus.PENDING, BookingStatus.FAILED}


def lock_booking(db: Session, booking_id: int) -> Booking | None:
    """Load a booking with a row lock so concurrent payments serialise."""
    return db.scalar(
        select(Booking)
        .where(Booking.id == booking_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def pick_mock_outcome(requested: PaymentStatus | None) -> PaymentStatus:
    if requested is not None:
        return requested
    if random.random() < settings.MOCK_PAYMENT_SUCCESS_RATE:
        return PaymentStatus.SUCCESS
    return PaymentStatus.FAILED


def ensure_payable(booking: Booking) -> None:
    if booking.status not in PAYABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Booking is already {booking.status.value}",
        )


def record_payment(
    db: Session,
    booking: Booking,
    outcome: PaymentStatus,
    amount: Decimal,
    source: str,
) -> Payment:
    """Create a payment attempt and move the booking to its new status.

    The caller must hold the booking lock and have checked the booking is
    payable.
    """
    payment = Payment(
        booking_id=booking.id,
        amount=amount,
        status=outcome,
        source=source,
    )
    booking.status = (
        BookingStatus.CONFIRMED
        if outcome == PaymentStatus.SUCCESS
        else BookingStatus.FAILED
    )
    db.add(payment)
    db.flush()
    return payment


def sign_payload(body: bytes) -> str:
    return hmac.new(
        settings.WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()


def verify_signature(body: bytes, signature: str | None) -> bool:
    if not signature:
        return False
    return hmac.compare_digest(sign_payload(body), signature.strip())
