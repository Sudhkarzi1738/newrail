"""Read-side helpers shared by routers, exports and AI context builders. Returns plain dicts."""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.political import (
    Affidavit, Candidate, CandidateElection, Constituency, Election, Party, State,
)


def _aff(a: Affidavit | None) -> dict | None:
    if not a:
        return None
    return {
        "total_assets": a.total_assets, "total_liabilities": a.total_liabilities,
        "criminal_cases_total": a.criminal_cases_total, "criminal_cases_serious": a.criminal_cases_serious,
        "education": a.education, "profession": a.profession, "source_url": a.source_url,
    }


async def load_career(db: AsyncSession, candidate_id: int) -> dict | None:
    cand = await db.get(Candidate, candidate_id)
    if not cand:
        return None
    rows = (await db.execute(
        select(CandidateElection, Election, Constituency, State, Party, Affidavit)
        .join(Election, Election.id == CandidateElection.election_id)
        .join(Constituency, Constituency.id == CandidateElection.constituency_id)
        .join(State, State.id == Constituency.state_id)
        .outerjoin(Party, Party.id == CandidateElection.party_id)
        .outerjoin(Affidavit, Affidavit.candidate_election_id == CandidateElection.id)
        .where(CandidateElection.candidate_id == candidate_id)
        .order_by(Election.year.desc())
    )).all()
    entries = [{
        "election_id": e.id, "year": e.year, "house": e.house, "constituency_id": c.id,
        "constituency": c.name, "state": s.name, "party": p.name if p else None,
        "votes": ce.votes, "vote_share_pct": ce.vote_share_pct, "position": ce.position,
        "is_winner": ce.is_winner, "margin": ce.margin, "deposit_forfeited": ce.deposit_forfeited,
        "affidavit": _aff(a),
    } for ce, e, c, s, p, a in rows]
    won = sum(1 for x in entries if x["is_winner"])
    return {
        "candidate_id": cand.id, "person_id": cand.person_id, "name": cand.name,
        "identity_verified": cand.identity_verified, "contested": len(entries), "won": won,
        "lost": len(entries) - won, "entries": entries,
    }


async def load_results(db: AsyncSession, constituency_id: int, election_id: int) -> dict | None:
    head = (await db.execute(
        select(Constituency, State, Election)
        .join(State, State.id == Constituency.state_id)
        .join(Election, Election.id == election_id)
        .where(Constituency.id == constituency_id)
    )).first()
    if not head:
        return None
    c, s, e = head
    rows = (await db.execute(
        select(CandidateElection, Candidate, Party)
        .join(Candidate, Candidate.id == CandidateElection.candidate_id)
        .outerjoin(Party, Party.id == CandidateElection.party_id)
        .where(CandidateElection.constituency_id == constituency_id, CandidateElection.election_id == election_id)
        .order_by(CandidateElection.votes.desc())
    )).all()
    if not rows:
        return None
    top = rows[0][0].votes
    winner = next((r[0] for r in rows if r[0].is_winner), None)
    return {
        "constituency": c.name, "state": s.name, "election_year": e.year,
        "total_votes_recorded": sum(r[0].votes for r in rows),
        "margin": winner.margin if winner else None,
        "candidates": [{
            "candidate_id": cand.id, "name": cand.name, "party": p.name if p else None, "votes": ce.votes,
            "vote_share_pct": ce.vote_share_pct, "position": ce.position,
            "votes_behind_winner": top - ce.votes, "deposit_forfeited": ce.deposit_forfeited,
        } for ce, cand, p in rows],
    }


async def load_constituency_history(db: AsyncSession, constituency_id: int, limit: int = 5) -> dict | None:
    """Last N elections in a constituency, top-3 per election. Input for the opposition-strategy prompt."""
    c = await db.get(Constituency, constituency_id)
    if not c:
        return None
    elections = (await db.scalars(
        select(Election).join(CandidateElection, CandidateElection.election_id == Election.id)
        .where(CandidateElection.constituency_id == constituency_id)
        .group_by(Election.id).order_by(Election.year.desc()).limit(limit)
    )).all()
    history = []
    for e in elections:
        res = await load_results(db, constituency_id, e.id)
        if res:
            res["candidates"] = res["candidates"][:3]
            history.append(res)
    return {"constituency_id": c.id, "constituency": c.name, "house": c.house.value, "history": history}


async def latest_winner_row(db: AsyncSession, constituency_id: int, election_id: int | None):
    q = (select(CandidateElection, Candidate, Party, Election, Constituency, State)
         .join(Candidate, Candidate.id == CandidateElection.candidate_id)
         .join(Election, Election.id == CandidateElection.election_id)
         .join(Constituency, Constituency.id == CandidateElection.constituency_id)
         .join(State, State.id == Constituency.state_id)
         .outerjoin(Party, Party.id == CandidateElection.party_id)
         .where(CandidateElection.constituency_id == constituency_id, CandidateElection.is_winner.is_(True)))
    q = q.where(Election.id == election_id) if election_id else q.order_by(Election.year.desc())
    return (await db.execute(q.limit(1))).first()


async def count_candidates(db: AsyncSession) -> int:
    return await db.scalar(select(func.count(Candidate.id))) or 0
