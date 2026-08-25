# Job Search Agent V1.9.0

V1.9.0 is the **resource-governed architecture correction** release. It was designed after a V1.8.3 full run made 60 Codex calls, consumed almost all of the user's official monthly Codex allowance, regenerated old application packages, and still left several promising new jobs without deep review.

The design rule is now simple:

> **Local computation first. Codex only where it changes a decision or creates a new deliverable. Never repeat expensive AI work unless the user explicitly asks for repair or the job truly needs a new deep assessment.**

Applications are **never auto-submitted**. The agent prepares files and alerts the user; the user reviews and applies.

## Critical safety state in this release

The shipped `input/codex_usage_hint.json` records the official usage state reported on 2026-08-14:

- a low remaining provider allowance
- reset date: 2026-09-13

Therefore **Codex is intentionally LOCKED in the shipped V1.9.0 configuration**. Discovery and local ranking still work. No provider call can start while the official-usage hint is at or below the configured safety threshold.

After the official allowance resets, update the hint from the VS Code runner only after checking the real Usage UI, for example:

```python
set_codex_usage_hint(100, "2026-10-13")
```

Changing the reset date starts a new locally tracked allowance period.

## What changed architecturally

### 1. No routine AI SCREEN stage

Old flow:

```text
local PRE -> Codex SCREEN -> Codex evidence selection -> Codex DEEP
```

V1.9.0:

```text
local relevance + PRE + practical priority
                 -> rank globally
                 -> a few direct Codex DEEP reviews
```

`job_screen` is no longer part of the normal execution path.

### 2. No routine semantic evidence-selection call

The evidence registry already contains verified IDs, tags, keywords and career-family metadata. Evidence retrieval is now local and deterministic. A normal run does not spend a Codex call asking Codex which evidence to send to Codex.

### 3. Existing application packages are immutable in normal runs

A normal `prepare_applications()` run **never regenerates an existing application**, including packages marked `needs_ai_or_review`.

Only the explicit:

```python
repair_packages()
```

route can rebuild an existing package.

If the database contains an application record but its files were not copied into the new project folder, V1.9.0 reports the missing artifact and does not silently spend AI to recreate it.

### 4. Existing completed deep analyses are reused

Completed V1.8.x/V1.9 deep analyses are expensive assets. Normal runs reuse them instead of refreshing the historical database merely because the agent version changed.

Jobs with existing application packages are not deep-refreshed during normal search, even if a career page changes wording. The package remains preserved for human review.

### 5. AI is allocated using local practical priority

Before assigning a deep slot, the agent now considers:

- deterministic relevance
- local PRE fit
- practical priority
- career-family tier
- freshness
- user feedback
- whether an application already exists
- explicit language blockers

An explicit C1+/fluent-German vacancy is not given a scarce deep slot by default when verified German is B1. It remains visible in the dashboard. Marking the job **Interested/APPLY** or supplying it manually overrides this local AI-saving rule.

### 6. One AI call creates one new application package

For a qualifying **new** job, CV tailoring and cover-letter writing are combined into one structured `application_bundle` call.

That call returns:

- complete tailored CV LaTeX
- CV evidence IDs and claim trace
- cover-letter text
- cover-letter evidence IDs and claim trace
- supported recipient/reference metadata

The German/English cover-letter LaTeX templates are based on the user's preferred recent application format.

### 7. Routine AI semantic audit/repair loops are removed

Normal application generation no longer automatically spends additional Codex calls on semantic audit and repair.

Instead, V1.9.0 performs a deterministic local trace gate:

```text
claim -> cited evidence IDs -> verified evidence catalog
```

It distinguishes:

- supported trace
- missing trace
- trace mismatch

Controlled facts such as CATIA, ANSYS, OpenFAST, MATLAB, SAP, B1/C1, quantified percentages, etc. must be compatible with the cited evidence. Ambiguous packages are held for human review rather than triggering another hidden AI call.

### 8. Hard AI safety budgets

Default local limits are intentionally conservative:

```yaml
ai:
  budget:
    max_calls_per_run: 4
    max_estimated_input_tokens_per_run: 35000
    max_failed_calls_per_run: 1

    max_provider_calls_per_day: 4
    max_provider_calls_per_allowance_period: 12
    max_estimated_input_tokens_per_day: 35000
    max_estimated_input_tokens_per_allowance_period: 90000

    pause_below_remaining_percent: 10
```

Normal strategy:

```yaml
ai:
  strategy:
    max_new_deep_per_run: 2
    reserve_calls_for_new_packages: 2
    max_new_packages_per_run: 2
```

So a normal run can never intentionally become another 60-call run. At most it plans roughly:

```text
up to 2 new direct DEEP reviews
+ up to 2 NEW application bundles
= at most 4 provider attempts
```

The estimated-input ceiling can stop the run even earlier.

These are **local safety limits, not official OpenAI plan limits**.

### 9. Cross-project global usage ledger

Creating `job_search_agent_v1_9_1`, copying the project, or starting a different SQLite database must not reset the safety counter.

Provider attempts are written before execution to:

```text
~/.job_search_agent/codex_budget_ledger.jsonl
```

The ledger counts attempts, including failed calls. It is used across project copies for daily and allowance-period safety ceilings. If the ledger cannot be written, provider use fails closed by default.

