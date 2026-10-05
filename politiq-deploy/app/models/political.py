"""Core electoral domain. NOTE: this repo ships NO election data. Load real data from ECI /
Lok Dhaba / MyNeta via app/services/ingestion (see README)."""
import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Date, DateTime, Enum, ForeignKey, Index, Integer,
    Numeric, String, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, pg_enum


class House(str, enum.Enum):
    LOK_SABHA = "lok_sabha"
    VIDHAN_SABHA = "vidhan_sabha"


class Reservation(str, enum.Enum):
    GENERAL = "general"
    SC = "sc"
    ST = "st"


class ElectionType(str, enum.Enum):
    GENERAL = "general"
    BYE = "bye"


class PromiseStatus(str, enum.Enum):
    FULFILLED = "fulfilled"
    PARTIAL = "partial"
    BROKEN = "broken"
    UNKNOWN = "unknown"


class ReviewStatus(str, enum.Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"


class State(Base, TimestampMixin):
    __tablename__ = "states"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    code: Mapped[str] = mapped_column(String(8), unique=True)  # e.g. ECI state code
    is_union_territory: Mapped[bool] = mapped_column(Boolean, default=False)
    constituencies: Mapped[list["Constituency"]] = relationship(back_populates="state")


class Party(Base, TimestampMixin):
    __tablename__ = "parties"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    abbreviation: Mapped[str | None] = mapped_column(String(30), index=True)
    recognition: Mapped[str | None] = mapped_column(String(30))  # national / state / unrecognised
    symbol: Mapped[str | None] = mapped_column(String(100))


class Constituency(Base, TimestampMixin):
    __tablename__ = "constituencies"
    __table_args__ = (
        UniqueConstraint("state_id", "house", "number", "delimitation_year", name="uq_constituency_identity"),
        Index("ix_constituency_name", "name"),
        Index("ix_constituency_state_house", "state_id", "house"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    state_id: Mapped[int] = mapped_column(ForeignKey("states.id"))
    house: Mapped[House] = mapped_column(pg_enum(House))
    number: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(150))
    district: Mapped[str | None] = mapped_column(String(150))
    reservation: Mapped[Reservation] = mapped_column(pg_enum(Reservation), default=Reservation.GENERAL)
    delimitation_year: Mapped[int] = mapped_column(Integer, default=2008)  # boundaries/numbers change
    state: Mapped[State] = relationship(back_populates="constituencies")


class Election(Base, TimestampMixin):
    __tablename__ = "elections"
    __table_args__ = (
        # state_id is NULL for Lok Sabha general elections; requires PostgreSQL 15+.
        UniqueConstraint("house", "state_id", "year", "election_type", name="uq_election_identity",
                         postgresql_nulls_not_distinct=True),
        Index("ix_election_house_year", "house", "year"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    house: Mapped[House] = mapped_column(pg_enum(House))
    state_id: Mapped[int | None] = mapped_column(ForeignKey("states.id"))
    year: Mapped[int] = mapped_column(Integer)
    election_type: Mapped[ElectionType] = mapped_column(pg_enum(ElectionType), default=ElectionType.GENERAL)
    election_date: Mapped[date | None] = mapped_column(Date)
    term_label: Mapped[str | None] = mapped_column(String(50))  # e.g. "18th Lok Sabha"
    source_ref: Mapped[str | None] = mapped_column(Text)  # URL / report ID of the official source


class Candidate(Base, TimestampMixin):
    """One row per real-world person. person_id lets us track a career across elections."""
    __tablename__ = "candidates"
    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), default=uuid.uuid4, unique=True)
    name: Mapped[str] = mapped_column(String(200))
    normalized_name: Mapped[str] = mapped_column(String(200), index=True)
    gender: Mapped[str | None] = mapped_column(String(20))
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    myneta_candidate_id: Mapped[str | None] = mapped_column(String(50), unique=True)
    identity_verified: Mapped[bool] = mapped_column(Boolean, default=False)  # False => needs admin merge review
    elections: Mapped[list["CandidateElection"]] = relationship(back_populates="candidate")


class CandidateElection(Base, TimestampMixin):
    __tablename__ = "candidate_elections"
    __table_args__ = (
        UniqueConstraint("candidate_id", "election_id", "constituency_id", name="uq_candidate_election"),
        # at most one winner per constituency per election
        Index("uq_one_winner", "election_id", "constituency_id", unique=True, postgresql_where=text("is_winner")),
        Index("ix_ce_constituency_election", "constituency_id", "election_id"),
        Index("ix_ce_candidate", "candidate_id"),
        Index("ix_ce_party", "party_id"),
        CheckConstraint("votes >= 0", name="votes_nonneg"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"))
    election_id: Mapped[int] = mapped_column(ForeignKey("elections.id"))
    constituency_id: Mapped[int] = mapped_column(ForeignKey("constituencies.id"))
    party_id: Mapped[int | None] = mapped_column(ForeignKey("parties.id"))
    votes: Mapped[int] = mapped_column(BigInteger)
    vote_share_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    position: Mapped[int | None] = mapped_column(Integer)
    is_winner: Mapped[bool] = mapped_column(Boolean, default=False)
    margin: Mapped[int | None] = mapped_column(BigInteger)  # winner only: votes over runner-up
    margin_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    deposit_forfeited: Mapped[bool | None] = mapped_column(Boolean)
    source: Mapped[str | None] = mapped_column(String(100))  # "eci_xlsx", "lokdhaba_csv", ...
    candidate: Mapped[Candidate] = relationship(back_populates="elections")
    election: Mapped[Election] = relationship()
    constituency: Mapped[Constituency] = relationship()
    party: Mapped[Party | None] = relationship()
    affidavit: Mapped["Affidavit | None"] = relationship(back_populates="candidate_election", uselist=False)


class Affidavit(Base, TimestampMixin):
    """Sourced from MyNeta / ADR. All money in INR."""
    __tablename__ = "affidavits"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_election_id: Mapped[int] = mapped_column(ForeignKey("candidate_elections.id"), unique=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    total_assets: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    total_liabilities: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    criminal_cases_total: Mapped[int | None] = mapped_column(Integer)
    criminal_cases_serious: Mapped[int | None] = mapped_column(Integer)
    education: Mapped[str | None] = mapped_column(String(150))
    profession: Mapped[str | None] = mapped_column(String(200))
    source_url: Mapped[str | None] = mapped_column(Text)
    candidate_election: Mapped[CandidateElection] = relationship(back_populates="affidavit")


class PromiseTracking(Base, TimestampMixin):
    __tablename__ = "promise_tracking"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    election_id: Mapped[int | None] = mapped_column(ForeignKey("elections.id"))
    promise_text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)  # manifesto page / speech / URL
    status: Mapped[PromiseStatus] = mapped_column(pg_enum(PromiseStatus), default=PromiseStatus.UNKNOWN)
    evidence: Mapped[str | None] = mapped_column(Text)
    evidence_urls: Mapped[list | None] = mapped_column(JSONB)
    ai_suggested: Mapped[bool] = mapped_column(Boolean, default=False)
    review_status: Mapped[ReviewStatus] = mapped_column(pg_enum(ReviewStatus), default=ReviewStatus.DRAFT)


class AgendaAnalysis(Base, TimestampMixin):
    __tablename__ = "agenda_analyses"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    house: Mapped[House] = mapped_column(pg_enum(House))
    term_label: Mapped[str] = mapped_column(String(50))
    questions_raised: Mapped[int | None] = mapped_column(Integer)
    debates_participated: Mapped[int | None] = mapped_column(Integer)
    attendance_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    raw_items: Mapped[list | None] = mapped_column(JSONB)  # question/debate titles loaded from Sansad/PRS/Assembly records
    key_issues: Mapped[list | None] = mapped_column(JSONB)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text)
    review_status: Mapped[ReviewStatus] = mapped_column(pg_enum(ReviewStatus), default=ReviewStatus.DRAFT)
