# Job Search Agent V1.6

V1.6 keeps the V1.5 decision-system architecture and adds the reliability/safety upgrades identified in the latest review: polite page fetching, stronger dashboard input validation, semantic evidence retrieval, and a final semantic claim-vs-evidence audit before an application package can be marked READY.

The design principle remains:

```text
SEARCH BROADLY
      ↓
EVALUATE STRICTLY
      ↓
WRITE TRUTHFULLY
```

## What V1.6 changes

### 1. Polite live-page checking

Generic career-page verification now uses one shared HTTP policy per run:

```yaml
http:
  min_delay_per_host_seconds: 1.5
  delay_jitter_seconds: 0.25
  max_retries: 2
  retry_backoff_seconds: 2.0
  max_retry_after_seconds: 60
  page_cache_minutes: 120
  cache_file: output/http_cache.json
  respect_robots_txt: true
  robots_fail_open: true
  robots_cache_hours: 12
```

This means multiple jobs on the same company site are not fetched back-to-back with no delay. HTTP 429/5xx responses use bounded retry/backoff, `Retry-After` is respected, and recently checked pages can be reused from the local cache.

`robots.txt` is checked and cached for arbitrary page fetching. An explicit disallow becomes `robots_disallowed`, not `expired`.

### 2. Safer local dashboard feedback endpoint

`python agent.py serve` still binds only to:

```text
http://127.0.0.1:8765/
```

V1.6 additionally uses a random session token for feedback writes and validates:

- `Content-Type: application/json`
- body size (max 8 KiB)
- 24-character job fingerprint
- allowed decision values
- reason type/length
- that the target job actually exists

The browser dashboard automatically sends the token. You do not need to manage it.

### 3. HTTP/HTTPS-only job links

Vacancy URLs must use `http://` or `https://`.

Schemes such as:

```text
javascript:
file:
data:
ftp:
```

are rejected at ingestion or rendered as non-clickable text if corrupted legacy data somehow reaches the dashboard.

### 4. Hybrid evidence retrieval

V1.5 used lexical/token overlap to retrieve evidence. V1.6 keeps that cheap first pass, then—only for jobs promoted to deep AI analysis—asks Codex/API for a semantic second pass across the verified evidence registry.

```text
Job
 ↓
lexical evidence retrieval (Python)
 ↓
AI semantic evidence selection (deep candidates only)
 ↓
verified evidence subset
 ↓
deep fit analysis
```

This helps with differently worded requirements such as `eigen-behaviour / oscillatory response` versus evidence tagged `modal / harmonic / vibration / resonance`.

### 5. Semantic claim-vs-evidence audit

A real evidence ID is no longer enough by itself.

Example:

```text
Evidence:
"Supported manufacturing and assembly..."

Generated claim:
"Led manufacturing and assembly..."
```

V1.6 performs a final AI entailment audit and should flag the stronger verb as unsupported/overstated.

Each generated package now contains:

```text
cv_evidence_trace.json
cover_letter_evidence.json
semantic_evidence_audit.json
```

By default:

```yaml
evidence:
  require_traceability_for_ready: true
  semantic_selection:
    enabled: true
  semantic_audit:
    enabled: true
    required_for_ready: true
```

A package cannot become `package_ready` if the semantic audit fails, if the audit itself fails, or if the CV/cover letter lacks a material claim trace.

### 6. Career-family and German heuristics remain cheap—but AI can correct context

Python still performs fast first-pass detection for:

- career family
- job language
- employment type
- German requirement

Deep AI analysis now additionally stores:

```text
AI career-family second opinion
secondary family
confidence
contextual German importance
contextual German mandatory/unclear flag
contextual German reason
```

The dashboard shows these under **analysis**. Contextual German importance affects Priority only softly; it does not invent an explicit B2/C1 requirement that the posting never stated.

## Fit vs Priority

V1.6 keeps the V1.5 distinction:

- **Fit** = how well verified evidence satisfies the vacancy.
- **Priority** = how strongly the opportunity deserves attention after language, mandatory gaps, career tier, freshness, employment fit and feedback.

A job can therefore be:

```text
Fit:      90
Priority: 75 REVIEW
```

if technical fit is excellent but fluent German is a serious practical risk.

## AI pipeline

AI is deliberately not used for every task.

