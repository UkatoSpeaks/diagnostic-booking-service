from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.main import app
from app.models.models import Payment, WebhookEvent


def event(booking, event_id="evt_1", status="SUCCESS", amount=500):
    return {
        "event_id": event_id,
        "booking_id": booking["id"],
        "amount": amount,
        "status": status,
    }


def count(model):
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(model))


def test_success_event_confirms_booking(booking, user_headers, post_webhook, get_booking):
    response = post_webhook(event(booking))

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "PROCESSED"
    assert body["duplicate"] is False
    assert body["booking_status"] == "CONFIRMED"
    assert get_booking(booking["id"], user_headers)["status"] == "CONFIRMED"


def test_failed_event_marks_booking_failed(booking, user_headers, post_webhook, get_booking):
    response = post_webhook(event(booking, status="FAILED"))

    assert response.status_code == 200
    assert get_booking(booking["id"], user_headers)["status"] == "FAILED"


def test_duplicate_event_is_idempotent(booking, user_headers, post_webhook, get_booking):
    first = post_webhook(event(booking))
    second = post_webhook(event(booking))
    third = post_webhook(event(booking))

    assert [r.status_code for r in (first, second, third)] == [200, 200, 200]
    assert first.json()["payment_id"] == second.json()["payment_id"]
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True
    assert count(Payment) == 1
    assert count(WebhookEvent) == 1
    assert get_booking(booking["id"], user_headers)["status"] == "CONFIRMED"


def test_duplicate_failed_event_does_not_create_extra_payments(booking, post_webhook):
    post_webhook(event(booking, status="FAILED"))
    post_webhook(event(booking, status="FAILED"))

    assert count(Payment) == 1


def test_same_event_id_with_different_payload_conflicts(booking, post_webhook):
    post_webhook(event(booking))

    response = post_webhook(event(booking, status="FAILED"))

    assert response.status_code == 409
    assert count(Payment) == 1


def test_concurrent_duplicate_events_create_one_payment(booking, user_headers, get_booking):
    from app.services.payments import sign_payload
    import json

    body = json.dumps(event(booking, "evt_race")).encode()
    headers = {"Content-Type": "application/json", "X-Signature": sign_payload(body)}

    def send(_):
        return TestClient(app).post("/payments/webhook/", content=body, headers=headers)

    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(send, range(6)))

    assert all(r.status_code == 200 for r in responses)
    assert sum(1 for r in responses if not r.json()["duplicate"]) == 1
    assert count(Payment) == 1
    assert count(WebhookEvent) == 1
    assert get_booking(booking["id"], user_headers)["status"] == "CONFIRMED"


def test_different_event_after_success_is_ignored(booking, user_headers, post_webhook, get_booking):
    post_webhook(event(booking, "evt_a"))

    late_failure = post_webhook(event(booking, "evt_b", status="FAILED"))

    assert late_failure.status_code == 200
    assert late_failure.json()["outcome"] == "IGNORED"
    assert count(Payment) == 1
    assert get_booking(booking["id"], user_headers)["status"] == "CONFIRMED"


def test_success_after_failure_recovers_booking(booking, user_headers, post_webhook, get_booking):
    post_webhook(event(booking, "evt_a", status="FAILED"))

    response = post_webhook(event(booking, "evt_b", status="SUCCESS"))

    assert response.json()["outcome"] == "PROCESSED"
    assert get_booking(booking["id"], user_headers)["status"] == "CONFIRMED"
    assert count(Payment) == 2


def test_event_for_cancelled_booking_is_ignored(client, booking, user_headers, post_webhook, get_booking):
    client.post(f"/bookings/{booking['id']}/cancel", headers=user_headers)

    response = post_webhook(event(booking))

    assert response.status_code == 200
    assert response.json()["outcome"] == "IGNORED"
    assert get_booking(booking["id"], user_headers)["status"] == "CANCELLED"
    assert count(Payment) == 0


def test_wrong_amount_rejected(booking, user_headers, post_webhook, get_booking):
    response = post_webhook(event(booking, amount=9999))

    assert response.status_code == 400
    assert count(Payment) == 0
    assert get_booking(booking["id"], user_headers)["status"] == "PENDING"


def test_unknown_booking(post_webhook):
    response = post_webhook(
        {"event_id": "evt_x", "booking_id": 99999, "amount": 500, "status": "SUCCESS"}
    )

    assert response.status_code == 404


def test_missing_or_bad_signature_rejected(booking, user_headers, post_webhook, get_booking):
    assert post_webhook(event(booking), signature=None).status_code == 401
    assert post_webhook(event(booking), signature="deadbeef").status_code == 401
    assert count(Payment) == 0
    assert get_booking(booking["id"], user_headers)["status"] == "PENDING"


def test_invalid_payloads(post_webhook):
    bad = [
        {},
        {"event_id": "", "booking_id": 1, "amount": 500, "status": "SUCCESS"},
        {"event_id": "e", "booking_id": 1, "amount": -1, "status": "SUCCESS"},
        {"event_id": "e", "booking_id": 1, "amount": 500, "status": "PAID"},
    ]

    for payload in bad:
        assert post_webhook(payload).status_code == 422, payload


def test_malformed_json_with_valid_signature(client):
    from app.services.payments import sign_payload

    body = b"{not json"
    response = client.post(
        "/payments/webhook/",
        content=body,
        headers={"X-Signature": sign_payload(body)},
    )

    assert response.status_code == 422
