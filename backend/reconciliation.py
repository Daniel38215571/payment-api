"""
Reconciliation: match internal ledger postings against an external
settlement file (list of transactions the payment processor reports).

Design principle:
    The internal source of truth is the ledger (Posting + JournalEntry +
    LedgerEvent). The external source of truth is a settlement file.
    Reconciliation classifies every item into one of five buckets:

        MATCHED                   - both sides agree on reference + amount
        MISSING_IN_SETTLEMENT     - ledger has it, settlement does not
        MISSING_IN_LEDGER         - settlement has it, ledger does not
        AMOUNT_MISMATCH           - both have it, amounts differ
        DUPLICATE_IN_SETTLEMENT   - settlement reports the same ref twice

    Every non-MATCHED item becomes an Exception.
"""
from collections import defaultdict
from datetime import datetime
from uuid import uuid4


CLASSIFICATIONS = (
    "MATCHED",
    "MISSING_IN_SETTLEMENT",
    "MISSING_IN_LEDGER",
    "AMOUNT_MISMATCH",
    "DUPLICATE_IN_SETTLEMENT",
)


def _ledger_items(db):
    from models import LedgerEvent, Payment

    events = db.query(LedgerEvent).order_by(LedgerEvent.event_time).all()

    latest_per_payment = {}
    for le in events:
        latest_per_payment[le.payment_id] = le

    out = {}
    for payment_id, le in latest_per_payment.items():
        p = db.query(Payment).filter(Payment.id == payment_id).first()
        if p is None:
            continue
        out[p.reference] = {
            "reference": p.reference,
            "amount_kobo": int(le.amount_kobo),
            "event_type": le.event_type,
            "event_time": le.event_time.isoformat(),
        }
    return out


def _normalize_settlement(settlement_rows):
    by_ref = {}
    counts = defaultdict(int)
    for row in settlement_rows:
        ref = row.get("reference")
        counts[ref] += 1
        by_ref[ref] = row
    duplicates = {ref for ref, n in counts.items() if n > 1}
    return by_ref, duplicates


def reconcile(db, settlement_rows):
    ledger = _ledger_items(db)
    settlement, duplicates = _normalize_settlement(settlement_rows)

    run_id = str(uuid4())
    run_at = datetime.utcnow().isoformat()

    exceptions = []
    matched = 0

    for ref, ledger_item in ledger.items():
        if ref not in settlement:
            exceptions.append({
                "classification": "MISSING_IN_SETTLEMENT",
                "reference": ref,
                "amount_kobo": ledger_item["amount_kobo"],
                "internal_value": ledger_item,
                "external_value": None,
            })
            continue

        if ref in duplicates:
            exceptions.append({
                "classification": "DUPLICATE_IN_SETTLEMENT",
                "reference": ref,
                "amount_kobo": ledger_item["amount_kobo"],
                "internal_value": ledger_item,
                "external_value": settlement[ref],
            })
            continue

        external_amount = int(settlement[ref].get("amount_kobo", 0))
        if external_amount != ledger_item["amount_kobo"]:
            exceptions.append({
                "classification": "AMOUNT_MISMATCH",
                "reference": ref,
                "amount_kobo": abs(ledger_item["amount_kobo"] - external_amount),
                "internal_value": ledger_item,
                "external_value": settlement[ref],
            })
        else:
            matched += 1

    for ref, ext in settlement.items():
        if ref not in ledger:
            exceptions.append({
                "classification": "MISSING_IN_LEDGER",
                "reference": ref,
                "amount_kobo": int(ext.get("amount_kobo", 0)),
                "internal_value": None,
                "external_value": ext,
            })

    counts = {c: 0 for c in CLASSIFICATIONS}
    counts["MATCHED"] = matched
    for ex in exceptions:
        counts[ex["classification"]] += 1

    value_at_risk = sum(ex["amount_kobo"] or 0 for ex in exceptions)

    return {
        "run_id": run_id,
        "run_at": run_at,
        "matched": counts["MATCHED"],
        "missing_in_settlement": counts["MISSING_IN_SETTLEMENT"],
        "missing_in_ledger": counts["MISSING_IN_LEDGER"],
        "amount_mismatch": counts["AMOUNT_MISMATCH"],
        "duplicate_in_settlement": counts["DUPLICATE_IN_SETTLEMENT"],
        "value_at_risk_kobo": value_at_risk,
        "exceptions": exceptions,
    }
