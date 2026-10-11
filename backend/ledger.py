"""
Ledger projection: turns payment lifecycle transitions into ledger events.

Pure function. No database access, no side effects.

Design principle (ADR 0002):
    `events`          -> status history
    `ledger_events`   -> financial fact history
    The API writes both. The ledger reads only `ledger_events`.
"""
from datetime import datetime
from models import LedgerEvent


def ledger_events_for_transition(
    payment,
    from_status: str,
    to_status: str,
    correlation_id: str,
    status_event_id: str,
) -> list:
    """
    Return the ledger events to emit for a given transition.

    Empty list = status-only change, no money moved.
    Caller is responsible for adding returned events to the session
    atomically with the status event.
    """
    events = []
    now = datetime.utcnow()

    if to_status == "COMPLETED":
        events.append(LedgerEvent(
            payment_id=payment.id,
            event_type="PAYMENT_COMPLETED",
            amount_kobo=payment.amount_kobo,
            currency=payment.currency,
            event_time=now,
            correlation_id=correlation_id,
            status_event_id=status_event_id,
        ))

    elif to_status == "REFUNDED":
        events.append(LedgerEvent(
            payment_id=payment.id,
            event_type="PAYMENT_REFUNDED",
            amount_kobo=payment.amount_kobo,
            currency=payment.currency,
            event_time=now,
            correlation_id=correlation_id,
            status_event_id=status_event_id,
        ))

    return events
