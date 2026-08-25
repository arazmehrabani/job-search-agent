# Job Search Agent V1.7 — Validation Report

Validation date: 2026-08-14

## Automated tests

Command:

```text
python -m unittest discover -s tests -p "test*.py" -v
```

Result:

```text
44 tests passed
```

V1.7 adds regression coverage for:

- enabled-by-default operational broad discovery sources
- Bundesagentur search-result HTML parsing
- BA full-time vs student/internship/thesis search-category selection
- Arbeitnow catalogue fetching once for multiple search queries
- Germany filtering for the no-key catalogue source
- per-source query caps and rotating non-anchor queries

All V1.6 regression tests continue to pass, including:

- TÜV SÜD and Ashby parsing regressions
- manual-job freshness bypass
- safe URL schemes
- request throttling and page cache
- robots.txt enforcement
- dashboard feedback validation
- semantic evidence selection
- semantic claim-vs-evidence audit
- Fit vs Priority
- feedback learning
- Codex-first provider safety
- telemetry

## Discovery architecture validation

The default configuration now contains two broad sources that do not require the user to provide API credentials:

```text
arbeitsagentur  enabled
arbeitnow       enabled
```

Adzuna and Jooble explicitly report unavailable when their credentials are absent; empty Greenhouse/Lever/SmartRecruiters lists explicitly report that no watchlist targets are configured.

Every pipeline run writes `output/discovery_report.json` with per-source attempted/success/result counts and `automatic_discovery_active`.

## Network-safety design

The BA connector:

- dynamically checks robots.txt before search-page requests
- has a configurable minimum delay and jitter
- caps queries per run
- caps results per query
- uses the shared live-page policy for subsequent detail-page verification

Fresh automatically discovered vacancies with known publication dates proceed to enrichment. Known stale jobs are filtered first, reducing unnecessary page requests.

The release test suite uses mocked provider HTTP data; no mass external scraping was performed during package validation.

## Python validation

All project Python files compile successfully with `py_compile`.

## LaTeX / evidence behavior

V1.7 does not modify the V1.6 document templates or evidence/semantic-audit readiness gate. The previously validated five CV bases and V1.6 claim-trace safeguards are preserved unchanged.
