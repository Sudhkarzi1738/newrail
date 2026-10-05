from pydantic import BaseModel, EmailStr, Field

from app.models.platform import LeadStatus, Product, ResourceType


class ReportRequestIn(BaseModel):
    name: str = Field(max_length=200)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=30)
    organization: str | None = Field(default=None, max_length=200)
    candidate_id: int | None = None
    constituency_id: int | None = None
    request_type: str = Field(default="full_report", pattern="^(full_report|retainer|strategy_brief|other)$")
    message: str | None = Field(default=None, max_length=4000)
    create_order: bool = False  # if true AND authenticated, an order for the report unlock is returned


class OrderOut(BaseModel):
    payment_id: int
    razorpay_order_id: str
    amount_paise: int
    currency: str
    razorpay_key_id: str


class ReportRequestOut(BaseModel):
    id: int
    status: LeadStatus
    message: str = "Thanks - our team will reach out shortly."
    order: OrderOut | None = None


class OrderIn(BaseModel):
    product: Product
    resource_type: ResourceType | None = None
    resource_id: int | None = None
    report_request_id: int | None = None


class VerifyIn(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class VerifyOut(BaseModel):
    status: str
    fulfilled: bool
