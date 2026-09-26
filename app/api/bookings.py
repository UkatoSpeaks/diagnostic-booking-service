from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.services.payments import lock_booking
from app.models.models import (
    Booking,
    BookingStatus,
    CentreTest,
    User,
)
from app.schemas.booking import BookingCreate, BookingResponse


router = APIRouter(
    prefix="/bookings",
    tags=["Bookings"],
)


@router.post(
    "/",
    response_model=BookingResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_booking(
    data: BookingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Appointment must be in the future
    if data.appointment_at <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Appointment must be in the future",
        )

    # Verify that this test is available at this centre
    centre_test = db.scalar(
        select(CentreTest).where(
            CentreTest.centre_id == data.centre_id,
            CentreTest.test_id == data.test_id,
        )
    )

    if not centre_test:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Test is not available at this diagnostic centre",
        )

    booking = Booking(
        user_id=current_user.id,
        test_id=data.test_id,
        centre_id=data.centre_id,
        appointment_at=data.appointment_at,
        amount=centre_test.price,
        status=BookingStatus.PENDING,
    )

    db.add(booking)
    db.commit()
    db.refresh(booking)

    return booking


@router.get(
    "/",
    response_model=list[BookingResponse],
)
def list_my_bookings(
    status_filter: BookingStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(Booking).where(Booking.user_id == current_user.id)

    if status_filter is not None:
        query = query.where(Booking.status == status_filter)

    return db.scalars(
        query.order_by(Booking.appointment_at.desc(), Booking.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()


@router.get(
    "/{booking_id}",
    response_model=BookingResponse,
)
def get_booking(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = db.get(Booking, booking_id)

    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    # Prevent users from viewing another user's booking
    if booking.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to access this booking",
        )

    return booking


@router.post(
    "/{booking_id}/cancel",
    response_model=BookingResponse,
)
def cancel_booking(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = lock_booking(db, booking_id)

    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    if booking.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to access this booking",
        )

    # Paid bookings would need a refund flow, which is out of scope.
    if booking.status not in (BookingStatus.PENDING, BookingStatus.FAILED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Booking is {booking.status.value} and cannot be cancelled",
        )

    booking.status = BookingStatus.CANCELLED
    db.commit()
    db.refresh(booking)

    return booking
