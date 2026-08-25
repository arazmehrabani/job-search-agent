# V1.4.2 Validation Report

## Automated tests

- 23/23 tests passing.
- All V1.4.1 parsing, language, employment, deduplication, dashboard and identity-protection regressions are retained.
- New regression: a manually supplied job older than the automated freshness window is still evaluated when active.
- New regression: an automatically discovered job of the same age is still filtered by `search.max_age_days`.

## Blank-row fix

V1.4.1 inserted a parsed job into SQLite before applying the hard filters. If the job was then rejected by the 7-day freshness filter, the dashboard could show its title/company/location but no score. V1.4.2 changes the policy for `source=manual`: an explicitly supplied URL bypasses the age cutoff by default (`sources.manual_links.bypass_age_filter: true`) and receives an age warning in match risks. Automatic discovery sources keep the freshness filter.

The database also gains a migrated `filter_reason` field. Any future hard-filtered row is displayed as `Filtered: <reason>` rather than looking broken.

## Existing V1.4.1 fixes retained

- TÜV SÜD SuccessFactors portal-title/company parsing.
- Compact 13-column dashboard.
- `international` no longer matches internship.
- `fluent in German` and `German advantageous` handling.
- Canonical URL/source-ID deduplication.
- Heuristic PRE scores refresh after parser corrections.
- Windows Codex CLI discovery.
- Five sanitized CV evidence/base templates and identity protection.
