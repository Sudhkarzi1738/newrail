"""Column-mapping profiles. ECI / Lok Dhaba / MyNeta files change layout between years.
>>> The header aliases below are PLACEHOLDERS. VERIFY them against the real file before first load. <<<
A profile maps our canonical field -> list of accepted header names (case/space-insensitive)."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    name: str
    aliases: dict[str, list[str]]
    required: tuple[str, ...]


RESULTS_REQUIRED = ("state", "constituency", "candidate", "votes")

ECI_XLSX = Profile(
    name="eci_xlsx",
    aliases={
        "state": ["state name", "state"],                      # TODO verify against real ECI statistical report
        "constituency_no": ["pc no", "ac no", "constituency no"],
        "constituency": ["pc name", "ac name", "constituency name"],
        "candidate": ["candidate name", "candidate"],
        "party": ["party name", "party"],
        "votes": ["total votes", "total", "votes"],
        "vote_share_pct": ["% of votes", "vote share"],
        "position": ["position", "rank"],
        "gender": ["sex", "gender"],
    },
    required=RESULTS_REQUIRED,
)

LOKDHABA_CSV = Profile(
    name="lokdhaba_csv",
    aliases={
        "state": ["state_name", "state"],                      # TODO verify against real Lok Dhaba export
        "constituency_no": ["constituency_no", "pc_no", "ac_no"],
        "constituency": ["constituency_name", "pc_name", "ac_name"],
        "candidate": ["candidate", "candidate_name"],
        "party": ["party"],
        "votes": ["votes"],
        "vote_share_pct": ["vote_share_percentage", "vote_share"],
        "position": ["position"],
        "gender": ["sex", "gender"],
    },
    required=RESULTS_REQUIRED,
)

MYNETA_CSV = Profile(
    name="myneta_csv",
    aliases={
        "myneta_candidate_id": ["candidate id", "myneta id"],  # TODO verify
        "candidate": ["candidate", "name"],
        "constituency": ["constituency"],
        "total_assets": ["total assets"],
        "total_liabilities": ["liabilities"],
        "criminal_cases_total": ["criminal cases", "total cases"],
        "criminal_cases_serious": ["serious cases"],
        "education": ["education"],
        "profession": ["profession", "self profession"],
        "source_url": ["url", "source url"],
    },
    required=("candidate", "constituency"),
)

PROFILES = {p.name: p for p in (ECI_XLSX, LOKDHABA_CSV, MYNETA_CSV)}
