from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BookingStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )

    bookings: Mapped[list["Booking"]] = relationship(back_populates="user")


class DiagnosticCentre(Base):
    __tablename__ = "diagnostic_centres"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    location: Mapped[str] = mapped_column(Text)

    tests: Mapped[list["CentreTest"]] = relationship(
        back_populates="centre",
        cascade="all, delete-orphan",
    )


class DiagnosticTest(Base):
    __tablename__ = "diagnostic_tests"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    centres: Mapped[list["CentreTest"]] = relationship(
        back_populates="test",
        cascade="all, delete-orphan",
    )

    bookings: Mapped[list["Booking"]] = relationship(back_populates="test")


class CentreTest(Base):
    __tablename__ = "centre_tests"

    id: Mapped[int] = mapped_column(primary_key=True)

    centre_id: Mapped[int] = mapped_column(
        ForeignKey("diagnostic_centres.id", ondelete="CASCADE")
    )

    test_id: Mapped[int] = mapped_column(
        ForeignKey("diagnostic_tests.id", ondelete="CASCADE")
    )

    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    centre: Mapped["DiagnosticCentre"] = relationship(back_populates="tests")
    test: Mapped["DiagnosticTest"] = relationship(back_populates="centres")

    __table_args__ = (
        UniqueConstraint(
            "centre_id",
            "test_id",
            name="uq_centre_test",
        ),
    )


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        Index("ix_bookings_user_id", "user_id"),
        Index("ix_bookings_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    test_id: Mapped[int] = mapped_column(ForeignKey("diagnostic_tests.id"))
    centre_id: Mapped[int] = mapped_column(ForeignKey("diagnostic_centres.id"))

    appointment_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Price snapshot taken at booking time; later catalog price changes
    # do not affect existing bookings.
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    status: Mapped[BookingStatus] = mapped_column(
        SQLEnum(BookingStatus),
        default=BookingStatus.PENDING,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
    )

    user: Mapped["User"] = relationship(back_populates="bookings")
    test: Mapped["DiagnosticTest"] = relationship(back_populates="bookings")
    centre: Mapped["DiagnosticCentre"] = relationship()
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="booking", order_by="Payment.id"
    )


class Payment(Base):
    """One payment attempt. A booking may have several (failed retries)."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)

    booking_id: Mapped[int] = mapped_column(
        ForeignKey("bookings.id"), index=True
    )

    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    status: Mapped[PaymentStatus] = mapped_column(SQLEnum(PaymentStatus))

    # MOCK (POST /payments/) or WEBHOOK (provider callback)
    source: Mapped[str] = mapped_column(
        String(20), default="MOCK", server_default="MOCK"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )

    booking: Mapped["Booking"] = relationship(back_populates="payments")


class WebhookEvent(Base):
    """Ledger of processed provider events; event_id uniqueness gives idempotency."""

    __tablename__ = "webhook_events"

    id: Mapped[int] = mapped_column(primary_key=True)

    event_id: Mapped[str] = mapped_column(String(255), unique=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), index=True)
    payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("payments.id"), nullable=True
    )

    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    status: Mapped[str] = mapped_column(String(20))
    # PROCESSED (applied to the booking) or IGNORED (booking was not payable)
    outcome: Mapped[str] = mapped_column(String(20))

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
