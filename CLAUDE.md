# Project rules for AI assistants

Kvitto Payments API: FastAPI + SQLAlchemy 2.0 + SQLite. Read this before changing code.

## Money
- All amounts are integers in kopecks (`int`). Never use `float` or `round()` for money.
- Use only `*`, `//`, `%` and `divmod` for money math.
- All money rules live in `app/domain.py` as pure functions with no FastAPI or DB imports.
- An installment schedule must always sum exactly to `amount`; extra kopecks go first.

## Statuses
- Allowed transitions are defined only in `ALLOWED_TRANSITIONS` in `app/domain.py`.
- Change a status only with a conditional `UPDATE ... WHERE status = <current>` and check `rowcount`.
- A forbidden transition returns 409 with exactly `{"error": "invalid_transition"}`.

## Idempotency
- `payments.idempotency_key` is UNIQUE. Keep the `except IntegrityError` branch in `create_payment`.
- A repeated request with the same key returns the existing payment with 200.

## Webhook security
- Verify `X-Signature` (HMAC-SHA256 of the raw body) with `hmac.compare_digest` on bytes.
- Never accept webhooks when `WEBHOOK_SECRET` is not set.

## Code style
- Python 3.11+, type hints on every function, Pydantic v2 (`field_validator`, `model_validator`).
- SQLAlchemy 2.0 style: `Mapped`, `mapped_column`, `select()`.
- Validation errors use the standard FastAPI 422 response.

## Before finishing any change
1. `ruff check .` and `ruff format .`
2. `python -m pytest -v` — all tests must pass.
3. Every new rule or bug fix gets a test that checks the result, not only the status code.