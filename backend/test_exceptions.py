"""
Test that reconciliation persists exceptions and that they can be resolved.
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
from models import Exception as ExceptionModel


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
    db.query(ExceptionModel).delete()
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


def test_exceptions_persist_after_reconciliation():
    _complete_payment("EXC-001", 10000)
    _complete_payment("EXC-002", 25000)

    settlement = {
        "settlement_rows": [
            {"reference": "EXC-001", "amount_kobo": 10000},   # MATCHED
            {"reference": "EXC-002", "amount_kobo": 20000},   # AMOUNT_MISMATCH
        ]
    }

    r = client.post("/reconcile/run", json=settlement)
    assert r.status_code == 200, r.text

    # List persisted exceptions
    r2 = client.get("/exceptions")
    assert r2.status_code == 200, r2.text
    data = r2.json()

    assert data["count"] == 1, data
    ex = data["items"][0]
    assert ex["classification"] == "AMOUNT_MISMATCH"
    assert ex["reference"] == "EXC-002"
    assert ex["amount_kobo"] == 5000  # |25000 - 20000|
    assert ex["status"] == "OPEN"


def test_exception_can_be_resolved():
    r = client.get("/exceptions?status=OPEN")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] >= 1

    ex_id = data["items"][0]["id"]

    # Resolve it
    r2 = client.post(
        f"/exceptions/{ex_id}/resolve",
        json={"note": "Confirmed with provider. Rounding difference accepted."},
    )
    assert r2.status_code == 200, r2.text
    resolved = r2.json()
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution_note"].startswith("Confirmed")
    assert resolved["resolved_at"] is not None

    # Open filter should no longer include it
    r3 = client.get("/exceptions?status=OPEN")
    open_items = r3.json()["items"]
    assert all(item["id"] != ex_id for item in open_items)

    # Resolved filter should include it
    r4 = client.get("/exceptions?status=RESOLVED")
    resolved_items = r4.json()["items"]
    assert any(item["id"] == ex_id for item in resolved_items)


def test_resolve_missing_exception_returns_404():
    r = client.post("/exceptions/nonexistent-id/resolve", json={"note": "test"})
    assert r.status_code == 404
