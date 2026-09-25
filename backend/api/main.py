import sys
sys.path.insert(0, "/content/payments-api/backend")

import uuid
import json
import hmac
import hashlib
import os
from datetime import datetime

from fastapi import FastAPI, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from database import get_db, init_db
from models import Payment, Event
from schemas import PaymentCreate, PaymentResponse, EventResponse
from idempotency import check_key, store_response
from state_machine import assert_transition, InvalidTransitionError


WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "test-secret-change-in-production")


app = FastAPI(
    title="Payments API",
    description="Production-grade payments service with idempotency.",
    version="0.1.0",
)


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/health")
def health_check():
    return {"status": "ok"}


def _generate_reference():
    return "PAY-" + uuid.uuid4().hex[:12]


def _verify_signature(raw_body: bytes, signature: str) -> bool:
    if not signature:
        return False
    expected = hmac.new(
        WEBHOOK_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.post("/payments", response_model=PaymentResponse, status_code=201)
async def create_payment(
    request: Request,
    idempotency_key: str = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    raw_body = await request.body()
    try:
        body_dict = json.loads(raw_body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    payment_data = PaymentCreate(**body_dict)

    if idempotency_key:
        outcome, cached_body, cached_status = check_key(db, idempotency_key, body_dict)
        if outcome == "replay":
            return json.loads(cached_body)
        if outcome == "conflict":
            raise HTTPException(
                status_code=422,
                detail="Idempotency-Key already used with a different request body",
            )

    payment = Payment(
        reference=_generate_reference(),
        amount_kobo=payment_data.amount_kobo,
        currency=payment_data.currency,
        customer_id=payment_data.customer_id,
        status="PENDING",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(payment)
    db.flush()

    event = Event(
        payment_id=payment.id,
        event_type="PAYMENT_CREATED",
        from_status=None,
        to_status="PENDING",
        payload={"amount_kobo": payment.amount_kobo, "currency": payment.currency},
        created_at=datetime.utcnow(),
    )
    db.add(event)
    db.commit()
    db.refresh(payment)

    response = {
        "id": payment.id,
        "reference": payment.reference,
        "amount_kobo": payment.amount_kobo,
        "currency": payment.currency,
        "customer_id": payment.customer_id,
        "status": payment.status,
        "created_at": payment.created_at.isoformat(),
        "updated_at": payment.updated_at.isoformat(),
    }

    if idempotency_key:
        store_response(db, idempotency_key, body_dict, json.dumps(response), 201)

    return response


@app.get("/payments/{payment_id}", response_model=PaymentResponse)
def get_payment(payment_id: str, db: Session = Depends(get_db)):
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment


@app.get("/payments/{payment_id}/events", response_model=list)
def get_payment_events(payment_id: str, db: Session = Depends(get_db)):
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")

    events = (
        db.query(Event)
        .filter(Event.payment_id == payment_id)
        .order_by(Event.created_at.asc())
        .all()
    )

    return [
        {
            "id": e.id,
            "event_type": e.event_type,
            "from_status": e.from_status,
            "to_status": e.to_status,
            "created_at": e.created_at.isoformat(),
        }
        for e in events
    ]


@app.post("/webhooks/gateway")
async def gateway_webhook(
    request: Request,
    x_gateway_signature: str = Header(None, alias="X-Gateway-Signature"),
    db: Session = Depends(get_db),
):
    raw_body = await request.body()

    if not _verify_signature(raw_body, x_gateway_signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = json.loads(raw_body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    payment_id = payload.get("payment_id")
    new_status = payload.get("status")

    if not payment_id or not new_status:
        raise HTTPException(status_code=400, detail="payment_id and status required")

    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")

    from_status = payment.status

    try:
        assert_transition(from_status, new_status)
    except InvalidTransitionError as e:
        raise HTTPException(status_code=400, detail=str(e))

    payment.status = new_status
    payment.updated_at = datetime.utcnow()

    event = Event(
        payment_id=payment.id,
        event_type="STATUS_CHANGED",
        from_status=from_status,
        to_status=new_status,
        payload=payload,
        created_at=datetime.utcnow(),
    )
    db.add(event)
    db.commit()
    db.refresh(payment)

    return {
        "status": "accepted",
        "payment_id": payment.id,
        "from_status": from_status,
        "to_status": new_status,
    }
