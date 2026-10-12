"""
Test that a completed payment emits exactly one ledger event
with the correct amount, currency, and correlation.
"""
import json
import hmac
import hashlib
import os
import sys

# Set the env var BEFORE importing the app, so main.py picks it up.
os.environ["WEBHOOK_SECRET"] = "test-secret"

# Make backend/ importable so `from api.main import app` works.
BACKEND = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND)

from fastapi.testclient import TestClient
from api.main import app
from database import SessionLocal, init_db
from models import Event, LedgerEvent


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


def test_completion_emits_one_ledger_event():
    # 1) Create a payment.
    create_resp = client.post("/payments", json={
        "reference": "TEST-LEDGER-001",
        "amount_kobo": 50000,
        "currency": "NGN",
        "customer_id": "CUST-001",
    })
    assert create_resp.status_code in (200, 201), create_resp.text
    payment_id = create_resp.json()["id"]

    db = SessionLocal()

    # 2) PENDING -> PROCESSING : no ledger event expected.
    body1 = json.dumps({"payment_id": payment_id, "status": "PROCESSING"}).encode()
    r1 = client.post(
        "/webhooks/gateway",
        content=body1,
        headers={
            "X-Gateway-Signature": _sign(body1),
            "Content-Type": "application/json",
        },
    )
    assert r1.status_code == 200, r1.text

    count_processing = db.query(LedgerEvent).filter(
        LedgerEvent.payment_id == payment_id
    ).count()
    assert count_processing == 0, "No ledger event for PROCESSING"

    # 3) PROCESSING -> COMPLETED : one ledger event expected.
    body2 = json.dumps({"payment_id": payment_id, "status": "COMPLETED"}).encode()
    r2 = client.post(
        "/webhooks/gateway",
        content=body2,
        headers={
            "X-Gateway-Signature": _sign(body2),
            "Content-Type": "application/json",
        },
    )
    assert r2.status_code == 200, r2.text

    ledger_events = db.query(LedgerEvent).filter(
        LedgerEvent.payment_id == payment_id
    ).all()

    assert len(ledger_events) == 1, f"Expected 1, got {len(ledger_events)}"
    le = ledger_events[0]
    assert le.event_type == "PAYMENT_COMPLETED"
    assert le.amount_kobo == 50000
    assert le.currency == "NGN"
    assert le.correlation_id is not None

    status_event = db.query(Event).filter(Event.id == le.status_event_id).first()
    assert status_event is not None
    assert status_event.to_status == "COMPLETED"

    db.close()
