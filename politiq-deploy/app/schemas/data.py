from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from app.models.political import House, PromiseStatus, Reservation


class Cta(BaseModel):
    message: str = "Full candidate history, all opponents, promise tracking, agenda and strategy analysis are available in our paid report."
    action: str = "request_full_report"
    endpoint: str = "/api/v1/report-requests"


# ---------- Public ----------
class CandidateSearchOut(BaseModel):
    id: int
    person_id: UUID
    name: str
    latest_election_year: int | None = None
    latest_constituency: str | None = None
    latest_party: str | None = None


class ConstituencyOut(BaseModel):
    id: int
    name: str
    number: int
    house: House
    state: str
    reservation: Reservation


class ElectionOut(BaseModel):
    id: int
    house: House
    state: str | None
    year: int
    election_date: date | None
    term_label: str | None


class BasicResultOut(BaseModel):
    constituency: str
    state: str
    election_year: int
    house: House
    winner_name: str
    party: str | None
    margin: int | None
    vote_share_pct: Decimal | None
    cta: Cta = Cta()


# ---------- Paid ----------
class AffidavitOut(BaseModel):
    total_assets: Decimal | None
    total_liabilities: Decimal | None
    criminal_cases_total: int | None
    criminal_cases_serious: int | None
    education: str | None
    profession: str | None
    source_url: str | None


class CareerEntry(BaseModel):
    election_id: int
    year: int
    house: House
    constituency_id: int
    constituency: str
    state: str
    party: str | None
    votes: int
    vote_share_pct: Decimal | None
    position: int | None
    is_winner: bool
    margin: int | None
    deposit_forfeited: bool | None
    affidavit: AffidavitOut | None = None


class CareerOut(BaseModel):
    candidate_id: int
    person_id: UUID
    name: str
    identity_verified: bool
    contested: int
    won: int
    lost: int
    entries: list[CareerEntry]


class OpponentRow(BaseModel):
    candidate_id: int
    name: str
    party: str | None
    votes: int
    vote_share_pct: Decimal | None
    position: int | None
    votes_behind_winner: int
    deposit_forfeited: bool | None


class DetailedResultOut(BaseModel):
    constituency: str
    state: str
    election_year: int
    total_votes_recorded: int
    margin: int | None
    candidates: list[OpponentRow]


class PromiseOut(BaseModel):
    id: int
    promise_text: str
    source: str
    status: PromiseStatus
    evidence: str | None
    evidence_urls: list | None
    ai_suggested: bool
    disclaimer: str | None = None
    model_config = {"from_attributes": True}


class AgendaOut(BaseModel):
    id: int
    house: House
    term_label: str
    questions_raised: int | None
    debates_participated: int | None
    attendance_pct: Decimal | None
    key_issues: list | None
    ai_summary: str | None
    source: str | None
    disclaimer: str | None = None
    model_config = {"from_attributes": True}


class AIReportOut(BaseModel):
    id: int
    kind: str
    content: dict | None
    content_text: str | None
    disclaimer: str
    model: str
    reviewed_at: datetime | None
    model_config = {"from_attributes": True}
