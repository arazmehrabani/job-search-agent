# V1.8 Changelog

V1.8 fixes the relevance and evaluation-budget problem exposed by the first large V1.7 discovery run.

## Relevance gate

- Added `src/relevance.py` with a conservative title gate and post-enrichment domain gate.
- Pure backend/frontend/full-stack/DevOps/cloud/data-platform/software jobs are hard-rejected unless the title contains a defensible bridge such as simulation, control, CAE, robotics, PLM or wind/mechanical context.
- Sales/marketing, finance/HR/admin, and design/media titles are hard-rejected even when they contain industry buzzwords such as “renewable energy”.
- Ambiguous engineering titles survive the cheap title gate but must gain a real mechanical/CAE/wind/simulation/manufacturing/controls/validation domain signal from the vacancy text.
- Manual URLs bypass automatic domain rejection because they are explicit user review requests.

## PRE scoring

- Replaced the generic capability-hit PRE formula with a domain-anchored formula.
- Generic words (`engineer`, `development`, `project`, `automation`, `Python`) no longer create high scores by themselves.
- Backend software example regression: `Software Engineer, Backend Focused` -> PRE 0 / hard filter.
- Structural/mechanical/simulation target roles score substantially higher and reach AI screening first.

## Discovery quality

- Tightened default search anchors to mechanical/wind/CAE/FEA/structural/simulation/test/validation terms.
- Disabled AI-generated query expansion by default; Codex is reserved for job reasoning.
- Arbeitnow local catalogue matching now ignores generic query tokens such as `engineer` and requires the domain-bearing query terms to match.

## AI-budget allocation

- Candidate ordering is now relevance-rank first, then PRE score.
- Obvious wrong-domain titles are rejected before detail-page fetching and before any Codex call.
- Strong mechanical/CAE/wind/simulation candidates consume limited screen/deep-analysis slots before weak adjacent candidates.

## Employment bug fix

- Added `professional` to allowed employment states.
- Professional jobs are not filtered merely because an ATS failed to expose `Full time / regular` metadata.

## Dashboard

- Main table now shows jobs worth attention (`HIGH`, `REVIEW`, `LOW/POSSIBLE`) instead of every discovered database row.
- Hard-filtered and Priority `REJECT` rows move into a collapsed audit section.
- Added cards for title-gate rejects and vacancies eligible after relevance filtering.
- Hard-filtering clears stale V1.7 PRE/priority data so an old irrelevant score cannot remain actionable.

## Compatibility

All V1.6 reliability/evidence safeguards and V1.7.1 Windows UTF-8 Codex fixes are retained.
