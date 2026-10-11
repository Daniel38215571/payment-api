"""
Double-entry projection: turns a LedgerEvent into a balanced JournalEntry
with two Postings (one debit, one credit).

Pure function. No database access, no side effects.

Design principle (ADR 0002):
    Ledger events record what happened financially.
    Postings record which accounts moved and in which direction.
    This module is the translation layer between the two.

Accounting rules for v1 (single currency, two event types):

    PAYMENT_COMPLETED:
        Debit  Cash (1000)     amount_kobo
        Credit Revenue (4000)  amount_kobo

    PAYMENT_REFUNDED:
        Debit  Revenue (4000)  amount_kobo
        Credit Cash (1000)     amount_kobo

Every journal entry satisfies: sum(debits) == sum(credits).
This invariant is enforced by assert_balanced() and tested.
"""
from datetime import datetime
from models import JournalEntry, Posting


# Chart of accounts (minimal)
CASH = ("1000", "Cash")
REVENUE = ("4000", "Revenue")
RECEIVABLES = ("1100", "Receivables")
FEES = ("5000", "Fees Expense")


# Rules: ledger_event_type -> (debit_account, credit_account)
RULES = {
    "PAYMENT_COMPLETED": (CASH, REVENUE),
    "PAYMENT_REFUNDED": (REVENUE, CASH),
}


class UnbalancedJournalEntryError(Exception):
    """Raised when a journal entry's debits and credits do not balance."""


def assert_balanced(postings: list) -> None:
    """Enforce that sum(debits) == sum(credits). Raise if not."""
    total_debit = sum(p.debit_kobo for p in postings)
    total_credit = sum(p.credit_kobo for p in postings)
    if total_debit != total_credit:
        raise UnbalancedJournalEntryError(
            f"Debits ({total_debit}) != Credits ({total_credit})"
        )


def project_to_postings(ledger_event) -> tuple:
    """
    Given a LedgerEvent, return (JournalEntry, [Posting, Posting]).

    The returned objects are NOT added to a session. The caller is
    responsible for adding them atomically.

    Raises ValueError if the ledger event type is not recognized.
    """
    rule = RULES.get(ledger_event.event_type)
    if rule is None:
        raise ValueError(
            f"No double-entry rule for ledger event type: {ledger_event.event_type}"
        )

    debit_account, credit_account = rule
    amount = ledger_event.amount_kobo
    now = datetime.utcnow()

    entry = JournalEntry(
        ledger_event_id=ledger_event.id,
        memo=f"{ledger_event.event_type} for payment {ledger_event.payment_id}",
        created_at=now,
    )

    debit_posting = Posting(
        account_code=debit_account[0],
        account_name=debit_account[1],
        debit_kobo=amount,
        credit_kobo=0,
        created_at=now,
    )

    credit_posting = Posting(
        account_code=credit_account[0],
        account_name=credit_account[1],
        debit_kobo=0,
        credit_kobo=amount,
        created_at=now,
    )

    postings = [debit_posting, credit_posting]
    assert_balanced(postings)
    return entry, postings
