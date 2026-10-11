"""
Test temporal balance queries.

Scenario:
- Complete payment A at time T_A
- Complete payment B at time T_B
- Query balance as of between T_A and T_B -> only A counted
- Query balance as of after T_B -> both counted
"""
import json
import hmac
import hashlib
import os
import sys
import time

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
    init_db()


def _complete_payment(reference: str, amount_kobo: int) -> str:
    """Create a payment, transition to PROCESSING then COMPLETED. Returns payment id."""
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


def test_balance_is_temporal():
    # --- First payment: complete it now.
    _complete_payment("BAL-TEST-001", 10000)

    # --- Wait, THEN record T1. This ensures T1 is strictly after
    #     the first payment's posting and comfortably before the second.
    time.sleep(0.5)
    from datetime import datetime
    t1 = datetime.utcnow()
    time.sleep(0.5)

    # --- Second payment: complete it after T1.
    _complete_payment("BAL-TEST-002", 25000)

    # --- Query Cash balance as of T1 (should be 10000 only).
    t1_iso = t1.isoformat()
    r1 = client.get(f"/accounts/1000/balance?as_of={t1_iso}")
    assert r1.status_code == 200, r1.text
    data1 = r1.json()
    assert data1["total_debit"] == 10000, (
        f"At T1, Cash should be 10000, got {data1}"
    )
    assert data1["total_credit"] == 0

    # --- Query Cash balance as of now (should be 35000).
    r2 = client.get("/accounts/1000/balance")
    assert r2.status_code == 200, r2.text
    data2 = r2.json()
    assert data2["total_debit"] == 35000, (
        f"Now, Cash should be 35000, got {data2}"
    )

    # --- Query Revenue balance as of now (should be 35000 credited).
    r3 = client.get("/accounts/4000/balance")
    assert r3.status_code == 200, r3.text
    data3 = r3.json()
    assert data3["total_credit"] == 35000, (
        f"Revenue should have 35000 credited, got {data3}"
    )
    assert data3["total_debit"] == 0


def test_balance_returns_zero_for_unknown_account():
    r = client.get("/accounts/9999/balance")
    assert r.status_code == 200
    data = r.json()
    assert data["total_debit"] == 0
    assert data["total_credit"] == 0
    assert data["net"] == 0


def test_balance_rejects_bad_as_of():
    r = client.get("/accounts/1000/balance?as_of=not-a-date")
    assert r.status_code == 400
