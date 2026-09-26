import pytest


def pay(client, headers, booking_id, simulate=None):
    body = {"booking_id": booking_id}
    if simulate:
        body["simulate"] = simulate
    return client.post("/payments/", headers=headers, json=body)


def test_successful_payment_confirms_booking(client, booking, user_headers, get_booking):
    response = pay(client, user_headers, booking["id"], "SUCCESS")

    assert response.status_code == 201
    assert response.json()["status"] == "SUCCESS"
    assert response.json()["source"] == "MOCK"
    assert get_booking(booking["id"], user_headers)["status"] == "CONFIRMED"


def test_failed_payment_marks_booking_failed(client, booking, user_headers, get_booking):
    response = pay(client, user_headers, booking["id"], "FAILED")

    assert response.status_code == 201
    assert response.json()["status"] == "FAILED"
    assert get_booking(booking["id"], user_headers)["status"] == "FAILED"


def test_unspecified_outcome_is_success_or_failed(client, booking, user_headers):
    response = pay(client, user_headers, booking["id"])

    assert response.json()["status"] in ("SUCCESS", "FAILED")


def test_failed_booking_can_be_retried(client, booking, user_headers, get_booking):
    pay(client, user_headers, booking["id"], "FAILED")

    retry = pay(client, user_headers, booking["id"], "SUCCESS")

    assert retry.status_code == 201
    assert get_booking(booking["id"], user_headers)["status"] == "CONFIRMED"


def test_cannot_pay_twice(client, booking, user_headers):
    first = pay(client, user_headers, booking["id"], "SUCCESS")
    second = pay(client, user_headers, booking["id"], "SUCCESS")

    assert first.status_code == 201
    assert second.status_code == 409


def test_cannot_pay_cancelled_booking(client, booking, user_headers):
    client.post(f"/bookings/{booking['id']}/cancel", headers=user_headers)

    assert pay(client, user_headers, booking["id"]).status_code == 409


def test_cannot_pay_someone_elses_booking(client, booking, other_headers, user_headers, get_booking):
    response = pay(client, other_headers, booking["id"], "SUCCESS")

    assert response.status_code == 403
    assert get_booking(booking["id"], user_headers)["status"] == "PENDING"


def test_payment_requires_auth(client, booking):
    response = client.post("/payments/", json={"booking_id": booking["id"]})

    assert response.status_code in (401, 403)


def test_invalid_booking_id(client, user_headers):
    assert pay(client, user_headers, 999999).status_code == 404


@pytest.mark.parametrize("body", [{}, {"booking_id": "abc"}, {"booking_id": 1, "simulate": "MAYBE"}])
def test_invalid_payment_payload(client, user_headers, body):
    assert client.post("/payments/", headers=user_headers, json=body).status_code == 422
