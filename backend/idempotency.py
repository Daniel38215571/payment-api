import hashlib
import json
from datetime import datetime, timedelta
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from models import IdempotencyKey


KEY_TTL_HOURS = 24


def _hash_request(body: dict) -> str:
    """Deterministic hash of a request body."""
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.utcnow()


def check_key(db: Session, key: str, body: dict) -> Tuple[str, Optional[str], Optional[int]]:
    """
    Check an idempotency key.

    Returns one of:
      ("new", None, None)                -> no key exists; proceed with the request
      ("replay", response_body, status)  -> key exists with same body; return cached
      ("conflict", None, None)           -> key exists but with different body; reject
      ("expired", None, None)            -> key exists but has expired; treat as new
    """
    existing = db.query(IdempotencyKey).filter(IdempotencyKey.key == key).first()

    if existing is None:
        return ("new", None, None)

    if existing.expires_at < _now():
        db.delete(existing)
        db.commit()
        return ("expired", None, None)

    if existing.request_hash != _hash_request(body):
        return ("conflict", None, None)

    return ("replay", existing.response_body, existing.response_status)


def store_response(db: Session, key: str, body: dict, response_body: str, response_status: int) -> None:
    """Store the response for a key so future replays return the same result."""
    record = IdempotencyKey(
        key=key,
        request_hash=_hash_request(body),
        response_body=response_body,
        response_status=response_status,
        created_at=_now(),
        expires_at=_now() + timedelta(hours=KEY_TTL_HOURS),
    )
    db.add(record)
    db.commit()
