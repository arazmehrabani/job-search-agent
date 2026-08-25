# Validation Report - Job Search Agent V1.9.0

Validation date: 2026-08-14

## Automated regression suite

```text
87 passed
```

Command:

```text
python -m pytest -q
```

Coverage includes all prior regression families plus V1.9 resource-governance safeguards.

V1.9-specific regressions verify:

- shipped low-remaining-usage hint locks provider execution
- global ledger prevents a copied/new project folder from resetting the daily budget
- provider budget is reserved before subprocess execution
- failed provider calls count toward the breaker/budget
- LOCAL_PREVIEW performs zero AI/provider calls
- normal full runs do not regenerate existing `needs_ai_or_review` packages
- existing application jobs are not needlessly deep-refreshed
- explicit repair is the only regeneration route and is capped
- routine job SCREEN and semantic evidence-selection calls are absent from normal execution
- explicit C1+/fluent-German gaps can be handled locally rather than consuming scarce deep slots
- new-package generation is capped and overflow is queued
- one application-bundle call creates the CV and cover-letter payload
- deterministic trace QA distinguishes supported, missing and mismatched evidence links

## Python compilation

```text
python -m compileall -q .
```

Passed with no syntax errors.

## LaTeX/PDF validation

All five sanitized master CV templates compiled successfully with pdfLaTeX and remained two pages:

```text
mechanical_de_master.tex   2 pages
mechanical_en_master.tex   2 pages
wind_de_master.tex         2 pages
wind_en_master.tex         2 pages
wind_thesis_en_master.tex  2 pages
```

Both V1.9 cover-letter templates were instantiated, compiled, rendered and visually inspected:

```text
cover_letter_de.tex        1 page
cover_letter_en.tex        1 page
```

A layout regression found during validation (subject and salutation joining on one line) was corrected before release and both templates were re-rendered successfully.

## Database/backward-compatibility validation

A copy of an uploaded existing V1.8.x SQLite database was opened with the V1.9 schema/migration code and passed SQLite integrity checking. Existing application records were retained. The application index correctly distinguishes application jobs from company folders and reports missing artifact directories when only the database is copied.

This is why the V1.9 upgrade instructions require copying both:

```text
output/job_agent.sqlite3
output/applications/
```

## AI safety validation

No live Codex provider call was made during release validation.

The shipped `input/codex_usage_hint.json` records the user-reported official state:

```text
low remaining usage
reset date recorded in the local usage hint
```

The budget guard was verified to remain locked at that state. The hint does not automatically unlock merely because the reset date passes; the user must refresh it from the official Usage UI.

The default hard limits are:

```text
max provider attempts/run:                 4
max estimated input/run:              35,000
max failed attempts/run:                   1
max provider attempts/day:                 4
max provider attempts/allowance period:   12
max estimated input/day:              35,000
max estimated input/allowance period:  90,000
```

A cross-project provider-attempt ledger is stored outside the project folder so copying/versioning the agent cannot silently reset local safety counters.

## HTTP behavior

Per-host politeness was preserved:

```text
minimum delay/host: 1.5 s
jitter:             enabled
robots.txt:         enabled
retry/backoff:      enabled
cache:              enabled
```

V1.9 improves runtime by prioritizing/capping detail enrichment rather than by increasing request rate.

## Release conclusion

V1.9.0 passes automated, compile, template-render, database-compatibility and fail-closed budget tests. Its primary purpose is to prevent recurrence of the V1.8.3 resource failure mode while preserving discovery quality, existing expensive analyses, truthful application generation and human-controlled application submission.
