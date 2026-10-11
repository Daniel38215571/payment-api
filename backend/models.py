import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, JSON, Text
from sqlalchemy.orm import declarative_base, relationship


Base = declarative_base()


def generate_uuid():
    return str(uuid.uuid4())


class Payment(Base):
    __tablename__ = "payments"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    reference = Column(String(64), unique=True, nullable=False, index=True)
    amount_kobo = Column(Integer, nullable=False)
    currency = Column(String(3), nullable=False, default="NGN")
    customer_id = Column(String(64), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="PENDING", index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    events = relationship("Event", back_populates="payment", order_by="Event.created_at")


class Event(Base):
    __tablename__ = "events"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    payment_id = Column(String(36), ForeignKey("payments.id"), nullable=False, index=True)
    event_type = Column(String(50), nullable=False)
    from_status = Column(String(20), nullable=True)
    to_status = Column(String(20), nullable=True)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    payment = relationship("Payment", back_populates="events")


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    key = Column(String(64), primary_key=True)
    request_hash = Column(String(64), nullable=False)
    response_body = Column(Text, nullable=True)
    response_status = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)


class LedgerEvent(Base):
    __tablename__ = "ledger_events"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    payment_id = Column(String(36), ForeignKey("payments.id"), nullable=False, index=True)
    event_type = Column(String(50), nullable=False, index=True)
    amount_kobo = Column(Integer, nullable=False)
    currency = Column(String(3), nullable=False)
    event_time = Column(DateTime, nullable=False, default=datetime.utcnow)
    correlation_id = Column(String(36), nullable=False, index=True)
    status_event_id = Column(String(36), nullable=True)
    payload = Column(JSON, nullable=True)


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    ledger_event_id = Column(String(36), ForeignKey("ledger_events.id"), nullable=False, index=True)
    memo = Column(String(200), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    postings = relationship("Posting", back_populates="journal_entry", order_by="Posting.created_at")


class Posting(Base):
    __tablename__ = "postings"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    journal_entry_id = Column(String(36), ForeignKey("journal_entries.id"), nullable=False, index=True)
    account_code = Column(String(20), nullable=False, index=True)
    account_name = Column(String(80), nullable=False)
    debit_kobo = Column(Integer, nullable=False, default=0)
    credit_kobo = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    journal_entry = relationship("JournalEntry", back_populates="postings")
