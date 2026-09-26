import logging

from fastapi.concurrency import run_in_threadpool
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.models import (
    Booking,
    BookingStatus,
    PaymentStatus,
    User,
    WebhookEvent,
)
from app.schemas.payment import (
    PaymentCreate,
    PaymentResponse,
    PaymentWebhook,
    WebhookResponse,
)
from app.services import payments as payment_service

logger = logging.getLogger(__name__)

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
    """Simulate a payment. Result is SUCCESS or FAILED and updates the booking.

    A FAILED booking may be paid again; CONFIRMED and CANCELLED may not.
    """
    booking = payment_service.lock_booking(db, data.booking_id)

    if booking is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Booking not found")

    if booking.user_id != current_user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You do not have access to this booking"
        )

    payment_service.ensure_payable(booking)

    outcome = payment_service.pick_mock_outcome(data.simulate)
    payment = payment_service.record_payment(
        db, booking, outcome, booking.amount, source="MOCK"
    )
    db.commit()
    db.refresh(payment)

    logger.info(
        "mock payment processed booking_id=%s payment_id=%s status=%s",
        booking.id,
        payment.id,
        outcome.value,
    )
    return payment


@router.post("/webhook/", response_model=WebhookResponse)
async def payment_webhook(
    request: Request,
    x_signature: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Idempotent provider callback, authenticated by HMAC-SHA256 signature.

    The signature is the hex HMAC of the raw request body using
    WEBHOOK_SECRET, sent in the ``X-Signature`` header.
    """
    body = await request.body()

    if not payment_service.verify_signature(body, x_signature):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid webhook signature")

    try:
        data = PaymentWebhook.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(
            422,
            detail=exc.errors(include_url=False, include_context=False, include_input=False),
        )

    # DB work is synchronous; keep it off the event loop.
    return await run_in_threadpool(_process_webhook, db, data)


def _process_webhook(db: Session, data: PaymentWebhook) -> WebhookResponse:
    # Locking the booking serialises concurrent deliveries of the same event.
    booking = payment_service.lock_booking(db, data.booking_id)

    if booking is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Booking not found")

    existing = db.scalar(
        select(WebhookEvent).where(WebhookEvent.event_id == data.event_id)
    )
    if existing is not None:
        return _duplicate_response(existing, booking.status, data)

    if booking.amount != data.amount:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Payment amount does not match booking amount",
        )

    payment = None
    outcome = "IGNORED"

    # Events for bookings that are no longer payable (already paid or
    # cancelled) are recorded and acknowledged with 200 so the provider
    # stops retrying, but they never change the booking. A repeated failure
    # for an already FAILED booking is likewise a no-op.
    is_repeat_failure = (
        booking.status == BookingStatus.FAILED
        and data.status == PaymentStatus.FAILED
    )
    if booking.status in payment_service.PAYABLE_STATUSES and not is_repeat_failure:
        payment = payment_service.record_payment(
            db, booking, data.status, data.amount, source="WEBHOOK"
        )
        outcome = "PROCESSED"

    event = WebhookEvent(
        event_id=data.event_id,
        booking_id=booking.id,
        payment_id=payment.id if payment else None,
        amount=data.amount,
        status=data.status.value,
        outcome=outcome,
    )
    db.add(event)

    try:
        db.commit()
    except IntegrityError:
        # Backstop: same event_id inserted by a concurrent request.
        db.rollback()
        existing = db.scalar(
            select(WebhookEvent).where(WebhookEvent.event_id == data.event_id)
        )
        if existing is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Webhook event could not be processed"
            )
        current = db.get(Booking, data.booking_id)
        return _duplicate_response(existing, current.status, data)

    logger.info(
        "webhook processed event_id=%s booking_id=%s outcome=%s",
        data.event_id,
        booking.id,
        outcome,
    )
    return WebhookResponse(
        event_id=event.event_id,
        booking_id=booking.id,
        booking_status=booking.status,
        payment_id=event.payment_id,
        outcome=outcome,
    )


def _duplicate_response(
    existing: WebhookEvent, booking_status: BookingStatus, data: PaymentWebhook
) -> WebhookResponse:
    if (
        existing.booking_id != data.booking_id
        or existing.amount != data.amount
        or existing.status != data.status.value
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Event ID already processed with a different payload",
        )
    return WebhookResponse(
        event_id=existing.event_id,
        booking_id=existing.booking_id,
        booking_status=booking_status,
        payment_id=existing.payment_id,
        outcome=existing.outcome,
        duplicate=True,
    )
