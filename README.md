# Job Search Agent V1.8.2

V1.8.2 is the **execution-clarity / AI-budget allocation** correction release. It preserves the V1.8 relevance gate, V1.8.1 freshness policy, evidence traceability, robots checking, page caching and the polite **1.5 s + jitter per-host request throttle**.

## V1.8.2 — what changed

- Makes the two run modes explicit:
  - `MATCH_ONLY` (`dry_run=True`) searches and evaluates jobs but **never writes CV/cover-letter packages and never sends desktop notifications**.
  - `FULL_APPLICATION_PREP` (`dry_run=False`) searches/evaluates and then generates eligible CV + cover-letter packages; it still **never auto-submits applications**.
- A match-only run now reports `packages_would_generate` plus the actual candidate titles that would receive documents in full mode.
- Adds convenient VS Code helpers: `match_only()` and `prepare_applications()` so a boolean flag is no longer the main user interface.
- Changes scarce deep-AI allocation from "first promoted jobs consume the budget" to **screen everyone first, globally rank promoted jobs, then spend the deep budget on the strongest candidates**.
- PRE/SCREEN-only rows can no longer become final `HIGH/APPLY`; they are capped at `REVIEW` until a deep AI assessment is completed.
- Screen-promoted jobs that miss the deep budget are marked `deep_pending` and compete for a deep slot on the next run **without paying for the same screen again**.
- Keeps semantic evidence selection for deep matches, but now makes the operation mix transparent in `last_run_report.json`.
- Clarifies telemetry: Codex token counts are **local text-length estimates**, not official ChatGPT/Codex account usage or billing data.
- Adds per-stage runtime telemetry and HTTP telemetry (page fetches, cache hits, network requests, robots requests, retries, errors, and throttle sleep time).
- Keeps the anti-hammering per-host request throttle. V1.8.2 saves some requests safely by applying the domain gate to source-supplied full descriptions before fetching the public detail page.
- Extends page cache lifetime from 2 h to 6 h so frequent watch cycles do not refetch unchanged pages unnecessarily.
- Finishes Bundesagentur title cleanup after employer enrichment, removing duplicated trailing `bei <company>` text.
- Locally rejects obvious `Customer Support Engineer` SaaS/support roles and commercial `Tender/Bid/Proposal Manager` roles before Codex.
- Makes high-priority notifications useful even when a generated package fails the READY audit: the notification says the package needs review rather than silently doing nothing.
- Hardens LaTeX/PDF compiler subprocess decoding with UTF-8 + replacement handling, including German CVs.

### Which mode should I use?

For a diagnostic comparison only:

```python
result = match_only()
```

This can still use Codex for job matching, but intentionally creates **no application files**.

For the original agent workflow — search, evaluate, generate documents and notify you:

```python
result = prepare_applications()
```

Eligible packages are written below:

```text
output/applications/YYYY-MM-DD/<company>/<role>/
```

A generated package can contain both `.tex` and `.pdf` CV/cover-letter files plus evidence traces and the semantic audit. Applications remain human-controlled and are never submitted automatically.

See `CHANGELOG_V1_8_2.md` for the complete correction list.

## V1.8.1 — corrections after real-output review

- Replaces the 7-day hard cutoff with staged freshness: 0-14 days fully eligible, 15-30 days live-checked, 31-45 days only for strong target titles with confirmed live status.
- Gives fresher vacancies priority within the same relevance tier before scarce Codex screening/deep slots are allocated.
- Normalizes Germany locations (`DE`, `Germany`, `Deutschland`, and city-only Germany results) so Priority no longer gets a false out-of-area penalty.
- Cleans Bundesagentur result labels such as `4: Mechanical Engineer ... bei Company` into a canonical title plus separate company field.
- Shows explicit vs contextual German importance more clearly in the dashboard.
- Adds local `SOFTWARE_PRODUCT_DESIGN` rejection for frontend/digital product-design roles that have no physical-engineering bridge.
- Writes `output/last_run_report.json` and displays AI calls/tokens **for this run** separately from daily usage.
- Keeps full `why rejected` analysis for AI-evaluated jobs in the audit section.

