from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.models import (
    Booking,
    BookingStatus,
    Payment,
    PaymentStatus,
    User,
)
from app.schemas.payment import (
    PaymentCreate,
    PaymentResponse,
    PaymentWebhook,
)

router = APIRouter(prefix="/payments", tags=["Payments"])


@router.post(
    "/",
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_mock_payment(
    data: PaymentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    booking = db.get(Booking, data.booking_id)

    if booking is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    if booking.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this booking",
        )

    if booking.status != BookingStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Booking is already {booking.status.value}",
        )

    existing_payment = db.scalar(
        select(Payment).where(Payment.booking_id == booking.id)
    )

    if existing_payment:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Payment already exists for this booking",
        )

    # Deterministic mock payment.
    # For now, every direct mock payment succeeds.
    payment = Payment(
        booking_id=booking.id,
        amount=booking.amount,
        status=PaymentStatus.SUCCESS,
    )

    booking.status = BookingStatus.CONFIRMED

    db.add(payment)

    try:
        db.commit()
        db.refresh(payment)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Payment already exists for this booking",
        )

    return payment


@router.post(
    "/webhook/",
    response_model=PaymentResponse,
)
def payment_webhook(
    data: PaymentWebhook,
    db: Session = Depends(get_db),
):
    # 1. Check whether this provider event was already processed.
    existing_event = db.scalar(
        select(Payment).where(
            Payment.provider_event_id == data.event_id
        )
    )

    if existing_event:
        if (
            existing_event.booking_id != data.booking_id
            or existing_event.amount != data.amount
            or existing_event.status != data.status
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Event ID already processed with different payload",
            )

        # Idempotent response.
        return existing_event

    # 2. Find booking.
    booking = db.get(Booking, data.booking_id)

    if booking is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    # 3. Verify payment amount.
    if booking.amount != data.amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payment amount does not match booking amount",
        )

    # 4. Prevent multiple payments for the same booking.
    existing_payment = db.scalar(
        select(Payment).where(Payment.booking_id == booking.id)
    )

    if existing_payment:
        if existing_payment.status == data.status:
            return existing_payment

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Booking already has a payment with a different status",
        )

    # 5. Booking must still be pending.
    if booking.status != BookingStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Booking is already {booking.status.value}",
        )

    # 6. Create payment.
    payment = Payment(
        booking_id=booking.id,
        amount=data.amount,
        status=data.status,
        provider_event_id=data.event_id,
    )

    # 7. Update booking.
    if data.status == PaymentStatus.SUCCESS:
        booking.status = BookingStatus.CONFIRMED
    else:
        booking.status = BookingStatus.FAILED

    db.add(payment)

    try:
        db.commit()
        db.refresh(payment)
    except IntegrityError:
        db.rollback()

        # Handles concurrent duplicate webhook requests.
        existing_payment = db.scalar(
            select(Payment).where(
                Payment.provider_event_id == data.event_id
            )
        )

        if existing_payment:
            return existing_payment

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Payment could not be processed",
        )

    return payment