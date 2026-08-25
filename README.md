# Job Search Agent V1.5

V1.5 turns the project from a job-finding/document generator into a more explicit **job-search decision system**.

It keeps the V1.4.2 parser fixes, bilingual multi-CV workflow, freshness rules, LaTeX compilation, local database, VS Code runner and continuous watch mode. The main changes are **verified evidence IDs, Fit vs Application Priority, feedback learning, tiered AI calls, safe Codex-first provider selection, usage telemetry, priority-based notifications and a stronger health check**.

## What V1.5 adds

### 1. Verified evidence registry

The factual CV boundary is now also represented in:

```text
input/evidence/evidence.json
```

It contains verified evidence objects such as:

```json
{
  "id": "EXP_CAE_002",
  "claim": "Performed modal and harmonic-response analyses in ANSYS...",
  "source": ["mechanical_en", "mechanical_de", "wind_en"],
  "verified": true
}
```

The agent retrieves only the evidence relevant to each vacancy instead of sending every CV in full to every AI call. Deep AI matching returns evidence IDs for important claims. Generated application folders also contain `evidence_sources.json` and `claim_trace.json`.

This makes it harder for the model to accidentally combine unrelated facts into a stronger unsupported claim.

### 2. Fit is not Priority

The dashboard now has two scores:

- **Fit**: how well your verified evidence satisfies the vacancy.
- **Priority**: how strongly you should consider applying after language requirements, freshness, career tier, mandatory gaps, location/employment compatibility and your own previous feedback.

Example:

```text
Fit:      90
Priority: 76 REVIEW

Reason:
- strong technical evidence
- fluent German requested, candidate is B1
```

A high technical fit therefore does not hide a practical risk.

### 3. Human feedback + learning

You can store:

```text
APPLY
SAVE
SKIP
APPLIED
INTERVIEW
REJECTED
OFFER
```

The agent records the decision in SQLite and writes:

```text
output/feedback_summary.json
```

After enough decisions in one career family, V1.5 can make a small bounded adjustment to **Priority**. It does not rewrite the underlying Fit score.

The adjustment is deliberately capped in `config.yaml`.

### 4. Interactive local dashboard

The normal static dashboard still works:

```text
output/dashboard.html
```

For working feedback buttons, start the local dashboard server:

```powershell
python agent.py serve
```

It opens:

```text
http://127.0.0.1:8765/
```

The dashboard has **Apply / Save / Skip** buttons.

You can also record feedback from the command line:

```powershell
python agent.py feedback "6328" SAVE --reason "Strong fit, German is a stretch"
```

or using an exact job URL:

```powershell
python agent.py feedback "https://example.com/job" APPLY
```

In VS Code you can use:

```python
save_feedback("6328", "SAVE", "Strong fit; language risk")
```

### 5. Tiered AI usage

V1.5 no longer treats every discovered vacancy as equally worthy of a full AI call.

Default flow:

```text
many discovered jobs
        ↓
hard filters + parser verification
        ↓
local heuristic PRE score
        ↓
compact AI SCREEN (only promising jobs)
        ↓
deep AI match (smaller shortlist)
        ↓
CV + cover letter (priority threshold only)
```

Default limits per run:

```yaml
ai:
  tiered:
    screen_min_pre_score: 40
    max_screen_per_run: 24
    deep_min_screen_score: 58
    deep_force_pre_score: 72
    max_deep_per_run: 10
    screen_evidence_limit: 8
    deep_evidence_limit: 16
```

Manual URLs are screened even if their local pre-score is low, because an explicitly supplied vacancy deserves evaluation.

### 6. Codex is explicit by default

V1.5 defaults to:

```yaml
ai:
  provider: codex_cli
```

If Codex is unavailable, it falls back to local heuristic ranking.

**It will not silently spend OpenAI API credits merely because an `OPENAI_API_KEY` exists.**

To intentionally use API billing, change:

```yaml
ai:
  provider: openai_api
```

`auto` is also safe in V1.5: it prefers Codex and otherwise uses heuristic mode; it does not silently select the paid API.

### 7. AI usage telemetry

Every AI call records:

- provider
- model
- operation (`job_screen`, `job_deep_match`, `cv_tailoring`, etc.)
- approximate/actual input and output tokens
- duration
- success/failure
- estimated API cost when you explicitly configure current pricing

The dashboard shows today's call/token totals.

For Codex/ChatGPT-plan usage, token counts are estimates based on text size and are **not billing data**.

