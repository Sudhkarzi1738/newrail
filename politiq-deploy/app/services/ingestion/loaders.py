import logging
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.political import (
    Affidavit, Candidate, CandidateElection, Constituency, Election, Party, State,
)
from app.services.ingestion.profiles import PROFILES
from app.services.ingestion.readers import read_mapped

log = logging.getLogger(__name__)


def normalize_name(s: str) -> str:
    return re.sub(r"[^a-z ]", "", s.lower()).strip()


def _int(v) -> int | None:
    try:
        return int(float(str(v).replace(",", "").strip()))
    except (ValueError, TypeError):
        return None


def _dec(v) -> Decimal | None:
    try:
        return Decimal(str(v).replace(",", "").replace("%", "").strip())
    except (InvalidOperation, TypeError):
        return None


async def _get_or_create_state(db: AsyncSession, name: str) -> State:
    st = await db.scalar(select(State).where(func.lower(State.name) == name.strip().lower()))
    if not st:
        # TODO: seed canonical states/UTs with official codes first; this fallback uses a derived code.
        st = State(name=name.strip(), code=re.sub(r"[^A-Z]", "", name.upper())[:8])
        db.add(st)
        await db.flush()
    return st


async def _get_or_create_party(db: AsyncSession, name: str | None) -> Party | None:
    if not name:
        return None
    p = await db.scalar(select(Party).where(func.lower(Party.name) == str(name).strip().lower()))
    if not p:
        p = Party(name=str(name).strip())
        db.add(p)
        await db.flush()
    return p


async def _resolve_person(db: AsyncSession, name: str, state_id: int, gender: str | None) -> Candidate:
    """Conservative identity resolution. Auto-links ONLY when exactly one existing person with the same
    normalized name has contested in the same state; otherwise creates a new, UNVERIFIED person which an
    admin can merge later. Wrongly merging two people is worse than leaving a duplicate."""
    norm = normalize_name(name)
    matches = (await db.scalars(
        select(Candidate).join(CandidateElection, CandidateElection.candidate_id == Candidate.id)
        .join(Constituency, Constituency.id == CandidateElection.constituency_id)
        .where(Candidate.normalized_name == norm, Constituency.state_id == state_id).distinct()
    )).all()
    if len(matches) == 1:
        return matches[0]
    cand = Candidate(name=name.strip(), normalized_name=norm, gender=gender, identity_verified=False)
    db.add(cand)
    await db.flush()
    return cand


async def load_results(db: AsyncSession, path: Path, profile_name: str, election_id: int) -> dict:
    profile = PROFILES[profile_name]
    election = await db.get(Election, election_id)
    if not election:
        raise ValueError(f"Election {election_id} does not exist. Create it first.")
    stats = {"rows": 0, "loaded": 0, "skipped": 0, "errors": []}
    touched: set[int] = set()

    for r in read_mapped(path, profile):
        stats["rows"] += 1
        try:
            votes = _int(r.get("votes"))
            if votes is None or not r.get("candidate") or not r.get("constituency"):
                stats["skipped"] += 1
                continue
            state = await _get_or_create_state(db, str(r["state"]))
            number = _int(r.get("constituency_no")) or 0
            cons = await db.scalar(select(Constituency).where(
                Constituency.state_id == state.id, Constituency.house == election.house,
                func.lower(Constituency.name) == str(r["constituency"]).strip().lower()))
            if not cons:
                cons = Constituency(state_id=state.id, house=election.house, number=number, name=str(r["constituency"]).strip())
                db.add(cons)
                await db.flush()
            party = await _get_or_create_party(db, r.get("party"))
            person = await _resolve_person(db, str(r["candidate"]), state.id, r.get("gender"))
            ce = await db.scalar(select(CandidateElection).where(
                CandidateElection.candidate_id == person.id, CandidateElection.election_id == election_id,
                CandidateElection.constituency_id == cons.id))
            if ce is None:
                ce = CandidateElection(candidate_id=person.id, election_id=election_id, constituency_id=cons.id, votes=votes)
                db.add(ce)
            ce.votes, ce.party_id, ce.source = votes, party.id if party else None, profile.name
            if r.get("vote_share_pct") is not None:
                ce.vote_share_pct = _dec(r["vote_share_pct"])
            if r.get("position") is not None:
                ce.position = _int(r["position"])
            touched.add(cons.id)
            stats["loaded"] += 1
        except Exception as e:  # noqa: BLE001  - one bad row must not kill the job
            stats["errors"].append({"row": stats["rows"], "error": str(e)[:200]})
            if len(stats["errors"]) > 200:
                raise RuntimeError("Too many row errors; aborting.") from e
    await db.flush()
    for cid in touched:
        await recompute_derived(db, election_id, cid)
    stats["constituencies"] = len(touched)
    return stats


