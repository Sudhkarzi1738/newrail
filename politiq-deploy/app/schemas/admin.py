from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.platform import AIKind, AIStatus, JobStatus, LeadStatus, Role
from app.models.political import ReviewStatus


class IngestionJobOut(BaseModel):
    id: int
    source: str
    profile: str
    status: JobStatus
    stats: dict | None
    error: str | None
    created_at: datetime
    model_config = {"from_attributes": True}


class IngestTriggerIn(BaseModel):
    source: Literal["eci", "lokdhaba", "myneta"]
    profile: str
    server_file_path: str  # file already placed under UPLOAD_DIR (e.g. a downloaded Lok Dhaba CSV)
    election_id: int | None = None


class UserPatchIn(BaseModel):
    role: Role | None = None
    is_active: bool | None = None


class GrantSubscriptionIn(BaseModel):
    plan: str = "manual"
    days: int = Field(gt=0, le=3650)


class AIGenerateIn(BaseModel):
    kind: AIKind
    candidate_id: int | None = None
    constituency_id: int | None = None


class AIReviewIn(BaseModel):
    action: Literal["publish", "reject"]
    notes: str | None = None
    edited_content: dict | None = None  # reviewer may correct the JSON before publishing


class AIReportAdminOut(BaseModel):
    id: int
    kind: AIKind
    status: AIStatus
    candidate_id: int | None
    constituency_id: int | None
    content: dict | None
    content_text: str | None
    input_snapshot: dict | None
    model: str
    created_at: datetime
    model_config = {"from_attributes": True}


class LeadPatchIn(BaseModel):
    status: LeadStatus | None = None
    admin_notes: str | None = None


class ContentReviewIn(BaseModel):
    review_status: ReviewStatus
