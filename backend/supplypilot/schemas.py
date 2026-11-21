from datetime import date
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator

class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Login(Input):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=256)

class Mutation(Input):
    expected_revision: int = Field(ge=1)

class Line(Input):
    sku: str = Field(min_length=1, max_length=80)
    quantity: int = Field(gt=0, le=1_000_000)
    unit: Literal['piece'] = 'piece'
    specs: dict[str, str] = Field(min_length=1, max_length=20)
    evidence_id: str | None = None

class RFQCreate(Input):
    title: str = Field(min_length=3, max_length=160)
    due_date: date
    lines: list[Line] = Field(min_length=1, max_length=20)
    @field_validator('lines')
    @classmethod
    def unique_skus(cls, v):
        if len({x.sku for x in v}) != len(v):
            raise ValueError('One line per SKU in the scoped baseline')
        return v

class RFQReview(Mutation):
    lines: list[Line] = Field(min_length=1, max_length=20)
    reason: str = Field(min_length=5, max_length=1000)
    @field_validator('lines')
    @classmethod
    def unique_skus(cls, v):
        return RFQCreate.unique_skus(v)

class Invite(Mutation):
    supplier_ids: list[str] = Field(min_length=1, max_length=30)

class OfferCreate(Input):
    expected_revision: int | None = Field(default=None, ge=1)
    rfq_id: str
    supplier_id: str
    sku: str
    quantity: int = Field(gt=0, le=1_000_000)
    unit: Literal['piece'] = 'piece'
    unit_price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    freight_per_piece: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    fixed_freight: Decimal = Field(default=Decimal('0.00'), ge=0, max_digits=12, decimal_places=2)
    moq: int = Field(default=1, ge=1, le=1_000_000)
    pack_size: int = Field(default=1, ge=1, le=1_000_000)
    currency: Literal['AED'] = 'AED'
    valid_until: date
    delivery_date: date
    specs: dict[str, str] = Field(min_length=1, max_length=20)
    evidence_id: str
    recipient: str = Field(min_length=5, max_length=200)
    terms: str = Field(min_length=3, max_length=500)

class Compliance(Mutation):
    certificate_verified: bool
    reason: str = Field(min_length=5, max_length=1000)

class PlanCreate(Input):
    rfq_id: str
    expected_revision: int = Field(ge=1)
    objective: Literal['cost', 'delivery'] = 'cost'
    budget: Decimal = Field(gt=0, max_digits=14, decimal_places=2)

class Decision(Mutation):
    decision: Literal['approved', 'rejected']
    reason: str = Field(min_length=5, max_length=1000)

class Execute(Mutation):
    key: str = Field(min_length=8, max_length=120, pattern=r'^[a-zA-Z0-9_-]+$')

class Dispatch(Input):
    simulate_timeout: bool = False

class Receipt(Mutation):
    order_id: str
    allocation_index: int = Field(ge=0)
    accepted: int = Field(ge=0)
    rejected: int = Field(ge=0)
    quarantine: int = Field(ge=0)
    evidence_id: str

class Invoice(Mutation):
    order_id: str
    allocation_index: int = Field(ge=0)
    invoice_number: str = Field(min_length=1, max_length=100)
    quantity: int = Field(gt=0)
    unit_price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    evidence_id: str

class InvoiceRecheck(Mutation):
    expected_order_revision: int = Field(ge=1)
    reason: str = Field(min_length=5, max_length=1000)

class ExceptionCreate(Input):
    resource_id: str
    category: str = Field(min_length=3, max_length=80)
    detail: str = Field(min_length=5, max_length=2000)
    owner: str
    due_date: date

class Resolve(Mutation):
    evidence_id: str
    reason: str = Field(min_length=5, max_length=1000)

class Search(Input):
    query: str = Field(min_length=2, max_length=500)

class Forecast(Input):
    values: list[float] = Field(min_length=8, max_length=500)
    @field_validator('values')
    @classmethod
    def nonnegative(cls, v):
        import math
        if any(not math.isfinite(x) or x < 0 for x in v):
            raise ValueError('Demand must be finite and nonnegative')
        return v

class Quote(Input):
    plan_id: str
    selling_price: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    discount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)

class Feedback(Input):
    resource_id: str
    correction: str = Field(min_length=5, max_length=2000)

class Release(Input):
    version: str = Field(min_length=3, max_length=80)
    evaluation_id: str
