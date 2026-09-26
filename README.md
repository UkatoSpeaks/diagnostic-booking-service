# Diagnostic Booking Service

Backend for booking diagnostic tests at diagnostic centres, with a simulated
payment service and an idempotent, signed payment webhook.

**Stack:** FastAPI · SQLAlchemy 2 · PostgreSQL · Alembic · JWT (python-jose) ·
argon2 password hashing · slowapi rate limiting · pytest.

## Running locally

### Setup

Requires Python 3.12+ and PostgreSQL.
The API is on <http://localhost:8000>; interactive docs (Swagger UI) at
<http://localhost:8000/docs>, OpenAPI JSON at `/openapi.json`.

```bash
uv sync                       # or: pip install -r requirements.txt
cp .env.example .env          # then edit DATABASE_URL and secrets
createdb diagnostic_booking
alembic upgrade head
uvicorn app.main:app --reload
```

### Configuration (`.env`)

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | SQLAlchemy URL, e.g. `postgresql://user:pass@localhost:5432/diagnostic_booking` |
| `SECRET_KEY` | JWT signing key (min 16 chars) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token lifetime, default 60 |
| `WEBHOOK_SECRET` | Shared secret for signing webhooks (min 8 chars) |
| `ADMIN_EMAILS` | Comma-separated emails that become admins **when they sign up** |
| `MOCK_PAYMENT_SUCCESS_RATE` | Chance (0–1) a mock payment succeeds when no outcome is forced, default 0.8 |

### Tests

```bash
uv sync                       # installs dev deps (pytest, httpx)
pytest
```

The suite needs a PostgreSQL database. It uses `TEST_DATABASE_URL` if set;
otherwise it takes your `DATABASE_URL` and appends `_test` to the database
name (create it first: `createdb diagnostic_booking_test`). Tables are
created and truncated by the tests, and the suite refuses to run against a
database whose name does not end in `_test`.

## API overview

All bodies are JSON. Protected endpoints need `Authorization: Bearer <token>`.

| Method & path | Auth | Description |
| --- | --- | --- |
| `POST /auth/signup` | – | Create account, returns JWT (rate limited 10/min) |
| `POST /auth/login` | – | Returns JWT (rate limited 10/min) |
| `GET /auth/me` | user | Current user |
| `GET /catalog/centres` | – | List centres with their tests and prices. Filters: `location`, `test_id`; `limit`, `offset` |
| `GET /catalog/centres/{id}` | – | One centre with tests and prices |
| `GET /catalog/tests` | – | List tests. Filters: `search`; `limit`, `offset` |
| `GET /catalog/tests/{id}` | – | One test |
| `POST /catalog/centres` | admin | Create a centre |
| `POST /catalog/tests` | admin | Create a test |
| `POST /catalog/centre-tests` | admin | Offer a test at a centre with a price |
| `PATCH /catalog/centre-tests/{id}` | admin | Change price (existing bookings keep theirs) |
| `DELETE /catalog/centre-tests/{id}` | admin | Stop offering a test at a centre |
| `POST /bookings/` | user | Book a test (status `PENDING`) |
| `GET /bookings/` | user | Own bookings. Filters: `status`; `limit`, `offset` |
| `GET /bookings/{id}` | owner | One booking |
| `POST /bookings/{id}/cancel` | owner | Cancel a `PENDING`/`FAILED` booking |
| `POST /payments/` | owner | Simulated payment → `SUCCESS` or `FAILED` |
| `POST /payments/webhook/` | HMAC signature | Provider status callback (idempotent) |
| `GET /health` | – | 200 if DB reachable, else 503 |

### Example requests

```bash
# Sign up (add the email to ADMIN_EMAILS to get catalog write access)
curl -X POST localhost:8000/auth/signup -H 'Content-Type: application/json' \
  -d '{"name":"Asha","email":"asha@example.com","password":"password123"}'
# -> {"access_token":"<jwt>","token_type":"bearer"}

TOKEN=<jwt>

# Admin: create centre, test, and price
curl -X POST localhost:8000/catalog/centres -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"name":"City Diagnostics","location":"Dehradun"}'
curl -X POST localhost:8000/catalog/tests -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"name":"CBC","description":"Complete Blood Count"}'
curl -X POST localhost:8000/catalog/centre-tests -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"centre_id":1,"test_id":1,"price":500}'

# Browse
curl 'localhost:8000/catalog/centres?location=dehradun'

# Book (appointment_at must be a future, timezone-aware timestamp)
curl -X POST localhost:8000/bookings/ -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"test_id":1,"centre_id":1,"appointment_at":"2030-01-15T09:30:00+05:30"}'

# Simulated payment. "simulate" is optional (SUCCESS | FAILED); random otherwise.
curl -X POST localhost:8000/payments/ -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"booking_id":1,"simulate":"SUCCESS"}'
```

### Webhook

`POST /payments/webhook/` body:

