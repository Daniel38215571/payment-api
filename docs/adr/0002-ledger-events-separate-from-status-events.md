# ADR 0002: Ledger Events Separate From Status Events

**Status:** Accepted  
**Date:** 2026-10-11

## Context

Payment state transitions and financial facts are related but distinct.
A payment moving from `PROCESSING` to `COMPLETED` is one thing; the
resulting debit to Cash and credit to Revenue is another.

We could have stored both in one table with a `type` column. We chose not to.

## Decision

Maintain two separate tables:

- **`events`** — status history. Records transitions of payment state.
  Answers: "what states did this payment pass through?"
- **`ledger_events`** — financial fact history. Records money movement.
  Answers: "what money moved, when, and why?"

The API writes both tables when a transition produces a financial fact.
The ledger reads only `ledger_events`.

Both rows are written in a single atomic transaction, sharing a
`correlation_id` so they can be traced together.

## Consequences

**Positive:**
- Clean separation: status history stays in `events`, financial history
  in `ledger_events`
- Replay of the ledger depends only on `ledger_events` — no filtering by
  event type, no coupling to status transitions
- Reconciliation anchors on `ledger_events` alone
- New financial event types (refunds, chargebacks, reversals) can be
  added without touching the status `events` table

**Negative:**
- Two tables to maintain instead of one
- Callers must remember to write both rows atomically
- The relationship between the two is a soft link (correlation_id),
  not a foreign key

## Alternatives Considered

- **Single `events` table with a `has_financial_impact` flag**: Rejected.
  Forces every status event to carry financial columns it does not need,
  and every financial fact to pretend it is a status transition.
- **Ledger reads from `events` and filters by type**: Rejected. Couples
  ledger correctness to the vocabulary of status events. Adds hidden
  coupling.
- **Emit ledger events asynchronously (Kafka, queue)**: Rejected for v1.
  Adds infrastructure complexity before it is needed. Can be introduced
  later without changing the design, because the event is already a
  first-class domain concept.
