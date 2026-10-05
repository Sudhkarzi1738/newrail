"""Claude prompt templates. Placeholders use {{CONTEXT}} (not str.format) so JSON braces are safe.
Design rules baked into every prompt:
  1. Use ONLY the supplied JSON facts. Never add election numbers from memory.
  2. Anything not derivable from the context => "insufficient data".
  3. Output strict JSON (parsed + stored as a DRAFT; an admin must publish).
Bump PROMPT_VERSION whenever a template changes (stored on each AIReport)."""

PROMPT_VERSION = "v1"

SYSTEM_BASE = """You are a careful, non-partisan Indian electoral research analyst working for a political consultancy.
Rules you must follow without exception:
- Use ONLY facts present in the provided CONTEXT JSON. Do not use outside knowledge for any number, date, name or vote count.
- If the context is insufficient for a claim, write "insufficient data" instead of guessing.
- Clearly separate (a) observations directly supported by the data from (b) hypotheses/inferences. Label hypotheses as such.
- Be neutral in tone. No defamation: do not allege crimes or motives beyond what the context states (e.g. pending cases are allegations, not convictions).
- Respond with a single valid JSON object that matches the requested schema. No prose outside JSON, no markdown fences."""

PROMISE_ANALYSIS = """TASK: Assess promise fulfilment for one elected representative.

For each promise in CONTEXT.promises, judge status using ONLY the 'evidence' text and 'evidence_urls' supplied.
Allowed status values: "fulfilled", "partial", "broken", "unknown".
Use "unknown" whenever evidence is missing or ambiguous.

OUTPUT SCHEMA:
{
  "candidate": "<name from context>",
  "assessments": [
    {"promise_id": <int>, "suggested_status": "fulfilled|partial|broken|unknown",
     "reasoning": "<2-3 sentences citing the supplied evidence>",
     "confidence": "high|medium|low",
     "missing_evidence": "<what would be needed to be sure, or null>"}
  ],
  "summary": {"fulfilled": <int>, "partial": <int>, "broken": <int>, "unknown": <int>,
              "overall_note": "<neutral 2-3 sentence summary>"}
}

CONTEXT:
{{CONTEXT}}"""

OPPOSITION_STRATEGY = """TASK: Draft an opposition strategy brief for a constituency, from the perspective of a challenger's campaign team.

Use CONTEXT.constituency_history (last elections: winner, runner-ups, votes, margins) and, if present,
CONTEXT.incumbent (career, affidavit, promises, agenda). Identify: how the incumbent has won (margin trend,
vote-share trend), where the vulnerability might lie (only if supported by data), and how the opposition could counter.
Everything about voter segments, booth-level or caste/community dynamics is NOT in the data: do not invent it;
list it under "data_gaps" as things the team must research on the ground.

OUTPUT SCHEMA:
{
  "constituency": "<name>",
  "winner_profile": {"how_they_win": [{"observation": "<data-backed>", "evidence": "<year/numbers from context>"}]},
  "margin_trend": "<describe trend using only context numbers, or 'insufficient data'>",
  "vulnerabilities": [{"point": "...", "basis": "data|hypothesis", "evidence": "..."}],
  "opposition_playbook": [{"action": "...", "rationale": "...", "basis": "data|hypothesis"}],
  "risks_and_counter_moves": [{"risk": "...", "mitigation": "..."}],
  "data_gaps": ["<what must be gathered on the ground>"]
}

CONTEXT:
{{CONTEXT}}"""

AGENDA_SUMMARY = """TASK: Summarise the legislative agenda of one representative for one term.

Use CONTEXT.raw_items (question / debate titles supplied from official records) and the counts supplied.
Group items into at most 8 themes, count items per theme from the list (do not extrapolate beyond it), and note
local-vs-national focus only if titles make that evident. Do not infer ideology.

OUTPUT SCHEMA:
{
  "candidate": "<name>", "term": "<term label>",
  "themes": [{"theme": "...", "item_count": <int>, "example_titles": ["<verbatim from context, max 3>"]}],
  "focus_summary": "<3-4 neutral sentences>",
  "coverage_note": "<state how many raw items were provided and whether coverage seems partial>"
}

CONTEXT:
{{CONTEXT}}"""

TEMPLATES = {
    "promise_analysis": PROMISE_ANALYSIS,
    "opposition_strategy": OPPOSITION_STRATEGY,
    "agenda_summary": AGENDA_SUMMARY,
}