See `CHANGELOG_V1_8_1.md` for details.

## V1.8 — relevance gate

V1.8 is the **relevance-gate** release. It keeps V1.7.1 automatic discovery and all V1.6 safety/evidence safeguards, but fixes the major problem exposed by the 223-job dashboard: broad sources were finding plenty of vacancies while generic words such as `engineer`, `development`, `project`, `Python` and `automation` allowed obviously unrelated software/business jobs to survive too far into the pipeline.

The design principle is now enforced in code:

```text
SEARCH BROADLY
      ↓
REJECT OBVIOUS WRONG-DOMAIN TITLES CHEAPLY
      ↓
EVALUATE RELEVANT / AMBIGUOUS ENGINEERING JOBS STRICTLY
      ↓
WRITE TRUTHFULLY
```

## V1.8 — relevance gate and AI-budget protection

### 1. Title-domain gate before page fetching

Automatic jobs are screened by title **before** the agent downloads the detailed vacancy page. Pure backend/frontend/full-stack/DevOps/cloud/data-platform/software roles, sales/marketing, finance/HR/admin and design/media roles are rejected when no defensible engineering bridge exists.

Examples:

```text
Software Engineer, Backend Focused        -> HARD REJECT / PURE_SOFTWARE_BACKEND
Data Platform Engineer                    -> HARD REJECT / PURE_SOFTWARE_BACKEND
Account Executive                         -> HARD REJECT / BUSINESS_SALES_MARKETING
Finance Manager Renewable Energy          -> HARD REJECT / FINANCE_HR_ADMIN

Software Engineer - Simulation            -> KEEP (simulation bridge)
Control Software Engineer - Wind Turbines -> KEEP (control + wind bridge)
Robotics CAE Engineer                      -> KEEP
Mechanical Engineer                       -> KEEP
Berechnungsingenieur                      -> KEEP
```

Manual URLs bypass this automatic title rejection because an explicit URL from you means “review this job”, even if it is unusual.

### 2. Domain signal required after enrichment

Ambiguous titles such as `Systems Engineer`, `Project Engineer`, `Research Engineer`, `Quality Engineer` or `Development Engineer` are not accepted just because they contain `Engineer`. Their detailed vacancy text must contain a real bridge to mechanical engineering, CAE/FEA, structural dynamics, wind, simulation, manufacturing, controls/mechatronics, validation, PLM/engineering data, or a configured adjacent family.

### 3. PRE score is now domain-anchored

Generic words no longer earn meaningful fit points by themselves. The local score is driven by:

```text
strong/bridged target title
+ mechanical/CAE/wind/simulation domain evidence
+ specific verified profile/evidence hits
+ career-family signal
```

A pure backend software role now receives PRE `0` and is filtered before AI. Typical mechanical/structural/simulation target titles start high enough to reach AI screening when their vacancy text supports the match.

### 4. Relevant jobs consume AI budget first

V1.8 sorts candidates by a cheap **relevance rank before PRE score**. Limited Codex screen/deep-analysis slots therefore go to obvious CAE/mechanical/wind/simulation candidates before generic adjacent jobs.

### 5. Arbeitnow matching no longer treats `engineer` as a domain

V1.7 could match the query `mechanical engineer` against `Software Engineer, Backend Focused` because the word `engineer` appeared in both. V1.8 ignores generic query tokens and requires the domain-bearing token (`mechanical`, `simulation`, `wind`, etc.) to match.

### 6. Professional jobs are no longer accidentally filtered

V1.7 could mark a legitimate professional job as ineligible when the ATS did not explicitly expose `Full time` even though professional full-time roles are a primary target. `professional` is now an allowed employment state and also maps safely to the enabled full-time policy.

### 7. Tighter search plan

The default anchors are now deliberately domain-specific, for example:

```text
mechanical design engineer
CAE engineer mechanical
FEA engineer mechanical
structural analysis engineer
mechanical simulation engineer
validation engineer mechanical
Berechnungsingenieur Maschinenbau
Berechnungsingenieur FEM
Simulationsingenieur Maschinenbau
Werkstudent CAE
Masterarbeit Windenergie Simulation
```

