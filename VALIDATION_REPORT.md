# Job Search Agent V1.6 — Validation Report

Validation date: 2026-08-14

## Automated tests

Command:

```text
python -m unittest discover -s tests -p "test*.py" -v
```

Result:

```text
39 tests passed
```

The suite retains V1.4/V1.5 regression coverage and adds V1.6 checks for:

- HTTP/HTTPS-only URL policy
- database rejection of unsafe URL schemes
- dashboard non-rendering of unsafe `javascript:` links
- feedback payload validation
- per-host request throttling
- persistent page caching
- robots.txt disallow handling
- semantic evidence selection beyond lexical overlap
- semantic claim-vs-evidence rejection of an overstatement (`supported` → `led`)
- contextual German-language risk affecting application priority softly

Existing regressions still cover:

- TÜV SÜD SuccessFactors title/company/location extraction
- real TÜV portal boilerplate not becoming the company name
- `international` not becoming `internship`
- `fluent in German` detection
- `German advantageous` remaining preferred rather than required
- Ashby enrichment and source IDs
- tracking URL canonicalization/deduplication
- manual vacancy age bypass
- old automatically discovered vacancy filtering
- Fit vs Priority separation
- feedback learning
- Codex-first provider safety
- AI usage telemetry
- evidence retrieval for wind-load roles
- identity-line protection

## Python validation

All project Python files compile successfully with `py_compile`.

## LaTeX validation

All five sanitized working CV bases compile successfully with `pdflatex`:

```text
mechanical_de_master.tex   2 pages
mechanical_en_master.tex   2 pages
wind_de_master.tex         2 pages
wind_en_master.tex         2 pages
wind_thesis_en_master.tex  2 pages
```

## V1.6 readiness gate

For generated application packages with the default configuration, READY now requires:

1. AI/Codex document generation succeeded.
2. Required language tailoring checks passed.
3. Valid evidence IDs exist for CV and cover letter.
4. Material claim traces exist for both CV and cover letter.
5. Semantic claim-vs-evidence audit passes.
6. Required PDFs compile when PDF compilation is enabled.

A semantic-audit failure or unsupported major claim produces a review package instead of READY.

## Network policy notes

The V1.6 HTTP layer includes request throttling, page cache, retry/backoff, Retry-After handling and robots.txt checks. Unit tests use mocked HTTP responses; the release validation did not mass-fetch external career sites.
