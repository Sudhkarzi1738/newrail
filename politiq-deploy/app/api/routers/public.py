from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import NotFound
from app.core.rate_limit import RateLimiter
from app.db.session import get_db
from app.models.political import Candidate, CandidateElection, Constituency, Election, Party, State
from app.schemas.data import BasicResultOut, CandidateSearchOut, ConstituencyOut, ElectionOut
from app.services import queries

public_limit = RateLimiter(lambda: settings.rate_limit_public_per_min, "public")
router = APIRouter(prefix="/public", tags=["public"], dependencies=[Depends(public_limit)])


def _like(q: str) -> str:
    return "%" + q.replace("%", r"\%").replace("_", r"\_") + "%"


@router.get("/candidates", response_model=list[CandidateSearchOut])
async def search_candidates(q: str = Query(min_length=2, max_length=100), limit: int = Query(20, le=50),
                            db: AsyncSession = Depends(get_db)):
    cands = (await db.scalars(select(Candidate).where(Candidate.normalized_name.ilike(_like(q.lower())))
                              .order_by(Candidate.name).limit(limit))).all()
    if not cands:
        return []
    ids = [c.id for c in cands]
    rows = (await db.execute(
        select(CandidateElection.candidate_id, Election.year, Constituency.name, Party.name)
        .join(Election, Election.id == CandidateElection.election_id)
        .join(Constituency, Constituency.id == CandidateElection.constituency_id)
        .outerjoin(Party, Party.id == CandidateElection.party_id)
        .where(CandidateElection.candidate_id.in_(ids)).order_by(Election.year.desc())
    )).all()
    latest: dict[int, tuple] = {}
    for cid, year, cname, pname in rows:  # rows are newest-first; keep first seen per candidate
        latest.setdefault(cid, (year, cname, pname))
    return [CandidateSearchOut(id=c.id, person_id=c.person_id, name=c.name,
                               latest_election_year=latest.get(c.id, (None,) * 3)[0],
                               latest_constituency=latest.get(c.id, (None,) * 3)[1],
                               latest_party=latest.get(c.id, (None,) * 3)[2]) for c in cands]


@router.get("/constituencies", response_model=list[ConstituencyOut])
async def search_constituencies(q: str = Query(min_length=2, max_length=100), limit: int = Query(20, le=50),
                                db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Constituency, State.name).join(State, State.id == Constituency.state_id)
                             .where(Constituency.name.ilike(_like(q))).order_by(Constituency.name).limit(limit))).all()
    return [ConstituencyOut(id=c.id, name=c.name, number=c.number, house=c.house, state=s, reservation=c.reservation)
            for c, s in rows]


@router.get("/elections/recent", response_model=list[ElectionOut])
async def recent_elections(limit: int = Query(10, le=50), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Election, State.name).outerjoin(State, State.id == Election.state_id)
                             .order_by(Election.year.desc(), Election.election_date.desc().nullslast()).limit(limit))).all()
    return [ElectionOut(id=e.id, house=e.house, state=s, year=e.year, election_date=e.election_date,
                        term_label=e.term_label) for e, s in rows]


@router.get("/constituencies/{constituency_id}/result", response_model=BasicResultOut)
async def basic_result(constituency_id: int, election_id: int | None = None, db: AsyncSession = Depends(get_db)):
    """FREE tier: winner, party, margin, vote %. Nothing about opponents, history or analysis."""
    row = await queries.latest_winner_row(db, constituency_id, election_id)
    if not row:
        raise NotFound("No result found.")
    ce, cand, party, el, cons, st = row
    return BasicResultOut(constituency=cons.name, state=st.name, election_year=el.year, house=el.house,
                          winner_name=cand.name, party=party.name if party else None,
                          margin=ce.margin, vote_share_pct=ce.vote_share_pct)