async def recompute_derived(db: AsyncSession, election_id: int, constituency_id: int) -> None:
    """Derives position / winner / margin / vote share / deposit status purely from loaded vote counts.
    Deposit rule (RP Act s.158): forfeited if a candidate gets <= 1/6 of valid votes polled in the constituency.
    Official ECI values loaded from the file are preserved where present (vote_share_pct, position)."""
    rows = (await db.scalars(
        select(CandidateElection).where(CandidateElection.election_id == election_id,
                                        CandidateElection.constituency_id == constituency_id)
        .order_by(CandidateElection.votes.desc()))).all()
    total = sum(r.votes for r in rows)
    if not rows or total == 0:
        return
    for i, r in enumerate(rows, start=1):
        r.position = r.position or i
        if r.vote_share_pct is None:
            r.vote_share_pct = (Decimal(r.votes) * 100 / Decimal(total)).quantize(Decimal("0.001"))
        r.deposit_forfeited = r.votes * 6 <= total
        r.is_winner = False
        r.margin = r.margin_pct = None
    # clear any previous winner first (partial unique index) then set the new one
    await db.flush()
    win = rows[0]
    win.is_winner = True
    if len(rows) > 1:
        win.margin = win.votes - rows[1].votes
        win.margin_pct = (Decimal(win.margin) * 100 / Decimal(total)).quantize(Decimal("0.001"))


async def load_affidavits(db: AsyncSession, path: Path, election_id: int) -> dict:
    """Attach MyNeta/ADR affidavit data to existing CandidateElection rows (match: myneta id, else name+constituency)."""
    profile = PROFILES["myneta_csv"]
    stats = {"rows": 0, "loaded": 0, "unmatched": 0}
    for r in read_mapped(path, profile):
        stats["rows"] += 1
        q = (select(CandidateElection).join(Candidate, Candidate.id == CandidateElection.candidate_id)
             .join(Constituency, Constituency.id == CandidateElection.constituency_id)
             .where(CandidateElection.election_id == election_id))
        if r.get("myneta_candidate_id"):
            q = q.where(Candidate.myneta_candidate_id == str(r["myneta_candidate_id"]))
        else:
            q = q.where(Candidate.normalized_name == normalize_name(str(r["candidate"])),
                        func.lower(Constituency.name) == str(r["constituency"]).strip().lower())
        matches = (await db.scalars(q)).all()
        if len(matches) != 1:
            stats["unmatched"] += 1
            continue
        ce = matches[0]
        aff = await db.scalar(select(Affidavit).where(Affidavit.candidate_election_id == ce.id)) or Affidavit(
            candidate_election_id=ce.id, candidate_id=ce.candidate_id)
        aff.total_assets, aff.total_liabilities = _dec(r.get("total_assets")), _dec(r.get("total_liabilities"))
        aff.criminal_cases_total, aff.criminal_cases_serious = _int(r.get("criminal_cases_total")), _int(r.get("criminal_cases_serious"))
        aff.education, aff.profession, aff.source_url = r.get("education"), r.get("profession"), r.get("source_url")
        db.add(aff)
        stats["loaded"] += 1
    return stats
