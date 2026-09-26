"""payment attempts, webhook event ledger, admin flag, timestamps

Revision ID: 7c1d2e9a4b10
Revises: 258940d05f40
Create Date: 2026-09-27 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7c1d2e9a4b10"
down_revision: Union[str, Sequence[str], None] = "258940d05f40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # users
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "users",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # bookings
    for column in ("created_at", "updated_at"):
        op.add_column(
            "bookings",
            sa.Column(
                column,
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )
    op.create_index("ix_bookings_user_id", "bookings", ["user_id"])
    op.create_index("ix_bookings_status", "bookings", ["status"])

    # webhook ledger
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("payment_id", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"]),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index("ix_webhook_events_booking_id", "webhook_events", ["booking_id"])

    # carry existing webhook-created payments over to the ledger
    op.execute(
        """
        INSERT INTO webhook_events
            (event_id, booking_id, payment_id, amount, status, outcome, received_at)
        SELECT provider_event_id, booking_id, id, amount, status::text,
               'PROCESSED', created_at
        FROM payments WHERE provider_event_id IS NOT NULL
        """
    )

    # payments: allow several attempts per booking, drop event id column
    op.add_column(
        "payments",
        sa.Column("source", sa.String(length=20), server_default="MOCK", nullable=False),
    )
    op.execute("UPDATE payments SET source = 'WEBHOOK' WHERE provider_event_id IS NOT NULL")
    op.alter_column(
        "payments", "created_at", server_default=sa.text("now()")
    )
    op.drop_index(op.f("ix_payments_provider_event_id"), table_name="payments")
    op.drop_column("payments", "provider_event_id")
    op.drop_constraint("payments_booking_id_key", "payments", type_="unique")
    op.create_index("ix_payments_booking_id", "payments", ["booking_id"])


def downgrade() -> None:
    op.drop_index("ix_payments_booking_id", table_name="payments")
    op.create_unique_constraint("payments_booking_id_key", "payments", ["booking_id"])
    op.add_column(
        "payments",
        sa.Column("provider_event_id", sa.String(length=255), nullable=True),
    )
    op.execute(
        """
        UPDATE payments p SET provider_event_id = w.event_id
        FROM webhook_events w WHERE w.payment_id = p.id
        """
    )
    op.create_index(
        op.f("ix_payments_provider_event_id"),
        "payments",
        ["provider_event_id"],
        unique=True,
    )
    op.alter_column("payments", "created_at", server_default=None)
    op.drop_column("payments", "source")

    op.drop_index("ix_webhook_events_booking_id", table_name="webhook_events")
    op.drop_table("webhook_events")

    op.drop_index("ix_bookings_status", table_name="bookings")
    op.drop_index("ix_bookings_user_id", table_name="bookings")
    op.drop_column("bookings", "updated_at")
    op.drop_column("bookings", "created_at")

    op.drop_column("users", "created_at")
    op.drop_column("users", "is_admin")
