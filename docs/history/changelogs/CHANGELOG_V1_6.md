# V1.6 Changelog

V1.6 is a reliability, safety and evidence-quality release built on V1.5.1.

## HTTP / career-site etiquette

- Added one shared per-host request policy for live-page verification.
- Default minimum delay: 1.5 seconds per host plus small jitter.
- Added bounded retry/backoff for HTTP 429 and 5xx responses.
- Respects `Retry-After` when present.
- Added persistent page caching (`output/http_cache.json`, default 120 minutes).
- Added cached `robots.txt` checks for arbitrary career-page fetching.
- `robots_disallowed` is recorded separately from `expired`.
- Official ATS/API source connectors remain separate from generic page fetching.

## Dashboard / local endpoint hardening

- Job URLs are restricted to `http://` and `https://` at ingestion and rendering.
- Unsafe schemes such as `javascript:`, `file:` and `data:` are rejected/disabled.
- Interactive feedback writes now require a random per-server session token.
- Feedback endpoint accepts only `application/json`.
- Request body is limited to 8 KiB.
- Fingerprints, decisions and reason length are validated.
- Feedback can only target a job that already exists in the local database.
- Dashboard server remains bound to `127.0.0.1` only.

## Semantic evidence retrieval

- Existing lexical evidence retrieval remains the cheap first pass.
- Jobs promoted to deep AI analysis now get a Codex/API semantic evidence-selection pass.
- Semantic selection chooses by meaning rather than exact token overlap and merges back lexical evidence for resilience.
- This happens only for deep-analysis candidates, not every discovered vacancy.

## Semantic claim-vs-evidence audit

- CV and cover-letter generation now require claim-level traces for READY status.
- The AI performs a final entailment audit of generated/reworded claims against cited evidence objects.
- The auditor is specifically told that `supported/assisted` does not justify `led/owned/managed`, and that separate facts do not justify invented tool coupling or causality.
- A major unsupported/overstated claim blocks `package_ready` and produces `needs_ai_or_review`.
- Audit output is saved as `semantic_evidence_audit.json` in each application package.
- Old V1.5 packages without a passing semantic audit are treated as needing V1.6 regeneration/review when they are otherwise eligible.

## AI second opinion on heuristics

- Fast Python career-family and German-requirement detection remain in place.
- Deep AI matching now stores a semantic career-family second opinion and confidence.
- Deep AI matching also stores contextual German-language importance/mandatory assessment.
- Contextual German importance is only a soft priority risk; it does not rewrite an explicit advertised requirement.

## Compatibility

- Keeps the V1.4.x TÜV SÜD / Ashby parsing regressions fixed.
- Keeps manual-link age bypass, Fit vs Priority, feedback learning, Codex-first provider safety, usage telemetry, bilingual multi-CV selection and LaTeX packaging.
- Same Conda/VS Code workflow and `vscode_runner.py` cells.

## Validation

- 39 automated tests pass.
- All five sanitized LaTeX CV bases compile successfully to 2 pages.
