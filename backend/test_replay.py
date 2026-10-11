"""
Test replay determinism.

Scenario:
1. Complete two payments (creating postings).
2. Call verify_replay() — should report deterministic=True.
3. Delete all live postings.
4. Call verify_replay() again — should report non-deterministic (missing_in_live).
5. This proves the replay function is independent of live state and
   that it detects divergence.
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
from models import Posting
from replay import verify_replay


client = TestClient(app)
HMAC_SECRET = b"test-secret"


def _sign(body: bytes) -> str:
    return hmac.new(HMAC_SECRET, body, hashlib.sha256).hexdigest()


def setup_module(module):
    init_db()


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


def test_replay_is_deterministic():
    _complete_payment("REPLAY-001", 10000)
    _complete_payment("REPLAY-002", 25000)

    db = SessionLocal()

    # Endpoint returns deterministic=True
    r = client.get("/replay/verify")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["deterministic"] is True, f"Expected deterministic, got {data}"
    assert data["live_count"] == data["rebuilt_count"], data
    assert data["live_count"] >= 4, f"Should have at least 4 postings, got {data}"
    assert data["differences"] == []

    db.close()


def test_replay_detects_missing_postings():
    """Delete live postings and verify the endpoint detects the divergence."""
    db = SessionLocal()

    # Wipe live postings (but keep ledger events + journal entries)
    deleted = db.query(Posting).delete()
    db.commit()

    # Now replay should find postings that aren't in live
    r = client.get("/replay/verify")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["deterministic"] is False, f"Expected non-deterministic, got {data}"
    assert data["live_count"] == 0
    assert data["rebuilt_count"] >= 4
    # All differences should be "missing_in_live"
    reasons = {d["reason"] for d in data["differences"]}
    assert reasons == {"missing_in_live"}, reasons

    db.close()