```json
{"event_id": "evt_123", "booking_id": 1, "amount": "500.00", "status": "SUCCESS"}
```

The provider signs the **raw request body** with HMAC-SHA256 using
`WEBHOOK_SECRET` and sends the hex digest in `X-Signature`:

```bash
BODY='{"event_id":"evt_123","booking_id":1,"amount":500,"status":"SUCCESS"}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" | awk '{print $NF}')
curl -X POST localhost:8000/payments/webhook/ \
  -H 'Content-Type: application/json' -H "X-Signature: $SIG" -d "$BODY"
```

Response:

```json
{"event_id":"evt_123","booking_id":1,"booking_status":"CONFIRMED",
 "payment_id":1,"outcome":"PROCESSED","duplicate":false}
```

| Situation | Result |
| --- | --- |
| Missing/invalid signature | 401 |
| Malformed body / bad fields | 422 |
| Unknown booking | 404 |
| Amount ≠ booking amount | 400 |
| First delivery of an event | 200, `PROCESSED`, booking updated |
| Same `event_id` again (same payload) | 200, `duplicate: true`, nothing changes |
| Same `event_id`, different payload | 409 |
| New event for a booking that is already `CONFIRMED`/`CANCELLED` | 200, `IGNORED` (recorded, booking untouched, so the provider stops retrying) |

Errors follow FastAPI's `{"detail": ...}` shape.

## Booking and payment lifecycle

```
PENDING ──payment SUCCESS──▶ CONFIRMED
   │  └───payment FAILED───▶ FAILED ──payment SUCCESS──▶ CONFIRMED
   └──cancel──▶ CANCELLED  (also from FAILED)
```

- `CONFIRMED` and `CANCELLED` are terminal; further payments get 409.
- A `FAILED` booking can be paid again. Each attempt is a separate `payments` row.

## Database design

```
users ─┐
       ├──< bookings >── diagnostic_tests ──< centre_tests >── diagnostic_centres
       │        │                                  (price per centre+test)
       │        ├──< payments        (one row per payment attempt)
       │        └──< webhook_events  (ledger; unique event_id)
```

| Table | Notes |
| --- | --- |
| `users` | unique lower-cased `email`, argon2 `password_hash`, `is_admin` |
| `diagnostic_centres` | `name`, `location` |
| `diagnostic_tests` | `name`, `description` |
| `centre_tests` | join table with `price`; **unique (centre_id, test_id)** |
| `bookings` | user, test, centre, `appointment_at` (tz-aware), `amount`, `status`; indexed on `user_id`, `status`; `created_at`/`updated_at` |
| `payments` | `booking_id` (indexed), `amount`, `status` (SUCCESS/FAILED), `source` (MOCK/WEBHOOK) |
| `webhook_events` | **unique `event_id`**, `booking_id`, `payment_id`, `amount`, `status`, `outcome` (PROCESSED/IGNORED) |

Design points:

- Money is `NUMERIC(10,2)`, never float.
- `bookings.amount` is a **snapshot** of the centre price at booking time. It
  is taken server-side, never from the client, so later price changes do not
  alter existing bookings.
- Idempotency lives in `webhook_events.event_id` (unique). Processing locks
  the booking row (`SELECT … FOR UPDATE`), so concurrent deliveries of the
  same event are serialised; the unique constraint is the backstop. The
  concurrency test fires six simultaneous identical webhooks and asserts one
  payment.
- The mock endpoint locks the booking the same way, so two simultaneous
  payments cannot both succeed.

## Assumptions

- A centre offering a test at a price is modelled by `centre_tests`; a booking
  is for one test at one centre.
- Only admins write to the catalog. Admins are designated by `ADMIN_EMAILS`
  (matched at signup); there is no admin-management endpoint.
- Payment provider is simulated; the webhook shares an HMAC secret with it.
  Amount is validated against the booking.
- Cancelling a paid (`CONFIRMED`) booking is not supported, because it would
  need a refund flow.
- The same user may create several bookings for the same slot (no capacity or
  slot model).
- Appointment times must be timezone-aware and in the future.
- `POST /payments/` accepts a `simulate` field so outcomes are deterministic
  for demos and tests; a real deployment would remove it.

## What I would improve with more time

- Slot/capacity management per centre and time (prevent double booking).
- Refunds and a `REFUNDED` state; cancelling paid bookings.
- Webhook timestamp in the signature (replay protection) and secret rotation.
- Background retry of failed/ignored webhook work via Celery + Redis, and a
  dead-letter view of `webhook_events`.
- Redis-backed rate limiting and caching of catalog reads (the in-memory
  limiter is per-process).
- Refresh tokens, email verification, password reset, an admin-management
  API, and login lockout.
- A consistent error envelope with machine-readable codes.
- Docker/docker-compose packaging, an async DB driver, and a CI pipeline.
- Catalog soft-delete and centre/test update endpoints.