```text
Sources
 ↓
Python parsing / dedupe / freshness / active check
 ↓
Python PRE score
 ↓
compact AI SCREEN for promising jobs
 ↓
semantic evidence selection for promoted jobs
 ↓
deep AI FIT analysis
 ↓
Python Priority rules
 ↓
CV + cover letter for worthwhile jobs
 ↓
semantic claim/evidence audit
 ↓
LaTeX/PDF + dashboard + notification
```

Default AI provider remains:

```yaml
ai:
  provider: codex_cli
```

Having an `OPENAI_API_KEY` does **not** silently switch the agent to paid API usage. To intentionally use API billing, set `provider: openai_api`.

## Installation / first run

Use your existing Conda environment:

```powershell
conda activate agent
cd C:\Users\YOUR_USER\Desktop\job_search_agent_v1_6
pip install -r requirements.txt
python agent.py doctor
```

For a network check:

```powershell
python agent.py doctor --network
```

The doctor now also checks the configured host throttling, robots policy, page cache and semantic evidence/audit settings.

## Codex check

In the same VS Code terminal:

```powershell
codex --version
codex exec "Reply only with CODEX_WORKS"
```

Then run the **CHECK SETUP** cell in `vscode_runner.py`.

You want:

```text
Requested AI provider: codex_cli
Active AI backend: codex_cli
```

If Codex is not found, set an explicit Windows path in `config.yaml`, for example:

```yaml
ai:
  provider: codex_cli
  codex_path: "C:/Users/YOUR_USER/AppData/Roaming/npm/codex.cmd"
```

## VS Code / Shift+Enter workflow

Open:

```text
vscode_runner.py
```

Then use:

```python
# test search/matching only
result = run_once(dry_run=True)

# generate eligible application packages
result = run_once(dry_run=False)

# continuous mode
watch(interval_minutes=30, dry_run=False)
```

For feedback buttons:

```python
serve_dashboard(DB_FILE, port=8765, open_browser=True)
```

or from PowerShell:

```powershell
python agent.py serve
```

## Package contents

A generated application folder can include:

```text
job.json
job_description.txt
match.json
evidence_sources.json
evidence_retrieved.json
cv_evidence_trace.json
cover_letter_evidence.json
semantic_evidence_audit.json
CV_<company>_<role>_<lang>.tex
CV_<company>_<role>_<lang>.pdf
CoverLetter_<company>_<role>_<lang>.txt
CoverLetter_<company>_<role>_<lang>.tex
CoverLetter_<company>_<role>_<lang>.pdf
package_status.json
```

If `semantic_evidence_audit_ok` is false, the package is kept for review but is not marked READY.

## Feedback / learning

The interactive dashboard and command line support:

```text
APPLY
SAVE
SKIP
APPLIED
INTERVIEW
REJECTED
OFFER
```

Example:

```powershell
python agent.py feedback "6328" SAVE --reason "Strong technical fit; German is a stretch"
```

Feedback can make a small bounded adjustment to future **Priority** in the same career family. It does not change the underlying Fit score.

## Migration from V1.5.1

The safest setup is a new V1.6 folder. Copy only local data you want to keep, for example:

```text
.env
input/manual_jobs.txt
input/assets/
```

You may copy `output/job_agent.sqlite3` if you want to preserve application history and feedback.

Important: V1.6 gives cached V1.5 AI matches a fresh analysis because V1.6 adds semantic evidence selection/context fields. Existing ready packages that do not contain a passing V1.6 semantic evidence audit are eligible for regeneration/review rather than being blindly trusted as ready.

## Safety rules

- Never invent skills, responsibilities, employers, dates or results.
- Never upgrade German above the real level.
- Never combine separate evidence into an unsupported stronger claim.
- Never overwrite source CVs.
- Preserve sanitized identity/contact placeholders.
- Never auto-submit applications.
- Human review remains required before submission.

For the first 5–10 generated packages, compare the wording closely with the master CV/evidence registry even with the new semantic audit. No automated check should be treated as a substitute for initial spot-checking.

## Useful commands

```powershell
python agent.py doctor
python agent.py doctor --network
python agent.py run --dry-run
python agent.py run
python agent.py dashboard
python agent.py digest
python agent.py serve
python agent.py feedback "6328" APPLY
python agent.py repair-db
```

## Testing

```powershell
python -m unittest discover -s tests -p "test*.py" -v
```

Release validation is documented in `VALIDATION_REPORT.md` and changes are summarized in `CHANGELOG_V1_6.md`.
