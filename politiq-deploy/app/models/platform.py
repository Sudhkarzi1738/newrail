import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, pg_enum


class Role(str, enum.Enum):
    PUBLIC = "public"
    PAID = "paid"
    ADMIN = "admin"


class ResourceType(str, enum.Enum):
    CANDIDATE = "candidate"
    CONSTITUENCY = "constituency"


class PaymentStatus(str, enum.Enum):
    CREATED = "created"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"


class Product(str, enum.Enum):
    REPORT_UNLOCK = "report_unlock"
    SUBSCRIPTION_MONTHLY = "subscription_monthly"


class LeadStatus(str, enum.Enum):
    NEW = "new"
    CONTACTED = "contacted"
    AWAITING_PAYMENT = "awaiting_payment"
    PAID = "paid"
    DELIVERED = "delivered"
    CLOSED = "closed"


class AIKind(str, enum.Enum):
    PROMISE_ANALYSIS = "promise_analysis"
    OPPOSITION_STRATEGY = "opposition_strategy"
    AGENDA_SUMMARY = "agenda_summary"


class AIStatus(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    REJECTED = "rejected"


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    hashed_password: Mapped[str] = mapped_column(String(100))
    full_name: Mapped[str | None] = mapped_column(String(200))
    organization: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[Role] = mapped_column(pg_enum(Role), default=Role.PUBLIC)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0)  # bump to revoke all tokens


class Subscription(Base, TimestampMixin):
    __tablename__ = "subscriptions"
    __table_args__ = (Index("ix_sub_user_ends", "user_id", "ends_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    plan: Mapped[str] = mapped_column(String(50))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    payment_id: Mapped[int | None] = mapped_column(ForeignKey("payments.id"))
    granted_by_admin_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class ReportEntitlement(Base, TimestampMixin):
    """One-time unlock of a specific candidate/constituency bundle."""
    __tablename__ = "report_entitlements"
    __table_args__ = (Index("ix_ent_lookup", "user_id", "resource_type", "resource_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    resource_type: Mapped[ResourceType] = mapped_column(pg_enum(ResourceType))
    resource_id: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payment_id: Mapped[int | None] = mapped_column(ForeignKey("payments.id"))


class Payment(Base, TimestampMixin):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    product: Mapped[Product] = mapped_column(pg_enum(Product))
    resource_type: Mapped[ResourceType | None] = mapped_column(pg_enum(ResourceType))
    resource_id: Mapped[int | None] = mapped_column(Integer)
    report_request_id: Mapped[int | None] = mapped_column(ForeignKey("report_requests.id"))
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    status: Mapped[PaymentStatus] = mapped_column(pg_enum(PaymentStatus), default=PaymentStatus.CREATED)
    razorpay_order_id: Mapped[str] = mapped_column(String(64), unique=True)
    razorpay_payment_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # idempotency marker


class ReportRequest(Base, TimestampMixin):
    """'Contact Us / Request Paid Report' lead. user_id is NULL for anonymous visitors."""
    __tablename__ = "report_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(30))
    organization: Mapped[str | None] = mapped_column(String(200))
    candidate_id: Mapped[int | None] = mapped_column(ForeignKey("candidates.id"))
    constituency_id: Mapped[int | None] = mapped_column(ForeignKey("constituencies.id"))
    request_type: Mapped[str] = mapped_column(String(50))  # full_report / retainer / strategy_brief / other
    message: Mapped[str | None] = mapped_column(Text)
    status: Mapped[LeadStatus] = mapped_column(pg_enum(LeadStatus), default=LeadStatus.NEW, index=True)
    admin_notes: Mapped[str | None] = mapped_column(Text)


class AIReport(Base, TimestampMixin):
    """Claude output. Never served to paying users until an admin sets status=PUBLISHED."""
    __tablename__ = "ai_reports"
    __table_args__ = (Index("ix_ai_lookup", "kind", "status", "candidate_id", "constituency_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[AIKind] = mapped_column(pg_enum(AIKind))
    candidate_id: Mapped[int | None] = mapped_column(ForeignKey("candidates.id"))
    constituency_id: Mapped[int | None] = mapped_column(ForeignKey("constituencies.id"))
    status: Mapped[AIStatus] = mapped_column(pg_enum(AIStatus), default=AIStatus.DRAFT)
    content: Mapped[dict | None] = mapped_column(JSONB)
    content_text: Mapped[str | None] = mapped_column(Text)  # raw text fallback if JSON parse failed
    input_snapshot: Mapped[dict | None] = mapped_column(JSONB)  # exact DB facts the model saw (audit/repro)
    model: Mapped[str] = mapped_column(String(80))
    prompt_version: Mapped[str] = mapped_column(String(20))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    disclaimer: Mapped[str] = mapped_column(Text)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_notes: Mapped[str | None] = mapped_column(Text)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_user_time", "user_id", "created_at"), Index("ix_audit_resource", "resource_type", "resource_id"))
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(80))  # paid_access, paid_denied, export, admin_upload, ai_review ...
    resource_type: Mapped[str | None] = mapped_column(String(50))
    resource_id: Mapped[str | None] = mapped_column(String(64))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    meta: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IngestionJob(Base, TimestampMixin):
    __tablename__ = "ingestion_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(50))  # eci / lokdhaba / myneta
    profile: Mapped[str] = mapped_column(String(50))
    file_path: Mapped[str] = mapped_column(Text)
    election_id: Mapped[int | None] = mapped_column(ForeignKey("elections.id"))
    status: Mapped[JobStatus] = mapped_column(pg_enum(JobStatus), default=JobStatus.QUEUED)
    stats: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