AI-generated search-query expansion is disabled by default. The curated career map still rotates adjacent/stretch queries, but Codex is reserved for actual job reasoning rather than inventing search strings.

### 8. Dashboard shows attention-worthy jobs first

The normal table contains only `HIGH`, `REVIEW` and `LOW/POSSIBLE` jobs at or above the configured priority floor. Hard-filtered jobs and `REJECT` rows stay auditable inside a collapsed **Rejected / filtered audit** section.

This means an irrelevant backend job can remain in SQLite for transparency without occupying your normal job-review list.

### Recommended migration from V1.7.x

Use V1.8.2 in a **new folder with a fresh `output/` database** for the cleanest first comparison. V1.8.2 will also clear stale scores when a rediscovered job becomes hard-filtered, so an old `PRE 46` backend row cannot remain actionable. Copy your personal local inputs/settings only if needed.

## Historical: V1.7.1 — automatic job discovery

V1.7.1 no longer treats a list of planned queries as proof that jobs were actually searched. Two broad sources are enabled by default:

```text
Bundesagentur für Arbeit Jobsuche  -> public Germany-wide search pages
Arbeitnow                         -> public no-key Europe/DACH job API
```

Optional sources remain available:

```text
Adzuna             broad search, requires ADZUNA_APP_ID + ADZUNA_APP_KEY
Jooble             broad search, requires JOOBLE_API_KEY
Greenhouse         company watchlist; configure board tokens
Lever              company watchlist; configure site names
SmartRecruiters    company watchlist; configure company identifiers
Email alerts       ingest .eml alerts from LinkedIn/Indeed/XING/StepStone/etc.
Manual URLs         explicit jobs you want reviewed
```

The Bundesagentur connector uses a conservative query budget, delays requests to the same host, dynamically checks `robots.txt`, and only follows fresh search results into the expensive live-page/enrichment stage. Arbeitnow downloads a few catalogue pages once per run and matches all selected career queries locally rather than making one API request per query.

### Source transparency

Run:

```powershell
python agent.py sources

# optional: actually perform one lightweight live test per broad source
python agent.py sources --test
```

You should see something similar to:

```text
OK  arbeitsagentur    broad      public Jobsuche HTML; max 14 queries/run
OK  arbeitnow         broad      public API, no key; 3 page(s) per run
--- adzuna            broad      ADZUNA_APP_ID / ADZUNA_APP_KEY missing
--- jooble            broad      JOOBLE_API_KEY missing
--- greenhouse        watchlist  enabled but no boards configured
--- lever             watchlist  enabled but no sites configured
--- smartrecruiters   watchlist  enabled but no companies configured
OK  manual            manual     ... manual URL(s)
OK  email_alert       inbox      ... .eml alert file(s)

Automatic broad discovery: CONFIGURED
```

After every run, V1.7.1 writes:

```text
output/discovery_report.json
```

The dashboard also shows **Auto discovery: ACTIVE/OFF**, raw discovered count, and an expandable source-health section. If no broad source successfully completes, the run emits an explicit `AUTOMATIC JOB SEARCH IS NOT ACTIVE` warning instead of silently showing only manual URLs.

### Search coverage and rate control

V1.7.1 keeps the 32-query career plan, but network sources can use a smaller per-source budget. Core anchor queries are retained and the remaining queries rotate between runs. This avoids sending all 32 searches to every provider every 30 minutes.

The default BA configuration is:

```yaml
sources:
  arbeitsagentur:
    enabled: true
    max_queries_per_run: 14
    anchor_queries_per_run: 8
    results_per_query: 8
    min_delay_seconds: 1.5
    respect_robots_txt: true

  arbeitnow:
    enabled: true
    pages: 3
    max_results_per_run: 120
```

The search anchors now also include working-student/internship/thesis queries so discovery is not limited to professional full-time roles.

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
cd C:\Users\YOUR_USER\Desktop\job_search_agent_v1_7
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
# diagnostic search/matching only — no application files
result = match_only()

# original workflow: generate eligible CV/cover-letter packages + notifications
result = prepare_applications()

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

The safest setup is a new version folder. Copy only local data you want to keep, for example:

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
