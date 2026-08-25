# V1.7 Changelog

V1.7 is the **Discovery** release. It keeps V1.6 matching, evidence, semantic audit, HTTP safety, dashboard feedback and Codex behavior, while making automatic job discovery real and transparent.

## New broad discovery sources

- **Bundesagentur für Arbeit Jobsuche** — enabled by default, Germany-wide, no user API key required. Uses public search pages, dynamic robots.txt checking, per-host delay, a conservative per-run query budget and fresh-result filtering before detail-page verification.
- **Arbeitnow public API** — enabled by default, no API key. Downloads a small catalogue once per run and matches all selected career queries locally.

Adzuna and Jooble remain optional broad sources when credentials are supplied. Greenhouse, Lever and SmartRecruiters remain explicit company/ATS watchlists.

## Source health and observability

Every source now reports:

- category: broad / watchlist / inbox / manual
- configured/operational status
- whether it was attempted
- whether the search completed successfully
- number of queries used
- result count
- error/reason when unavailable

Each run writes `output/discovery_report.json` and the dashboard shows automatic-discovery status and source health.

New CLI command:

```text
python agent.py sources
```

If no broad source completes successfully, V1.7 reports:

```text
AUTOMATIC JOB SEARCH IS NOT ACTIVE
```

instead of silently returning only manual jobs.

## Query budgets and rotation

Network broad sources no longer have to receive all 32 planned queries every cycle.

- first anchor queries remain stable
- remaining source query slots rotate between runs
- state is saved to `output/source_query_rotation.json`

Default BA budget: 14 queries/run, 8 results/query, with 1.5 s minimum delay.

## Employment-stage search coverage

The default query plan now deliberately includes:

- `Werkstudent Maschinenbau`
- `Werkstudent Windenergie`
- `working student engineering`
- `Praktikum Maschinenbau`
- `Masterarbeit Windenergie`

BA searches automatically use its internship/trainee/student offer category for these queries.

## Request-efficiency improvements

- Automatically discovered jobs already known to be older than the configured freshness window are filtered before expensive live-page enrichment.
- Greenhouse and Lever board payloads are cached inside a run, so the same board is not redownloaded once per query.
- Arbeitnow is catalogue-fetched once and query-matched locally.

## Compatibility

- Existing V1.6 SQLite databases can be reused.
- V1.6 AI matches are not invalidated solely by the V1.7 discovery upgrade; the deep-match schema remains V1.6-compatible.
- All V1.6 safety/evidence gates remain active.
