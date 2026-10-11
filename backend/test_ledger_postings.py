"""
Test that a completed payment produces:
- 1 status event
- 1 ledger event
- 1 journal entry
- 2 postings (1 debit, 1 credit)
- Balanced: sum(debits) == sum(credits)
"""
import json
import hmac
import hashlib
import os
import sys

os.environ["WEBHOOK_SECRET"] = "test-secret"

BACKEND = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND)

from fastapi.testclient import TestClient
from api.main import app
from database import SessionLocal, init_db
from models import Event, LedgerEvent, JournalEntry, Posting


client = TestClient(app)
HMAC_SECRET = b"test-secret"


def _sign(body: bytes) -> str:
    return hmac.new(HMAC_SECRET, body, hashlib.sha256).hexdigest()


def setup_module(module):
    init_db()


def test_completed_payment_creates_balanced_journal_entry():
    # 1) Create and complete a payment
    r = client.post("/payments", json={
        "reference": "TEST-POSTING-001",
        "amount_kobo": 50000,
        "currency": "NGN",
        "customer_id": "CUST-001",
    })
    assert r.status_code in (200, 201), r.text
    pid = r.json()["id"]

    db = SessionLocal()

    b1 = json.dumps({"payment_id": pid, "status": "PROCESSING"}).encode()
    r1 = client.post("/webhooks/gateway", content=b1,
                     headers={"X-Gateway-Signature": _sign(b1),
                              "Content-Type": "application/json"})
    assert r1.status_code == 200, r1.text

    b2 = json.dumps({"payment_id": pid, "status": "COMPLETED"}).encode()
    r2 = client.post("/webhooks/gateway", content=b2,
                     headers={"X-Gateway-Signature": _sign(b2),
                              "Content-Type": "application/json"})
    assert r2.status_code == 200, r2.text

    # 2) Exactly one ledger event
    ledger_events = db.query(LedgerEvent).filter(
        LedgerEvent.payment_id == pid
    ).all()
    assert len(ledger_events) == 1, f"Expected 1 ledger event, got {len(ledger_events)}"
    le = ledger_events[0]

    # 3) Exactly one journal entry, linked to the ledger event
    entries = db.query(JournalEntry).filter(
        JournalEntry.ledger_event_id == le.id
    ).all()
    assert len(entries) == 1, f"Expected 1 journal entry, got {len(entries)}"
    entry = entries[0]

    # 4) Exactly two postings
    postings = db.query(Posting).filter(
        Posting.journal_entry_id == entry.id
    ).all()
    assert len(postings) == 2, f"Expected 2 postings, got {len(postings)}"

    # 5) Invariant: sum(debits) == sum(credits)
    total_debit = sum(p.debit_kobo for p in postings)
    total_credit = sum(p.credit_kobo for p in postings)
    assert total_debit == total_credit, \
        f"Unbalanced: debits={total_debit}, credits={total_credit}"
    assert total_debit == 50000

    # 6) Correct accounts: Dr Cash, Cr Revenue
    by_code = {p.account_code: p for p in postings}
    assert "1000" in by_code, "Missing Cash posting"
    assert "4000" in by_code, "Missing Revenue posting"
    assert by_code["1000"].debit_kobo == 50000, "Cash should be debited"
    assert by_code["1000"].credit_kobo == 0
    assert by_code["4000"].credit_kobo == 50000, "Revenue should be credited"
    assert by_code["4000"].debit_kobo == 0

    db.close()


def test_non_terminal_transition_creates_no_postings():
    """PROCESSING transition should not create any journal entries."""
    r = client.post("/payments", json={
        "reference": "TEST-POSTING-002",
        "amount_kobo": 10000,
        "currency": "NGN",
        "customer_id": "CUST-002",
    })
    assert r.status_code in (200, 201), r.text
    pid = r.json()["id"]

    db = SessionLocal()

    b = json.dumps({"payment_id": pid, "status": "PROCESSING"}).encode()
    r1 = client.post("/webhooks/gateway", content=b,
                     headers={"X-Gateway-Signature": _sign(b),
                              "Content-Type": "application/json"})
    assert r1.status_code == 200, r1.text

    # No ledger event, no journal entry, no postings
    assert db.query(LedgerEvent).filter(LedgerEvent.payment_id == pid).count() == 0
    # (No journal entries should reference this payment at all,
    #  which we verify indirectly: no ledger event means no entry.)

    db.close()
