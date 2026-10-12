


import uuid
import json
import hmac
import hashlib
import os
from datetime import datetime

from fastapi import FastAPI, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from database import get_db, init_db
from models import Exception
from models import Payment, Event
from ledger import ledger_events_for_transition
from ledger_postings import project_to_postings
from balance import get_balance
from replay import verify_replay
from reconciliation import reconcile
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
        reference=payment_data.reference,
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

    # 1) Build the status-change event
    status_event = Event(
        payment_id=payment.id,
        event_type="STATUS_CHANGED",
        from_status=from_status,
        to_status=new_status,
        payload=payload,
        created_at=datetime.utcnow(),
    )
    db.add(status_event)
    db.flush()

    # 2) Derive ledger events (only for terminal money states)
    ledger_events = ledger_events_for_transition(
        payment=payment,
        from_status=from_status,
        to_status=new_status,
        correlation_id=status_event.id,
        status_event_id=status_event.id,
    )
    for le in ledger_events:
        db.add(le)
        db.flush()   # assigns le.id without committing

        # 3) Derive double-entry postings for each ledger event
        journal_entry, postings = project_to_postings(le)
        db.add(journal_entry)
        db.flush()   # assigns journal_entry.id

        for posting in postings:
            posting.journal_entry_id = journal_entry.id
            db.add(posting)

    # 4) Atomic commit — status event, ledger event, journal entry,
    #    and both postings all commit together, or none do.
    db.commit()
    db.refresh(payment)

    return {
        "status": "accepted",
        "payment_id": payment.id,
        "from_status": from_status,
        "to_status": new_status,
    }


from datetime import datetime as _dt
from typing import Optional as _Optional


@app.get("/accounts/{account_code}/balance")
def get_account_balance(
    account_code: str,
    as_of: _Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Return the balance of an account as of a given time.

    Query params:
        as_of: ISO 8601 timestamp. Defaults to now.

    Response:
        {
            "account_code": "1000",
            "as_of": "2026-10-11T12:00:00",
            "total_debit": 50000,
            "total_credit": 0,
            "net": 50000
        }
    """
    if as_of is None:
        as_of_dt = _dt.utcnow()
    else:
        try:
            as_of_dt = _dt.fromisoformat(as_of)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="as_of must be ISO 8601, e.g. 2026-10-11T12:00:00",
            )

    return get_balance(db, account_code, as_of_dt)


@app.get("/replay/verify")
def replay_verify(db: Session = Depends(get_db)):
    """
    Rebuild the ledger from ledger_events and compare to live postings.

    Returns:
        {
            "live_count": int,
            "rebuilt_count": int,
            "deterministic": bool,
            "differences": [...]
        }
    """
    return verify_replay(db)


from pydantic import BaseModel as _BaseModel


class _SettlementRow(_BaseModel):
    reference: str
    amount_kobo: int


class _ReconcileRequest(_BaseModel):
    settlement_rows: list[_SettlementRow]


@app.post("/reconcile/run")
def reconcile_run(req: _ReconcileRequest, db: Session = Depends(get_db)):
    """
    Reconcile the ledger against an external settlement file.

    Body:
        {
            "settlement_rows": [
                {"reference": "PAY-001", "amount_kobo": 10000},
                ...
            ]
        }

    Returns a run summary and the list of exceptions.
    """
    rows = [r.model_dump() for r in req.settlement_rows]
    return reconcile(db, rows)


@app.get("/exceptions")
def list_exceptions(
    status: _Optional[str] = None,
    classification: _Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    List exceptions, newest first. Optional filters by status and classification.
    """
    q = db.query(Exception)
    if status:
        q = q.filter(Exception.status == status)
    if classification:
        q = q.filter(Exception.classification == classification)
    rows = q.order_by(Exception.created_at.desc()).all()

    return {
        "count": len(rows),
        "items": [
            {
                "id": r.id,
                "run_id": r.run_id,
                "classification": r.classification,
                "reference": r.reference,
                "amount_kobo": r.amount_kobo,
                "status": r.status,
                "created_at": r.created_at.isoformat(),
                "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
                "resolution_note": r.resolution_note,
            }
            for r in rows
        ],
    }


class _ResolveRequest(_BaseModel):
    note: str = ""


@app.post("/exceptions/{exception_id}/resolve")
def resolve_exception(
    exception_id: str,
    req: _ResolveRequest,
    db: Session = Depends(get_db),
):
    """
    Mark an exception as resolved with an optional note.
    """
    from datetime import datetime as _dt_now

    row = db.query(Exception).filter(Exception.id == exception_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Exception not found")

    if row.status == "RESOLVED":
        return {
            "id": row.id,
            "status": row.status,
            "already_resolved": True,
        }

    row.status = "RESOLVED"
    row.resolved_at = _dt_now.utcnow()
    row.resolution_note = req.note or None
    db.commit()
    db.refresh(row)

    return {
        "id": row.id,
        "status": row.status,
        "resolved_at": row.resolved_at.isoformat(),
        "resolution_note": row.resolution_note,
    }