For OpenAI API cost tracking, enter current pricing yourself in `config.yaml`:

```yaml
telemetry:
  openai_input_cost_per_million: null
  openai_output_cost_per_million: null
```

The project intentionally does not hard-code potentially outdated prices.

### 8. Priority-based notifications

A ready package no longer automatically means a desktop notification.

Default:

```yaml
notifications:
  immediate_priority_min: 82
  digest_priority_min: 68
```

- High priority: immediate notification when a new ready package is generated.
- Review priority: shown in dashboard/digest without notification spam.
- Low priority: dashboard only.

The digest is generated at:

```text
output/daily_digest.html
```

You can regenerate it with:

```powershell
python agent.py digest
```

## Installation with your Conda environment

You already use the Conda environment `agent`.

```powershell
conda activate agent
cd C:\path\to\job_search_agent_v1_5
pip install -r requirements.txt
```

Then:

```powershell
python agent.py doctor
```

For an optional network check:

```powershell
python agent.py doctor --network
```

## Codex check

The desired output is:

```text
AI provider requested: codex_cli
AI backend active: codex_cli
```

Test Codex in the same VS Code/Conda context:

```powershell
codex --version
codex exec "Reply only with CODEX_WORKS"
```

If VS Code cannot find it, set an explicit path in `config.yaml`, for example:

```yaml
ai:
  codex_path: "C:/Users/YOUR_USER/AppData/Roaming/npm/codex.cmd"
```

## VS Code / Shift+Enter

Open:

```text
vscode_runner.py
```

Use the cells for:

- setup check
- search-query preview
- dry run
- real run
- interactive dashboard
- feedback
- continuous watch

Test without documents:

```python
result = run_once(dry_run=True)
```

Generate real packages:

```python
result = run_once(dry_run=False)
```

Continuous monitoring:

```python
watch(interval_minutes=30, dry_run=False)
```

## Search strategy

V1.5 keeps the broad-search principle:

```text
SEARCH BROADLY
      ↓
EVALUATE STRICTLY
      ↓
WRITE TRUTHFULLY
```

It searches Core, Adjacent and selected Stretch career families rather than only literal Mechanical/Wind job titles.

The five sanitized CV sources remain:

```text
input/cvs/mechanical_en_master.tex
input/cvs/mechanical_de_master.tex
input/cvs/wind_en_master.tex
input/cvs/wind_de_master.tex
input/cvs/wind_thesis_en_master.tex
```

The base CV is a layout/emphasis choice. The evidence registry is the cross-CV factual bridge.

## German jobs

German vacancies can produce German CVs and cover letters. German proficiency must remain truthfully B1/actively learning.

Strong German requirements are recorded as risk/priority factors rather than automatically deleting technically relevant jobs.

## Full-time jobs

Full-time professional jobs remain a primary target alongside:

- fixed-term
- part-time
- working student
- internship
- Master's thesis

The agent must not leave thesis-only targeting language in a full-time application.

## Package folders

A generated package looks like:

```text
output/applications/2026-08-13/company/role/
├── job.json
├── job_description.txt
├── match.json
├── evidence_sources.json
├── claim_trace.json
├── CV_company_role_EN.tex
├── CV_company_role_EN.pdf
├── CoverLetter_company_role_EN.txt
├── CoverLetter_company_role_EN.tex
├── CoverLetter_company_role_EN.pdf
└── package_status.json
```

## Safety rules

V1.5 keeps the existing guardrails:

- never invent skills or experience
- never upgrade language proficiency
- never overwrite source CVs
- preserve sanitized identity placeholders
- do not auto-submit applications
- keep human review before application submission

## Migrating from V1.4.2

The safest route is to use the new V1.5 folder and copy only your local data you intentionally want to preserve:

```text
.env
input/manual_jobs.txt
input/assets/
```

If you want to keep old application history and feedback, you may also copy:

```text
output/job_agent.sqlite3
```

V1.5 performs lightweight SQLite schema migration automatically.

Because V1.5 changes scoring semantics from one score to **Fit + Priority**, a clean test database is still recommended while validating the new behavior.

## Useful commands

```powershell
python agent.py doctor
python agent.py run --dry-run
python agent.py run
python agent.py dashboard
python agent.py digest
python agent.py serve
python agent.py feedback "6328" APPLY
python agent.py repair-db
```

## Testing

Run:

```powershell
python -m unittest discover -s tests -p "test*.py" -v
```

The release validation for this package is documented in `VALIDATION_REPORT.md`.
