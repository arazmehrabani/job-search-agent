# Safe Start - V1.9.0 on Windows / VS Code

V1.9.0 ships with Codex intentionally locked because the last reported official Usage UI showed only low remaining usage until 2026-09-13. Do not change the hint merely to test the release.

## 1. Extract to a new folder

Example:

```text
C:\Users\<USER>\Desktop\Job Agent\job_search_agent_v1_9_0
```

## 2. Preserve expensive previous work

From the previous working agent folder, copy:

```text
output\job_agent.sqlite3
output\applications\
```

Copying **both** matters. The database contains package records; the `applications` directory contains the actual CV/cover-letter artifacts.

Optional:

```text
output\http_cache.json
```

Do not copy old `dashboard.html`, `last_run_report.json`, `discovery_report.json`, or other transient reports.

## 3. Activate the existing environment

```powershell
conda activate agent
```

Use the same Python interpreter already used for the project.

## 4. Open/run `vscode_runner.py`

The setup cells should report V1.9.0 and, with the shipped usage hint, something similar to:

```text
Codex budget: LOCKED
Official usage hint: low remaining usage
```

That lock is intentional.

## 5. Safe test now - zero Codex

Run:

```python
result = local_preview()
```

or:

```powershell
python agent.py run
```

Expected behavior:

- discovery works
- relevance/freshness/language/employment filtering works
- local ranking works
- existing deep analyses are reused for display
- no Codex provider subprocess is started
- no new CV or cover letter is generated
- no application is submitted

Check `output/last_run_report.json`. Provider attempts for the preview must be zero.

## 6. Do not run provider work at 3%

Do not use these until the official allowance resets and the real Usage UI has been checked:

```python
prepare_applications()
repair_packages()
watch_prepare()
```

The shipped budget guard should block them anyway, but preserving the lock is deliberate.

## 7. After the official reset

First check Codex's real Usage UI. Then update the hint to the actual remaining percentage and the next reset date, for example:

```python
set_codex_usage_hint(100, "2026-10-13")
```

Use the real value shown by the UI, not an assumed value.

Re-run setup. Only proceed when the budget status is `OPEN`.

Then a full cycle is explicit:

```python
result = prepare_applications()
```

Default safety planning permits at most 4 provider attempts in the entire run and normally reserves them for up to 2 unresolved direct DEEP evaluations plus up to 2 NEW application bundles. Existing applications are preserved and are not regenerated.

## 8. Repair is explicit

If an old `needs_ai_or_review` package truly needs to be regenerated after allowance is available:

```python
result = repair_packages()
```

This is the only normal route that is allowed to regenerate an existing application package. It is capped separately and does no job discovery or job matching.

## Permanent invariants

- Applications are never auto-submitted.
- Existing packages are not silently regenerated in ordinary search.
- LOCAL_PREVIEW never calls Codex.
- No routine SCREEN/evidence-selection/semantic-audit AI pipeline exists.
- Per-host request throttling remains enabled.
- Provider attempts are guarded by per-run, daily and cross-project allowance-period ceilings.
- A failed provider attempt counts against the safety budget.
