"""
Replay verification: rebuild postings from ledger events and compare
to the live postings.

Why this matters:
    If the projection function project_to_postings() is pure, then
    applying it to the same ledger events always produces the same
    postings. That means we can rebuild the ledger from scratch at
    any time and get identical results.

    Replay is the proof that:
    - ledger_events are the source of truth
    - postings are a deterministic projection
    - nothing in the live postings is "extra" or "missing"

Comparison rules:
    - Postings are matched by ledger_event_id + account_code.
    - We compare debit_kobo and credit_kobo.
    - We do NOT compare created_at, because replay runs at a
      different wall-clock time than the original.
"""
from collections import defaultdict


def _live_postings_by_key(db):
    """Map (ledger_event_id, account_code) -> (debit, credit) for live postings."""
    from models import Posting, JournalEntry

    rows = (
        db.query(
            JournalEntry.ledger_event_id,
            Posting.account_code,
            Posting.debit_kobo,
            Posting.credit_kobo,
        )
        .join(Posting, Posting.journal_entry_id == JournalEntry.id)
        .all()
    )

    out = {}
    for ledger_event_id, account_code, debit, credit in rows:
        out[(ledger_event_id, account_code)] = (int(debit), int(credit))
    return out


def _rebuild_postings_by_key(db):
    """Replay the ledger by applying project_to_postings to every ledger event."""
    from models import LedgerEvent
    from ledger_postings import project_to_postings

    events = db.query(LedgerEvent).order_by(LedgerEvent.event_time).all()

    out = {}
    for le in events:
        entry, postings = project_to_postings(le)
        for p in postings:
            out[(le.id, p.account_code)] = (int(p.debit_kobo), int(p.credit_kobo))
    return out


def verify_replay(db) -> dict:
    """
    Return a dict describing whether live postings match replayed postings.

    {
      "live_count": int,
      "rebuilt_count": int,
      "deterministic": bool,
      "differences": [
        {"reason": "missing_in_live" | "missing_in_rebuild" | "amount_mismatch",
         "ledger_event_id": str,
         "account_code": str,
         "live": [debit, credit] | None,
         "rebuilt": [debit, credit] | None}
      ]
    }
    """
    live = _live_postings_by_key(db)
    rebuilt = _rebuild_postings_by_key(db)

    diffs = []

    for key in rebuilt:
        if key not in live:
            le_id, acct = key
            diffs.append({
                "reason": "missing_in_live",
                "ledger_event_id": le_id,
                "account_code": acct,
                "live": None,
                "rebuilt": list(rebuilt[key]),
            })
        elif live[key] != rebuilt[key]:
            le_id, acct = key
            diffs.append({
                "reason": "amount_mismatch",
                "ledger_event_id": le_id,
                "account_code": acct,
                "live": list(live[key]),
                "rebuilt": list(rebuilt[key]),
            })

    for key in live:
        if key not in rebuilt:
            le_id, acct = key
            diffs.append({
                "reason": "missing_in_rebuild",
                "ledger_event_id": le_id,
                "account_code": acct,
                "live": list(live[key]),
                "rebuilt": None,
            })

    return {
        "live_count": len(live),
        "rebuilt_count": len(rebuilt),
        "deterministic": len(diffs) == 0,
        "differences": diffs,
    }
