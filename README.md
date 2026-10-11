# Payment Ledger and Reconciliation Service

> **Thesis**: I build financial systems where every number can be traced to an event, every event can be replayed, and every balance can be reconciled against an external source of truth. My work is defensible under audit because correctness is architectural, not documented after the fact.

An event-sourced payment API that emits financial facts (ledger events) as a first-class domain concept, separate from status history.

## Status

**Week 1 — Foundation.** Ledger event emission is implemented and tested. Postings, journal entries, temporal balance queries, and reconciliation integration are in progress.

## What works today

- `POST /payments` — create a payment (idempotent)
- `GET /payments/{id}` — fetch a payment
- `GET /payments/{id}/events` — full status history
- `POST /webhooks/gateway` — HMAC-verified webhook handler that transitions payment state and emits ledger events on terminal money states
- `GET /health` — liveness check

## Architecture

Payment API emits two kinds of records:

- `events` — status history (what states did this payment pass through?)
- `ledger_events` — financial fact history (what money moved, when, and why?)

The two tables are separate on purpose. The API writes both atomically. See ADR 0002 for the reasoning.

## What this demonstrates

- **Event sourcing** — every state change derives from an immutable event log
- **Double-entry accounting** — postings and journal entries (in progress)
- **Atomic multi-table writes** — a status event and its ledger event commit together
- **Idempotency** — every write path is safely retryable
- **HMAC verification** — webhooks are cryptographically authenticated
- **Test-driven** — behavior is verified by executable tests, not documentation

## What this is not

- Not a payment processor. It consumes events; it does not move money.
- Not multi-currency (yet). Scope is single-currency.
- Not fraud detection. That comes later as an application of this platform.

## Stack

- Python 3.10+
- FastAPI
- SQLAlchemy
- Pydantic
- SQLite (production would use PostgreSQL)
- Pytest
- Render

## Getting started

Install dependencies:

pip install -r backend/requirements.txt

Run the API locally:

cd backend
uvicorn api.main:app --reload

Interactive API docs: http://localhost:8000/docs

## Testing

Run the full test suite:

cd backend
pytest -v

The ledger test (test_ledger_emission.py) verifies:

- No ledger event is emitted for non-terminal transitions
- Exactly one ledger event is emitted when a payment completes
- The ledger event carries the correct amount, currency, and correlation ID
- The ledger event links back to its source status event

## Documentation

- Architecture Decision Records (docs/adr/)
  - 0000: Project Thesis
  - 0001: Event Sourcing Over CRUD
  - 0002: Ledger Events Separate From Status Events
- Glossary (docs/glossary.md)

## Roadmap

- [x] Payment API with state machine, idempotency, audit trail
- [x] Ledger event emission on terminal money states
- [ ] Postings and journal entries (double-entry translation)
- [ ] Balance queries ("what was the balance at time T?")
- [ ] Replay verification (rebuild ledger from events, compare to live)
- [ ] Reconciliation engine wired to the ledger
- [ ] Exception queue for reconciliation mismatches

## Author

Anuoluwapo Daniel Ojo

- GitHub: https://github.com/Daniel38215571
- LinkedIn: https://linkedin.com/in/daniel-ojo-879273197
- Email: ojodaniel38@gmail.com
- Location: Lagos, Nigeria

Data x AI x Software. Building systems that prove themselves.
