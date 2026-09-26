def test_non_admin_cannot_write_catalog(client, user_headers):
    for path, body in [
        ("/catalog/centres", {"name": "Centre", "location": "Delhi"}),
        ("/catalog/tests", {"name": "Test"}),
        ("/catalog/centre-tests", {"centre_id": 1, "test_id": 1, "price": 10}),
    ]:
        response = client.post(path, headers=user_headers, json=body)
        assert response.status_code == 403, path


def test_anonymous_cannot_write_catalog(client):
    response = client.post("/catalog/centres", json={"name": "Centre", "location": "X1"})

    assert response.status_code in (401, 403)


def test_centre_lists_tests_with_price(client, catalog):
    response = client.get(f"/catalog/centres/{catalog['centre_id']}")

    assert response.status_code == 200
    (item,) = response.json()["tests"]
    assert item["test"]["name"] == "CBC Test"
    assert float(item["price"]) == 500


def test_filter_centres_by_location_and_test(client, catalog, admin_headers):
    client.post(
        "/catalog/centres",
        headers=admin_headers,
        json={"name": "Other Lab", "location": "Mumbai"},
    )

    by_location = client.get("/catalog/centres", params={"location": "dehra"}).json()
    by_test = client.get("/catalog/centres", params={"test_id": catalog["test_id"]}).json()
    everything = client.get("/catalog/centres").json()

    assert [c["name"] for c in by_location] == ["City Diagnostics"]
    assert [c["name"] for c in by_test] == ["City Diagnostics"]
    assert len(everything) == 2


def test_pagination(client, admin_headers):
    for i in range(3):
        client.post("/catalog/tests", headers=admin_headers, json={"name": f"Test {i}"})

    page = client.get("/catalog/tests", params={"limit": 2, "offset": 2}).json()

    assert [t["name"] for t in page] == ["Test 2"]
    assert client.get("/catalog/tests", params={"limit": 0}).status_code == 422


def test_duplicate_centre_test_conflicts(client, catalog, admin_headers):
    response = client.post(
        "/catalog/centre-tests",
        headers=admin_headers,
        json={
            "centre_id": catalog["centre_id"],
            "test_id": catalog["test_id"],
            "price": 1,
        },
    )

    assert response.status_code == 409


def test_centre_test_validation(client, catalog, admin_headers):
    bad_price = client.post(
        "/catalog/centre-tests",
        headers=admin_headers,
        json={
            "centre_id": catalog["centre_id"],
            "test_id": catalog["test_id"],
            "price": -5,
        },
    )
    missing = client.post(
        "/catalog/centre-tests",
        headers=admin_headers,
        json={"centre_id": 9999, "test_id": catalog["test_id"], "price": 5},
    )

    assert bad_price.status_code == 422
    assert missing.status_code == 404


def test_unknown_ids_return_404(client):
    assert client.get("/catalog/centres/999").status_code == 404
    assert client.get("/catalog/tests/999").status_code == 404


def test_price_change_does_not_affect_existing_booking(
    client, catalog, admin_headers, booking
):
    response = client.patch(
        f"/catalog/centre-tests/{catalog['centre_test_id']}",
        headers=admin_headers,
        json={"price": 900},
    )

    assert response.status_code == 200
    assert float(booking["amount"]) == 500


def test_remove_test_from_centre(client, catalog, admin_headers):
    response = client.delete(
        f"/catalog/centre-tests/{catalog['centre_test_id']}", headers=admin_headers
    )

    assert response.status_code == 204
    assert client.get(f"/catalog/centres/{catalog['centre_id']}").json()["tests"] == []
