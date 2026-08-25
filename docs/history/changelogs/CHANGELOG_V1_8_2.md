# V1.8.2 Changelog

V1.8.2 is a focused correction based on the real V1.8.1 run from 2026-08-14. That run proved Codex was functioning (40/40 successful matching calls) but also exposed an execution-mode misunderstanding: it was deliberately run with `dry_run=True`, so document generation and notifications were suppressed even though substantial AI matching work was performed.

## 1. Run modes are now explicit

`dry_run=True` is reported as `MATCH_ONLY` and prints a visible warning that CV/cover-letter generation and desktop notifications are disabled.

`dry_run=False` is reported as `FULL_APPLICATION_PREP` and may generate application packages and notifications. Auto-submission remains disabled.

VS Code helpers:

```python
result = match_only()
result = prepare_applications()
```

A MATCH_ONLY run reports `packages_would_generate` and `package_candidates` so the user can see which deep-matched jobs would receive files in full mode.

## 2. Global deep-AI budget allocation

V1.8.1 could spend a deep slot immediately after a job was screened, allowing an early result to consume the budget before a better later result was screened.

V1.8.2:

1. screens the ranked candidate queue up to `max_screen_per_run`;
2. collects every promoted candidate;
3. globally ranks the promoted candidates using AI screen score, local relevance/PRE, career tier, freshness and manual-job preference;
4. sends only the strongest `max_deep_per_run` candidates to semantic evidence selection + deep matching.

Promoted screen-only jobs that miss the deep budget are marked `deep_pending` and compete again on the next run without repeating the compact screen.

## 3. PRE/SCREEN can no longer become final HIGH/APPLY

Only a completed deep AI assessment can receive final `HIGH` / `APPLY` status.

If a PRE or SCREEN result calculates above the HIGH threshold, V1.8.2 caps it at `REVIEW` and records:

```text
Final HIGH/APPLY status requires a completed deep AI assessment.
```

Document generation therefore cannot be triggered by an unfinished PRE/SCREEN assessment.

## 4. Original application-preparation workflow made observable

A full run still follows the intended workflow:

```text
discover -> filter -> screen -> deep match -> priority
                                      ↓
                         eligible deep match
                                      ↓
                       tailor CV + cover letter
                                      ↓
                         evidence/claim audit
                                      ↓
                           compile .tex/.pdf
                                      ↓
                         desktop notification
```

Application packages are generated only when:

- the match is a completed deep Codex/API result;
- Priority is at least `package_generation_min` (default 74);
- the vacancy is not expired;
- the user has not marked it SKIP/NOT_INTERESTED;
- a valid current application package does not already exist.

Notifications are sent for high-priority ready packages. If a high-priority package is generated but fails READY checks, V1.8.2 sends a `needs package review` notification instead of silently withholding the notification.

## 5. Telemetry clarity

`output/last_run_report.json` now includes:

```text
execution_mode
document_generation_enabled
notifications_enabled
packages_would_generate
package_candidates
packages_ready
packages_needing_review
notifications_sent
stage_seconds
http
token_counts_note
```

Dashboard token wording is now `Estimated text tokens` and explicitly states that the value is a local text-length estimate, not official OpenAI plan usage/billing data.

## 6. Runtime / HTTP diagnostics while keeping polite throttling

The per-host anti-hammering policy remains enabled:

```yaml
http:
  min_delay_per_host_seconds: 1.5
  delay_jitter_seconds: 0.25
```

V1.8.2 adds HTTP telemetry for page fetches, cache hits, network requests, robots requests, retries, errors and total throttle sleep time.

It also applies the domain gate to source-supplied full descriptions before a redundant detail-page fetch when safe (notably Arbeitnow), and extends the default page cache from 120 to 360 minutes for repeated watch cycles.

## 7. Relevance cleanup

New local rejects include obvious SaaS/customer-support and commercial tender/bid/proposal-management titles:

```text
Founding Customer Support Engineer -> BUSINESS_SALES_MARKETING
Tender Manager Renewable Energy    -> BUSINESS_SALES_MARKETING
```

The latter does not reject technical engineering titles merely because they involve project/tender support; the explicit manager/bid-management title is the negative signal.

## 8. Bundesagentur title cleanup completed

After page enrichment, BA titles are normalized again once the employer is known, so:

```text
Mechanical Design Engineer (m/w/d) bei Loesche GmbH
```

becomes:

```text
Mechanical Design Engineer (m/w/d)
```

with the employer retained in the separate Company field.

## 9. LaTeX subprocess decoding

LaTeX and `pdfinfo` subprocess output now uses explicit UTF-8 decoding with replacement handling. This prevents non-UTF-8 German compiler output from causing a false package failure.

## Validation

- 71/71 automated tests pass.
- All 5 source CVs compile successfully to 2 pages.
- V1.7/V1.7.1 discovery, Codex UTF-8, relevance, freshness, evidence traceability, robots/throttling and dashboard regression tests remain green.
