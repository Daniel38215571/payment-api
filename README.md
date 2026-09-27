# Payments API

Production-grade payments service with idempotency, state machine, and audit trail.

**Live:** https://payment-api-kwe9.onrender.com

## Endpoints

- GET /health
- POST /payments — create a payment (idempotent)
- GET /payments/{id} — fetch a payment
- GET /payments/{id}/events — full audit trail
- POST /webhooks/gateway — HMAC-verified webhook handler

## Stack

Python · FastAPI · SQLAlchemy · Pydantic · SQLite · Pytest · Render

## Local Run

pip install -r backend/requirements.txt
uvicorn backend.api.main:app --reload

## Tests

pytest -v

## Author

Anuoluwapo Daniel Ojo
GitHub: https://github.com/Daniel38215571
LinkedIn: https://linkedin.com/in/daniel-ojo-879273197
