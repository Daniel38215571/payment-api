"""
Test reconciliation: create three payments, then run reconciliation with
a synthetic settlement file that intentionally contains:
- 1 matching row
- 1 amount mismatch
- 1 missing from settlement

Expect: correct classification counts and value-at-risk.
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


client = TestClient(app)
HMAC_SECRET = b"test-secret"


def _sign(body: bytes) -> str:
    return hmac.new(HMAC_SECRET, body, hashlib.sha256).hexdigest()



def setup_module(module):
    """Wipe the database before this test file runs."""
    init_db()
    from models import Posting, JournalEntry, LedgerEvent, Event, IdempotencyKey, Payment
    db = SessionLocal()
    db.query(Posting).delete()
    db.query(JournalEntry).delete()
    db.query(LedgerEvent).delete()
    db.query(Event).delete()
    db.query(IdempotencyKey).delete()
    db.query(Payment).delete()
    db.commit()
    db.close()


def _complete_payment(reference: str, amount_kobo: int) -> str:
    r = client.post("/payments", json={
        "reference": reference,
        "amount_kobo": amount_kobo,
        "currency": "NGN",
        "customer_id": "CUST-" + reference,
    })
    assert r.status_code in (200, 201), r.text
    pid = r.json()["id"]

    for status in ("PROCESSING", "COMPLETED"):
        body = json.dumps({"payment_id": pid, "status": status}).encode()
        rr = client.post(
            "/webhooks/gateway",
            content=body,
            headers={
                "X-Gateway-Signature": _sign(body),
                "Content-Type": "application/json",
            },
        )
        assert rr.status_code == 200, rr.text

    return pid


def test_reconciliation_classifies_mismatches():
    # --- Create three payments in the ledger
    _complete_payment("REC-001", 10000)   # will match
    _complete_payment("REC-002", 25000)   # will mismatch
    _complete_payment("REC-003", 50000)   # will be missing from settlement

    # --- Synthetic settlement: 1 match, 1 mismatch, 1 extra
    settlement = {
        "settlement_rows": [
            {"reference": "REC-001", "amount_kobo": 10000},   # MATCHED
            {"reference": "REC-002", "amount_kobo": 20000},   # AMOUNT_MISMATCH (should be 25000)
            {"reference": "REC-999", "amount_kobo": 5000},    # MISSING_IN_LEDGER
        ]
    }

    r = client.post("/reconcile/run", json=settlement)
    assert r.status_code == 200, r.text
    data = r.json()

    # --- Assertions
    assert data["matched"] == 1, data
    assert data["amount_mismatch"] == 1, data
    assert data["missing_in_settlement"] == 1, data
    assert data["missing_in_ledger"] == 1, data
    assert data["duplicate_in_settlement"] == 0, data

    # --- Value at risk = sum of exception amounts
    # MISSING_IN_SETTLEMENT: 50000
    # AMOUNT_MISMATCH: |25000 - 20000| = 5000
    # MISSING_IN_LEDGER: 5000
    # Total: 60000
    assert data["value_at_risk_kobo"] == 60000, data

    # --- Verify exception classifications
    classifications = [ex["classification"] for ex in data["exceptions"]]
    assert "AMOUNT_MISMATCH" in classifications
    assert "MISSING_IN_SETTLEMENT" in classifications
    assert "MISSING_IN_LEDGER" in classifications
    assert "MATCHED" not in classifications  # matches don't become exceptions
    assert len(data["exceptions"]) == 3


def test_reconciliation_detects_duplicate_settlement_rows():
    _complete_payment("REC-DUP", 15000)

    settlement = {
        "settlement_rows": [
            {"reference": "REC-DUP", "amount_kobo": 15000},
            {"reference": "REC-DUP", "amount_kobo": 15000},
        ]
    }

    r = client.post("/reconcile/run", json=settlement)
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["duplicate_in_settlement"] == 1, data
    assert data["matched"] == 0, data
