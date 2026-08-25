# Job Search Agent V1.5.1 — Validation Report

Validation date: 2026-08-13

## Automated tests

```text
29 / 29 tests passed
```

The suite contains the existing V1.4.x regression tests plus V1.5 tests.

### Existing regression coverage retained

- tracking URL canonicalization
- Ashby enrichment and stable vacancy identity
- TÜV SÜD / SuccessFactors real portal shape
- portal heading is not mistaken for job title
- D&I boilerplate is not mistaken for company name
- `international` is not classified as internship
- `fluent in German` detection
- `German advantageous` is preferred, not mandatory
- German/English vacancy-language detection
- working-student/full-time/thesis employment classification
- manual old vacancy bypass vs automated age filter
- multi-CV source selection
- identity-protection round trip

### V1.5 coverage

- verified evidence retrieval selects wind/CAE evidence for relevant jobs
- Fit and Priority are separate values
- major German requirement can lower Priority without rewriting Fit
- feedback history can produce a bounded career-family preference adjustment
- Codex-first provider does not silently use OpenAI API merely because an API key exists
- AI usage/token/cost telemetry is stored in SQLite
- dashboard contains Fit, Priority and feedback controls

## Static code validation

```text
python -m compileall -q .
COMPILE_OK
```

## Pipeline smoke test

A no-source dry pipeline run completed successfully and returned:

```text
raw_found: 0
unique: 0
evaluated: 0
errors: []
parse_failures: []
```

This validates configuration loading, database initialization, query planning, evidence loading, priority/feedback infrastructure and pipeline return schema without external network dependencies.

## Doctor smoke test

The release package successfully checks:

- Python version
- Conda environment
- Codex executable/provider
- API credentials as optional
- LaTeX compiler
- pdfinfo
- all five CV sources
- identity placeholders
- profile
- career scope
- evidence registry
- assets directory
- output writability
- SQLite integrity

In the build environment, 33 verified evidence objects were loaded.

## CV privacy validation

The sanitized working CV templates were scanned for the previously shared real identity/contact strings. No matching real name/email/phone/LinkedIn values were found in the V1.5 working CV/profile files.

## Important runtime note

Codex authentication cannot be validated inside the release build container because the user's local ChatGPT/Codex login lives on their Windows machine. On the target machine run:

```powershell
codex exec "Reply only with CODEX_WORKS"
python agent.py doctor
```

and confirm the active backend is `codex_cli` before expecting deep matching or document generation.
