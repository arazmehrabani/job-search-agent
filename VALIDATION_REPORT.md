# Job Search Agent V1.8.1 — Validation Report

## Automated test suite

Command:

```text
python -m unittest discover -s tests -v
```

Result: **65 / 65 tests passed**.

The suite includes all prior parser, deduplication, employment/language, CV selection, feedback learning, telemetry, HTTP throttling/robots/cache, semantic evidence audit, source discovery, Windows/Codex UTF-8, and V1.8 relevance-gate regressions.

### V1.8.1 regressions added

- 8-14 day vacancies remain fully eligible.
- 15-30 day vacancies survive the cheap filter for live-page confirmation.
- 31-45 day automatic vacancies require a strong target title.
- `DE` and city-only German locations do not receive a false location penalty.
- Explicit foreign-country locations still receive the light location penalty.
- BA titles remove search-result ranks and duplicated `bei <company>` suffixes.
- Software/frontend product-design titles are rejected locally.
- Dashboard shows contextual German importance clearly.
- AI-rejected audit rows retain detailed reasoning.
- Per-run AI call/token telemetry is rendered from `last_run_report.json`.

## Python compilation

```text
python -m compileall -q .
```

Result: **passed**.

## Base CV compilation

All sanitized master CV templates compile successfully with pdfLaTeX:

- `mechanical_de_master.tex` → 2 pages
- `mechanical_en_master.tex` → 2 pages
- `wind_de_master.tex` → 2 pages
- `wind_en_master.tex` → 2 pages
- `wind_thesis_en_master.tex` → 2 pages

## Recommended first validation run

Use `run_once(dry_run=True)` and review:

- `output/dashboard.html`
- `output/discovery_report.json`
- `output/search_plan.json`
- `output/last_run_report.json`

The most important expected change from V1.8 is that relevant 8-30 day jobs are no longer thrown away solely because they are older than seven days, while obvious unrelated roles still die before detail-page/Codex work.
