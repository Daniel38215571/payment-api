from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class PaymentCreate(BaseModel):
    amount_kobo: int = Field(..., gt=0)
    currency: str = Field(default="NGN", max_length=3, min_length=3)
    customer_id: str = Field(..., min_length=1, max_length=64)


class PaymentResponse(BaseModel):
    id: str
    reference: str
    amount_kobo: int
    currency: str
    customer_id: str
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class EventResponse(BaseModel):
    id: str
    event_type: str
    from_status: Optional[str] = None
    to_status: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
