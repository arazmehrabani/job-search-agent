# Job Search Agent V1.4 — Robust Job Parsing + Multi-CV Bilingual Applications

V1.4 fixes the parsing and classification problems exposed by real Ashby and TÜV SÜD manual URLs while keeping the broad career-search and multi-CV evidence architecture from V1.3.

## Critical fixes in V1.4

- **Platform-aware enrichment:** JSON-LD first, plus dedicated handling for Ashby and SAP SuccessFactors-style pages such as TÜV SÜD.
- **Company/location extraction:** structured vacancy fields are preferred over generic browser metadata.
- **Stable deduplication:** tracking parameters are removed; Ashby `/application` and vacancy overview URLs resolve to the same canonical job; database migration also recognizes a previously stored copy of the same URL.
- **No ghost rows:** a manual page that cannot yield both a meaningful title and company is reported as a parse failure and is not inserted as `Unknown job / Unknown company`.
- **Employment dimensions:** career stage, schedule and contract are tracked separately. A role can therefore be `working_student + part_time + fixed_term`.
- **Internship bug fixed:** the word `intern` is matched on word boundaries, so `international projects` can no longer make a full-time engineering role look like an internship.
- **German requirement fixes:** phrases such as `fluent in German` are recognized; `German is advantageous` is stored as `preferred`, not mandatory.
- **Improved language detection:** German vacancy titles receive strong weight so an English-language ATS shell does not incorrectly relabel a German role as English.
- **Richer dashboard:** separate employment dimensions plus technical/experience/language/education fit fields when the AI backend returns them.
- **Legacy cleanup:** `python agent.py repair-db` removes V1.3 ghost parser rows that have no application package.

### Migrating from V1.3

The safest approach is to use the new V1.4 folder and copy only your `.env`, `input/manual_jobs.txt`, assets/photo, and any local configuration changes you intentionally made. If you instead reuse the old `output/job_agent.sqlite3`, run:

```powershell
python agent.py repair-db
```

Then run a new real or dry cycle so the three URLs are re-enriched with V1.4.

---

## What changed in V1.4

The agent now has five factual CV sources:

- `input/cvs/mechanical_en_master.tex`
- `input/cvs/mechanical_de_master.tex`
- `input/cvs/wind_en_master.tex`
- `input/cvs/wind_de_master.tex`
- `input/cvs/wind_thesis_en_master.tex` — compact Fraunhofer/thesis source

The four new CVs are **sanitized copies**. Their engineering content is retained, while personal identity/contact data is represented only by placeholders. See `PERSONAL_FIELDS.md`.

### Important architecture change: base CV != evidence boundary

For every vacancy the agent:

1. detects the job language;
2. detects employment type;
3. classifies a broad career family;
4. chooses the best **base CV** for layout/emphasis;
5. gives the AI an **evidence library containing all configured CVs**;
6. allows the AI to pull a relevant verified fact from another source CV;
7. forbids invention or strengthening of unsupported claims;
8. produces the CV and cover letter in the vacancy language;
9. compiles LaTeX to PDF;
10. saves the job in its own folder and notifies only for new ready packages.

Example:

```text
German Berechnungsingenieur FEM vacancy
        ↓
job language: DE
career family: CAE / structural dynamics
        ↓
base CV: mechanical_de_master.tex
        ↓
evidence available from:
  mechanical EN + DE
  wind EN + DE
  Fraunhofer wind/thesis
        ↓
German job-specific CV + German cover letter
```

A German wind-load role instead normally starts from `wind_de_master.tex`.
An English mechanical/product-development role normally starts from `mechanical_en_master.tex`.
An English wind thesis can use the compact `wind_thesis_en_master.tex` specialist source.

## Career search is deliberately broader than Mechanical/Wind titles

The static career map in `input/career_scope.yaml` searches three tiers.

### Core

- Wind-turbine loads / structures / simulation
- CAE / FEA / FEM / structural mechanics / structural dynamics
- Mechanical design / product development / machinery
- Renewable-energy engineering and project roles

### Adjacent

- Simulation / computational engineering / engineering automation
- Manufacturing / production / industrialization / project engineering
- CAE application engineering / technical consulting
- Wind-farm planning / site assessment / renewable-energy analysis
- Test / validation / verification engineering

### Stretch — discover, then evaluate carefully

- Controls / robotics / mechatronics
- Systems / research / interdisciplinary engineering
- Reliability / vibration / mechanical-integrity / condition-oriented roles

A stretch search is **not** a claim that the candidate already has all required experience. It only gives the matching layer a chance to identify a defensible bridge.

## Evidence currently available to the agent

The profile and CV evidence include, among other things:

