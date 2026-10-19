# Kvitto Payments API

A small payments service for an online school: tariffs, payments with promo codes and
installments, idempotent payment creation and a signed bank webhook.

## Task

A take-home assignment for a Junior Python (FastAPI) position at Kvitto (time budget: ~3 hours).
Build a payments API for an online school: tariffs, payment creation with a promo code and
installments, idempotent retries via `Idempotency-Key`, and a bank webhook that changes the
payment status by strict transition rules. All money is integer kopecks, at least 5 pytest tests,
plus an `AI_LOG.md` describing how AI tools were used.

Optional extras implemented here: docker compose, Alembic migrations, webhook HMAC signature check, `GET /payments` with filters,
GitHub Actions (ruff + pytest) and assistant rules in `CLAUDE.md`.

**Stack:** Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.0, SQLite, pytest + httpx, ruff.

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export WEBHOOK_SECRET=dev-secret
uvicorn app.main:app --reload
```

The API is available at http://127.0.0.1:8000, interactive docs at http://127.0.0.1:8000/docs.
The SQLite database `kvitto.db` and the three tariffs are created on startup.

`WEBHOOK_SECRET` is required only for `POST /webhooks/bank`: without it the webhook is rejected
with 500 (unsigned webhooks are never accepted). `DATABASE_URL` is optional
(default: `sqlite:///./kvitto.db`).

### Run with Docker

```bash
docker compose up --build
```

The API starts at http://127.0.0.1:8000 with `WEBHOOK_SECRET=dev-secret` by default
(override it with `WEBHOOK_SECRET=... docker compose up`). The SQLite database is stored
in the `kvitto-data` volume; `docker compose down -v` removes it.

## Tests and linting

```bash
python -m pytest -v
ruff check .
ruff format --check .
```

Tests use a separate temporary database and do not touch `kvitto.db`.
The same checks run in GitHub Actions on every push (`.github/workflows/ci.yml`).

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/tariffs` | List of tariffs |
| POST | `/payments` | Create a payment; supports the `Idempotency-Key` header |
| GET | `/payments/{id}` | Get a payment; 404 if it does not exist |
| GET | `/payments` | List payments, filters `email`, `status`, paging `limit`, `offset` |
| POST | `/webhooks/bank` | Bank status update, signed with `X-Signature` |

All amounts are integers in kopecks: 19 900 RUB is `1990000`.

## Examples

Create a payment in installments with a promo code:

```bash
curl -s -X POST localhost:8000/payments \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: order-1" \
  -d '{"tariff_id": "standard", "email": "me@example.com", "method": "installment", "installment_months": 3, "promo_code": "kvitto10"}'
```

```json
{"id": "…", "status": "pending", "tariff_id": "standard", "amount": 1791000, "discount": 199000,
 "method": "installment", "installment_months": 3, "schedule": [597000, 597000, 597000],
 "email": "me@example.com", "created_at": "…Z"}
```

Repeating the same request with the same `Idempotency-Key` returns the same payment with 200.

Get a payment:

```bash
curl -s localhost:8000/payments/<payment_id>
```

Send a signed webhook (the signature is HMAC-SHA256 of the raw body with `WEBHOOK_SECRET`):

```bash
BODY='{"payment_id": "<payment_id>", "status": "succeeded"}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "dev-secret" | sed 's/^.* //')
curl -s -X POST localhost:8000/webhooks/bank \
  -H "Content-Type: application/json" -H "X-Signature: $SIG" -d "$BODY"
```

List payments of one customer:

```bash
curl -s "localhost:8000/payments?email=me@example.com&status=succeeded"
```

## Business rules

- **Money** is stored and calculated only as integer kopecks. The discount is
  `price * percent // 100`, the amount is `price - discount`.
- **Promo code** `KVITTO10` gives −10%, case-insensitive, surrounding spaces are ignored.
  An unknown code returns 422.
- **Installments**: `installment_months` is required for `installment` and must be 3, 6 or 12;
  it is rejected for `card` and `sbp`. The schedule always sums exactly to `amount`,
  extra kopecks go to the first payments: `1990000 / 3 → [663334, 663333, 663333]`.
- **Statuses**: a new payment is `pending`. Allowed: `pending → succeeded`, `pending → failed`,
  `succeeded → refunded`. Anything else, including a repeat of the current status, returns
  409 `{"error": "invalid_transition"}` and the status does not change.

## Design decisions

- **Idempotency has two layers.** A lookup by key handles normal retries; a UNIQUE index plus
  `except IntegrityError` handles two identical requests arriving at the same time.
- **Status changes are atomic.** The webhook updates with `WHERE status = <current>` and checks
  `rowcount`, so a parallel webhook can never be overwritten.
- **Webhook signature** is checked against the raw body with `hmac.compare_digest`.
- **Unknown tariff** returns 404 (the tariff is looked up in the database);
  invalid input formats return the standard FastAPI 422.
- **Sync endpoints + SQLite** keep the code simple; FastAPI runs them in a thread pool.
  Moving to PostgreSQL only needs a different `DATABASE_URL` and driver.
 - **Schema is managed by Alembic** (`migrations/`). Migrations run automatically on startup; `alembic upgrade head` and `alembic downgrade base` also work from the command line. A test checks that the migrations match the models.

## Project structure

```
app/
  main.py       # app, startup, endpoints
  domain.py     # money and status rules, no FastAPI or DB
  models.py     # SQLAlchemy tables
  schemas.py    # Pydantic request/response schemas and validation
  database.py   # engine, sessions, get_db dependency
  security.py   # webhook signature check
tests/          # 92 tests: domain, payments, idempotency, webhooks, list
CLAUDE.md       # rules for AI assistants
AI_LOG.md       # how AI was used
```