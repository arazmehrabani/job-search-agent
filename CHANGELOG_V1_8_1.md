# V1.8.1 Changelog

V1.8.1 is a focused correction release based on the first real V1.8 discovery/dashboard review. It keeps the V1.8 relevance-gate architecture and fixes the remaining issues that were reducing useful job coverage or distorting Priority.

## 1. Staged freshness instead of a 7-day hard cutoff

The old automatic rule rejected every vacancy older than seven days. That discarded highly relevant roles such as Berechnungsingenieur, NVH, structural dynamics, mechanical integrity and validation jobs before they could be checked.

Default policy is now:

- **0-7 days:** fresh, highest evaluation preference.
- **8-14 days:** fully eligible with no freshness penalty.
- **15-30 days:** eligible when the live vacancy page confirms the job is still active; a small Priority freshness penalty is applied.
- **31-45 days:** only strong target titles are considered, and only with confirmed live status; a larger Priority freshness penalty is applied.
- **>45 days:** automatically filtered unless the URL was supplied manually.

Freshness is also used when allocating scarce Codex budget: within the same relevance tier, fresher jobs are evaluated first.

## 2. Germany location normalization

`Düsseldorf, Nordrhein-Westfalen, DE`, `Hamburg`, `Germany` and `Deutschland` are now treated consistently for a Germany-targeted search. City-only German locations no longer receive the false `Location may be outside preferred area` penalty. Explicit foreign-country locations still receive the configured light penalty.

## 3. Bundesagentur title cleanup

BA result labels such as:

`4: Mechanical Design Engineer (m/w/d) bei Loesche GmbH`

are normalized to:

`Mechanical Design Engineer (m/w/d)`

while `Loesche GmbH` remains in the structured company field. This keeps title-based scoring, deduplication and package naming cleaner.

## 4. Clearer German-language display

The dashboard now distinguishes the advertised explicit requirement from Codex's contextual assessment. Examples:

- `Not explicit`
- `Not explicit ⚠ likely important`
- `Not explicit ⚠ likely mandatory`
- `B2/good required`
- `C1+/fluent required`

The detailed analysis retains the contextual reason when available.

## 5. Additional local rejection for software product-design roles

Titles dominated by software/frontend/digital product design (for example `Director of Product Design, Frontend Technologies...`) are now rejected locally under `SOFTWARE_PRODUCT_DESIGN` when no relevant physical/mechanical engineering bridge exists. They do not need a Codex call.

## 6. Per-run AI telemetry

Each completed pipeline run now writes:

`output/last_run_report.json`

with:

- AI calls this run
- estimated input/output tokens this run
- calls/tokens by AI operation
- screen/deep counts
- discovery/relevance/freshness counts

The dashboard shows **AI calls this run / Tokens this run** separately from the daily totals.

## 7. AI-rejected jobs keep their reasoning

The hidden audit table now preserves a `why rejected` expander for evaluated jobs, including match dimensions, missing requirements, risks, evidence IDs, decision reasons and reasoning. This makes low-scoring structural/mechanical jobs auditable instead of reducing them to `Priority decision: REJECT`.

## Compatibility

- Codex remains `codex_cli` by default; there is still no silent paid API fallback.
- Existing evidence, feedback, dashboard feedback API, robots/throttling/cache and semantic claim-audit protections are retained.
- `analysis_version` is now `1.8.1`, so cached V1.8 AI matches are refreshed when rediscovered.
- Old `max_age_days` custom configuration is still recognized as a fallback, but the new staged freshness fields are preferred.