### 10. Failure circuit breaker

The default is one failed provider attempt per run. Once a provider call fails, further calls are blocked for that run. This prevents repeated timeouts/errors from consuming allowance.

### 11. LOCAL_PREVIEW is genuinely zero-Codex

In `vscode_runner.py`:

```python
result = local_preview()
```

runs discovery, filtering and deterministic local ranking only.

No Codex calls. No CV generation. No cover letters. No desktop notifications.

The safety invariant is enforced by the pipeline itself, not merely by configuration.

CLI is safe by default too:

```powershell
python agent.py run
```

is a zero-Codex local preview. Provider work requires the explicit:

```powershell
python agent.py run --full
```

flag.

### 12. Recurring watch is safe by default

```python
watch()
```

now runs LOCAL_PREVIEW by default.

Recurring full application preparation is deliberately explicit:

```python
watch_prepare()
```

Even then, all hard per-run/daily/allowance-period budgets remain enforced.

### 13. HTTP politeness remains intact

The anti-hammering controls were not weakened:

```yaml
min_delay_per_host_seconds: 1.5
delay_jitter_seconds: 0.25
respect_robots_txt: true
```

V1.9.0 saves time by requesting fewer pages, not by hitting a host faster.

Detail enrichment is ranked/capped. Strong target titles receive priority; lower-ranked jobs can be saved as `discovered_unenriched` for later cycles instead of being discarded.

### 14. Application job count vs company-folder count is explicit

`output/application_index.json` reports:

- number of application jobs
- number of companies
- each package directory
- whether the package directory exists
- count of missing artifact folders

This prevents confusion such as “five applications but four company folders” when two vacancies belong to the same company.

### 15. Notifications are deduplicated

The database stores `(job, notification kind)` pairs. The same package-ready, queued, package-error, missing-artifact, or strong-local-candidate alert is not repeatedly emitted each cycle.

When Codex is locked, a very strong local candidate can still be surfaced once so AI budgeting does not make a time-sensitive vacancy invisible.

## Recommended upgrade from V1.8.3

Create a new folder such as:

```text
C:\Users\<USER>\Desktop\Job Agent\job_search_agent_v1_9_0
```

To preserve expensive work, copy from the previous project:

```text
output\job_agent.sqlite3
output\applications\        <- important: copy the application files too
```

Optional, if still useful within the cache lifetime:

```text
output\http_cache.json
```

Do **not** copy old `last_run_report.json`, dashboard, discovery report or other transient reports. V1.9.0 will rebuild them.

If you copy the database but forget `output\applications`, V1.9.0 will flag the missing package folders and will not regenerate them during an ordinary run.

## What to run right now with only low remaining usage

Use:

```python
result = local_preview()
```

or from PowerShell:

```powershell
python agent.py run
```

Both are zero-Codex.

Do **not** update the usage hint to bypass the lock merely to test the release.

## After the official reset

1. Check Codex's official Usage UI.
2. Update the usage hint with the actual remaining percentage and next reset date.
3. Run setup and confirm `Codex budget: OPEN`.
4. Use:

```python
result = prepare_applications()
```

A full run then performs:

```text
discovery
-> deterministic relevance/freshness/language/employment classification
-> local PRE + practical ranking
-> reuse cached completed deep matches
-> at most a few direct new DEEP calls
-> globally rank NEW package candidates
-> at most a few single-call application bundles
-> deterministic evidence-trace QA
-> LaTeX/PDF validation
-> deduplicated notification
-> human review/apply
```

## Explicit repair mode

Only when you deliberately want to rebuild old `needs_ai_or_review` packages:

```python
result = repair_packages()
```

Repair performs no discovery and no job matching. It is capped separately (`max_repair_packages_per_run: 2`) and still respects every AI budget/usage lock.

## Provider policy

Default:

```yaml
ai:
  provider: codex_cli
```

- Codex CLI is used only if available and budget-unlocked.
- `auto` means Codex first, otherwise heuristic.
- `auto` **never silently switches to a paid OpenAI API key**.
- `openai_api` must be selected explicitly and requires `OPENAI_API_KEY`.

## Useful files

```text
output/dashboard.html
output/daily_digest.html
output/discovery_report.json
output/search_plan.json
output/last_run_report.json
output/application_index.json
output/job_agent.sqlite3
```

The dashboard distinguishes local estimates from official provider usage. The official Codex Usage UI remains the authoritative allowance meter.

## Source coverage

Broad sources included by default:

- Bundesagentur fuer Arbeit public Jobsuche HTML
- Arbeitnow public API

Optional when configured:

- Adzuna
- Jooble
- Greenhouse watchlists
- Lever watchlists
- SmartRecruiters watchlists
- manual URLs
- `.eml` job alerts

## Safety invariants

- Never auto-submit applications.
- Never invent experience, skills, certifications, standards knowledge or language level.
- Never overwrite source CVs.
- Preserve sanitized/redacted identity fields.
- Never regenerate an existing package in normal search.
- Never make routine SCREEN or semantic evidence-selection calls.
- Never make provider calls in LOCAL_PREVIEW.
- Never exceed local AI call/input ceilings.
- Never bypass the official-usage hint lock automatically.
- Never disable per-host throttling for speed.
