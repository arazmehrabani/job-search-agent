# Job Search Agent V1.9.0 - Resource-Governed Architecture Correction

V1.9.0 is an architecture correction, not a tuning patch. It responds to the V1.8.3 full-run failure mode in which one cycle made 60 Codex calls, consumed almost the user's entire monthly Codex allowance, regenerated existing applications, and still left promising new vacancies without deep review.

## Governing rule

**Local computation first. Codex only where it changes a decision or creates a new deliverable. Expensive work is reused and is never repeated silently.**

Applications remain human-controlled and are never auto-submitted.

## Codex safety and quota control

- Ships with the reported official usage hint of **low remaining usage, reset date recorded in the local usage hint** and therefore starts **Codex-locked**.
- Adds fail-closed hard ceilings for provider attempts and estimated input volume:
  - 4 provider attempts per run
  - 35,000 estimated input tokens per run
  - 1 failed provider attempt per run
  - 4 provider attempts per day
  - 12 provider attempts per locally tracked allowance period
  - 35,000 estimated input tokens per day
  - 90,000 estimated input tokens per allowance period
- Adds a cross-project ledger at `~/.job_search_agent/codex_budget_ledger.jsonl`; copying the project or changing SQLite databases does not reset the safety counter.
- Provider attempts are reserved in the ledger before execution, including failed calls.
- If the ledger cannot be written, provider execution is blocked by default.
- An official-usage hint at or below the safety threshold locks Codex. A stale hint does not auto-unlock after the reset date; the user must update it from the real Usage UI.
- No silent paid API fallback was introduced.

## AI architecture

Removed from the normal execution path:

- routine `job_screen` calls
- routine semantic evidence-selection calls
- routine semantic claim-audit calls
- automatic AI claim-repair loops

New normal flow:

```text
Discovery
-> deterministic relevance/freshness/employment/language gates
-> local PRE + practical priority
-> reuse completed DEEP analyses
-> globally rank unresolved candidates
-> at most a few direct DEEP calls
-> rank NEW application candidates
-> at most a few single-call application bundles
-> deterministic evidence-trace QA
-> PDF validation
-> deduplicated notification
-> human review/application
```

Default full-run planning is intentionally small:

- at most 2 new direct DEEP evaluations
- reserve up to 2 calls for new application packages
- at most 2 new application packages
- hard maximum 4 provider attempts in the run

The input-volume limit can stop the run earlier.

## Application generation

- CV tailoring and cover-letter writing are combined into one structured `application_bundle` call per NEW job.
- The bundle returns the complete tailored CV LaTeX, cover-letter body, evidence IDs, claim traces, and supported recipient/reference metadata.
- German and English cover-letter templates follow the user's preferred recent application layout and substantive one-page style.
- Deterministic local trace QA validates claim-to-evidence links against the complete verified evidence registry.
- Ambiguous evidence is held for human review rather than silently spending additional Codex calls.
- PDF readiness checks the actual generated PDF artifact.

## Existing packages and cached intelligence

- Normal `prepare_applications()` **never regenerates an existing application package**, including `needs_ai_or_review` packages.
- Only explicit `repair_packages()` may regenerate an existing package.
- Existing completed V1.8.x/V1.9 DEEP analyses are reused.
- Jobs that already have application packages are not deep-refreshed during an ordinary search cycle.
- Missing application artifacts are reported instead of silently recreated.
- `output/application_index.json` distinguishes application-job count from company-folder count and records missing package directories.

## Better scarce-slot allocation

- Deep slots are selected using local practical priority as well as PRE/relevance/freshness/career-family data.
- Terminal feedback states do not consume deep slots.
- Existing packages do not consume deep slots.
- Explicit C1+/fluent-German vacancies are not given scarce Codex deep slots by default when verified German is B1, unless the job is manually supplied or the user has explicitly marked it `APPLY`/Interested.
- Strong locally ranked jobs remain visible and can generate a one-time local-candidate notification if AI is locked or deferred.

## Zero-Codex safe mode

- `local_preview()` is enforced as zero-provider execution by the pipeline itself.
- CLI `python agent.py run` is now the safe zero-Codex default.
- Full provider-enabled execution requires `python agent.py run --full` or `prepare_applications()`.
- `watch()` is zero-Codex by default.
- Recurring provider work requires explicit `watch_prepare()` and remains budget governed.

## HTTP behavior

The anti-hammering safeguards remain intact:

- minimum 1.5 s per-host delay
- jitter
- robots.txt handling
- retries/backoff
- cache

Runtime is reduced by requesting fewer unnecessary detail pages, not by reducing politeness. Detail enrichment is ranked/capped; lower-ranked jobs can be preserved as `discovered_unenriched` for later cycles instead of being discarded.

## Notifications and telemetry

- Notifications are deduplicated by `(job fingerprint, notification kind)`.
- Last-run telemetry reports resource-plan counts, provider attempts/success/failure, operation breakdown, local estimated text volume, HTTP activity, and stage timing.
- Local estimated tokens remain explicitly labeled as estimates and are never presented as official OpenAI account usage.
- Official Codex Usage UI remains authoritative.

## Upgrade rule

When moving from an existing project, copy BOTH:

```text
output/job_agent.sqlite3
output/applications/
```

Optionally copy a still-useful `output/http_cache.json`.

Do not copy transient dashboard/run-report files. If the database is copied without the applications directory, V1.9.0 reports the missing artifacts and does not silently spend AI to reconstruct them.
