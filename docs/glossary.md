# Glossary

Definitions are operational, not dictionary. Each term is defined in
service of the project thesis.

## Aggregate

A consistency boundary. Events are ordered within an aggregate, not
globally. In this system, a *payment* is an aggregate.

## Event

A fact about something that happened to a payment. Events are immutable
and timestamped. Stored in the `events` table.

## Ledger Event

A financial fact: a specific money movement tied to a payment. Stored in
the `ledger_events` table, separate from status events (see ADR 0002).

## Status Event

An event recording a payment's transition from one state to another
(e.g., `PROCESSING` → `COMPLETED`). Status events that produce financial
consequences emit a corresponding ledger event.

## Posting

A single debit or credit to a single account, derived from a ledger event.

*Not yet implemented. Next milestone.*

## Journal Entry

A balanced set of postings. Every journal entry has equal total debits
and total credits.

*Not yet implemented. Next milestone.*

## Ledger

The append-only collection of journal entries and postings.

## Balance

The sum of postings to an account, up to a given point in time. Derived,
never stored as a mutable field.

## Reconciliation

The process of matching internal ledger state against an external source
of truth (settlement file, bank statement, gateway report).

## Match

A confirmed correspondence between an internal ledger item and an
external record.

## Exception

A reconciliation outcome where internal and external records do not
agree, or cannot be matched within tolerance. Exceptions are first-class,
not errors to be suppressed.

## Replay

Deterministic reconstruction of state from the event log.

## Idempotency Key

A unique identifier that allows an operation to be safely retried
without duplicating its effect.

## Invariant

A condition that must always hold. If violated, the system is in an
invalid state. Enforced in code and tested, not merely documented.

## Correlation ID

A UUID shared between a status event and the ledger event it produced.
Enables tracing related facts across tables without a foreign key.
