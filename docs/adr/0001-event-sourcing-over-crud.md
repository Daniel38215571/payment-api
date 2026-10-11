# ADR 0001: Event Sourcing Over CRUD

**Status:** Accepted  
**Date:** 2026-10-11

## Context

The payment API needs to record payment state changes in a way that is
auditable, replayable, and defensible under external review. A traditional
CRUD design would store only the current state of each payment, losing the
history of how it reached that state.

## Decision

Use event sourcing for payment state. Every status transition is recorded
as an immutable `Event` row. The current state of a payment is derivable
from its event history.

Events are appended, never modified or deleted. The `payments` table is
maintained as a materialized current state for read performance, but the
`events` table is the source of truth.

## Consequences

**Positive:**
- Full audit trail by construction
- State can be rebuilt from events
- Historical queries ("what was the state at time T?") become possible
- Debugging is easier — the sequence of events tells the story

**Negative:**
- More storage than pure CRUD
- Every state change requires a new row, not an UPDATE
- Application code must be careful never to mutate events

## Alternatives Considered

- **Pure CRUD with an audit log table**: Rejected. Audit logs are usually
  bolted on and incomplete. Event sourcing makes audit the primary model.
- **Snapshot-only storage**: Rejected. Loses history, breaks replay.
- **Change Data Capture (CDC)**: Deferred. Adds infrastructure complexity
  without changing the domain model.