- nearly six years of industrial mechanical/development experience;
- ANSYS static structural, modal and harmonic-response analysis;
- structural dynamics, vibration and resonance work;
- machinery development: crushers, conveyors, high-frequency vibrating screens and washing systems;
- mechanical/CAD work in CATIA V5, SOLIDWORKS and Siemens NX;
- manufacturing drawings, BOMs, component specifications and SAP-based engineering data;
- solar tracking and an automated electric-motor-driven panel-cleaning mechanism;
- manufacturing/assembly/on-site installation support;
- approximately 10% production scrap/raw-material-waste improvement evidence;
- current M.Sc. Wind Energy Engineering, grade average 1.9, expected February 2027;
- current rotor-as-sensor / wind-inflow-estimation Master's thesis;
- OpenFAST aeroelastic simulations and IEC 61400-1 load-case work;
- Python/MATLAB simulation automation, batch execution, signal/data processing and visualization;
- windPRO/QGIS wind-farm planning, energy-yield, noise, shadow-flicker and bat-curtailment assessment;
- M.Sc. Mechanical Engineering focus in control systems and robotics;
- MATLAB/Simulink underwater-welding-robot motion-control thesis;
- additive-manufacturing / 3D-printed hand-prosthesis project;
- Power BI, Excel and MS Project exposure;
- English C1 / IELTS 7.0;
- German B1 and actively learning.

## German-language jobs

German vacancies are intentionally included.

Policy:

```text
German job
   ↓
German CV
   +
German cover letter
```

The agent must always state German ability truthfully as B1 / actively learning.

If a role explicitly asks for B2/C1/fluent/native German, V1.4 records that as a **risk/gap** rather than automatically deleting the vacancy. This lets strong engineering matches remain visible while keeping the language mismatch honest.

The dashboard has a `German req.` column for this signal.

## Full-time positions

Full-time jobs are explicitly allowed and are a primary target.

The agent must not leave phrases such as:

```text
Seeking a Master's thesis...
```

inside a CV prepared for a full-time role.

For a full-time application, current Wind Energy M.Sc. status can remain in Education / relevant projects without framing the candidate as only seeking student work.

## Personal data

The working CVs use:

```text
REPLACENAME
REPLACELOCATION
REPLACEPHONE
REPLACEEMAIL
REPLACELINKEDIN
REPLACEPORTFOLIO
REPLACEPROJECTLINK
candidate_photo.jpeg
```

The AI cannot alter those fields. Your separate program can replace them later.

## Running in VS Code with your Conda environment `agent`

Open the whole project folder in VS Code.

Select your interpreter:

```text
Ctrl+Shift+P
Python: Select Interpreter
agent
```

Install dependencies once:

```powershell
conda activate agent
pip install -r requirements.txt
```

Then open:

```text
vscode_runner.py
```

You can run cells with **Shift+Enter**.

### Check setup

Run the `CHECK SETUP` cell.

### Preview search queries

Run the `PREVIEW SEARCH QUERIES` cell. It also writes:

```text
output/search_plan.json
```

### Dry run

Uncomment:

```python
result = run_once(dry_run=True)
```

No application documents are generated.

### Real run

Uncomment:

```python
result = run_once(dry_run=False)
```

### Continuous mode

```python
watch(interval_minutes=30, dry_run=False)
```

This repeats the search while VS Code/Python and the laptop remain running.

## AI backends

`ai.provider: auto` chooses in this order:

1. OpenAI API if `OPENAI_API_KEY` exists;
2. Codex CLI if `codex` is installed/authenticated;
3. local heuristic matching.

Without API/Codex, discovery, filtering, deduplication and heuristic ranking still work, but the agent intentionally does **not** mark a package ready because genuine job-specific rewriting/translation was not performed.

## Search sources already implemented

- Adzuna API
- Jooble API
- Greenhouse boards
- Lever boards
- SmartRecruiters companies
- manual URLs
- saved `.eml` job-alert files

LinkedIn/Indeed/XING/StepStone account scraping is not built in. Their job-alert emails can be fed into the email-alert workflow instead.

## Per-job folder structure

Example:

```text
output/applications/2026-08-13/company/job_title/
├── job.json
├── job_description.txt
├── match.json
├── evidence_sources.json
├── CV_company_job_title_DE.tex
├── CV_company_job_title_DE.pdf
├── CoverLetter_company_job_title_DE.txt
├── CoverLetter_company_job_title_DE.tex
├── CoverLetter_company_job_title_DE.pdf
└── package_status.json
```

Existing application packages are stored in SQLite so repeated cycles do not notify you again for the same ready package.

## Freshness and live-vacancy checks

Default maximum age:

```yaml
max_age_days: 7
```

The agent can also check the original page before generating documents. Expired vacancies are discarded.

## Matching philosophy

The rule is:

```text
SEARCH BROADLY
      ↓
EVALUATE STRICTLY
      ↓
WRITE TRUTHFULLY
```

Exact title mismatch alone is not a reason to reject a job. The matcher evaluates underlying evidence and separates required vs nice-to-have requirements.

## Quality guardrails

- never invent skills or experience;
- never upgrade German beyond the real level;
- never overwrite source CVs;
- preserve identity placeholders;
- use the same language as the vacancy;
- remove thesis-only targeting for professional roles;
- target <= 2 A4 pages;
- only notify when the generated package passes readiness checks;
- never auto-submit an application.

## Tests

Run:

```powershell
python -m unittest discover -s tests -v
```

V1.4 currently tests:

- age filtering;
- capability-based CAE matching;
- deduplication;
- German/English job-language detection;
- employment-type detection;
- career-family classification;
- English/German + Mechanical/Wind base-CV selection;
- thesis-specialist base selection;
- all-CV evidence sharing;
- explicit German-language-requirement detection;
- no hard rejection solely for a German-language gap;
- identity-placeholder masking/restoration.
