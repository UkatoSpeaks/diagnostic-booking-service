from datetime import datetime, timedelta, timezone


def _payload(catalog, when):
    return {
        "test_id": catalog["test_id"],
        "centre_id": catalog["centre_id"],
        "appointment_at": when,
    }


def _future():
    return (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()


def test_create_booking_uses_catalog_price(client, catalog, user_headers):
    response = client.post(
        "/bookings/", headers=user_headers, json=_payload(catalog, _future())
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "PENDING"
    assert float(body["amount"]) == catalog["price"]


def test_amount_from_client_is_ignored(client, catalog, user_headers):
    payload = _payload(catalog, _future()) | {"amount": 1}

    response = client.post("/bookings/", headers=user_headers, json=payload)

    assert float(response.json()["amount"]) == catalog["price"]


def test_booking_requires_auth(client, catalog):
    response = client.post("/bookings/", json=_payload(catalog, _future()))

    assert response.status_code in (401, 403)


def test_past_appointment_rejected(client, catalog, user_headers):
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

    response = client.post("/bookings/", headers=user_headers, json=_payload(catalog, past))

    assert response.status_code == 400


def test_naive_datetime_rejected(client, catalog, user_headers):
    naive = (datetime.now() + timedelta(days=2)).replace(tzinfo=None).isoformat()

    response = client.post("/bookings/", headers=user_headers, json=_payload(catalog, naive))

    assert response.status_code == 422


def test_test_not_offered_at_centre(client, catalog, user_headers, admin_headers):
    other_test = client.post(
        "/catalog/tests", headers=admin_headers, json={"name": "Lipid Profile"}
    ).json()
    payload = _payload(catalog, _future()) | {"test_id": other_test["id"]}

    response = client.post("/bookings/", headers=user_headers, json=payload)

    assert response.status_code == 404


def test_invalid_payload(client, user_headers):
    response = client.post("/bookings/", headers=user_headers, json={"test_id": "x"})

    assert response.status_code == 422


def test_get_booking_owner_only(client, booking, user_headers, other_headers):
    assert client.get(f"/bookings/{booking['id']}", headers=user_headers).status_code == 200
    assert client.get(f"/bookings/{booking['id']}", headers=other_headers).status_code == 403
    assert client.get("/bookings/99999", headers=user_headers).status_code == 404
    assert client.get(f"/bookings/{booking['id']}").status_code in (401, 403)


def test_list_only_returns_own_bookings_with_pagination(
    client, make_booking, user_headers, other_headers
):
    for _ in range(3):
        make_booking(user_headers)
    make_booking(other_headers)

    everything = client.get("/bookings/", headers=user_headers).json()
    page = client.get("/bookings/", params={"limit": 2}, headers=user_headers).json()

    assert len(everything) == 3
    assert len(page) == 2


def test_list_filters_by_status(client, make_booking, user_headers):
    first = make_booking(user_headers)
    make_booking(user_headers)
    client.post(f"/bookings/{first['id']}/cancel", headers=user_headers)

    cancelled = client.get(
        "/bookings/", params={"status": "CANCELLED"}, headers=user_headers
    ).json()

    assert [b["id"] for b in cancelled] == [first["id"]]


def test_cancel_pending_booking(client, booking, user_headers):
    response = client.post(f"/bookings/{booking['id']}/cancel", headers=user_headers)

    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"


def test_cancel_requires_ownership(client, booking, other_headers):
    response = client.post(f"/bookings/{booking['id']}/cancel", headers=other_headers)

    assert response.status_code == 403


def test_cancel_unknown_booking(client, user_headers):
    assert client.post("/bookings/999/cancel", headers=user_headers).status_code == 404


def test_cannot_cancel_confirmed_booking(client, booking, user_headers):
    client.post(
        "/payments/",
        headers=user_headers,
        json={"booking_id": booking["id"], "simulate": "SUCCESS"},
    )

    response = client.post(f"/bookings/{booking['id']}/cancel", headers=user_headers)

    assert response.status_code == 409
