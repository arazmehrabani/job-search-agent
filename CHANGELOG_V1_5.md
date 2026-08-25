# V1.5 Changelog

## Decision quality

- Added separate **Fit** and **Application Priority** scores.
- Priority incorporates practical constraints without corrupting the underlying evidence-fit score.
- Added priority labels: HIGH / REVIEW / LOW / SKIP (or equivalent reject state).
- Added explicit priority reasons and deep-match decision reasons.

## Evidence traceability

- Added `input/evidence/evidence.json` with verified evidence IDs.
- AI screening/deep matching uses only relevant retrieved evidence instead of all CV text.
- Deep matching can return requirement-to-evidence mappings.
- Application packages write `evidence_sources.json` and `claim_trace.json`.

## AI efficiency

- Added tiered pipeline: local heuristic → compact AI screen → deep AI match → documents.
- Separate per-run screen and deep-evaluation budgets.
- Reduced job-description and evidence payload sizes.
- CV-based query planning uses compact evidence summaries instead of full multi-CV LaTeX.

## Provider/cost safety

- Default provider changed from `auto` to explicit `codex_cli`.
- `auto` no longer silently selects the paid OpenAI API.
- OpenAI API is used only when explicitly selected.
- Added per-call telemetry and optional cost estimation using user-configured rates.

## Feedback and learning

- Added APPLY / SAVE / SKIP / APPLIED / INTERVIEW / REJECTED / OFFER feedback states.
- Added SQLite feedback history.
- Added `output/feedback_summary.json`.
- Career-family feedback can make a small bounded adjustment to Priority after enough samples.
- Added interactive local dashboard server for feedback buttons.

## Notifications/dashboard

- Dashboard now shows Fit and Priority separately.
- Added AI source labels PRE / SCREEN / AI.
- Added evidence IDs and practical reasons in expandable analysis.
- Added user-decision controls.
- Added usage/token cards.
- Immediate desktop notification now depends on high Priority.
- Added review digest (`output/daily_digest.html`).

## Health checks

- Expanded `doctor()` for Python/Conda, Codex, LaTeX, SQLite, CV sources, placeholders, evidence registry and writable output.
- Optional `doctor --network` connectivity test.

## Preserved V1.4.2 fixes

- SuccessFactors/TÜV SÜD parsing fixes.
- Ashby parsing/deduplication.
- `international` no longer triggers internship classification.
- German requirement parsing such as `fluent in German` and `German advantageous`.
- Manual URL age bypass while active.
- Canonical URL deduplication and no parser ghost rows.
