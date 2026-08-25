# V1.8.3 — Application Package Integrity & Cover-Letter Template Correction

V1.8.3 is a document-generation correction release built on V1.8.2 Hotfix 1. It addresses the real application-package output reviewed on 2026-08-14: cover letters were too short compared with the preferred application style, evidence-trace failures were incorrectly blocking truthful documents, valid PDFs could be recorded as failed, and recovery mode was not represented correctly on the dashboard.

## 1. Canonical cover-letter templates

Two sanitized templates are now shipped:

- `input/templates/cover_letter_de.tex`
- `input/templates/cover_letter_en.tex`

They follow the preferred recent application layout: compact Helvetica-style header, contact line, horizontal rule, company/date block, bold application subject, substantive role-specific body, and signature. The templates contain placeholders only; no personal contact data from the example applications is shipped.

`config.yaml` now points to these templates and defines a preferred substantive cover-letter range of roughly 400–560 words when enough verified evidence exists. The AI prompt explicitly asks for a reasoned evidence-to-role argument rather than a short CV summary.

## 2. Better cover-letter reasoning structure

Cover-letter generation now asks for:

1. role/company motivation and strongest overall fit;
2. concrete professional engineering evidence linked to requirements;
3. a second relevant professional example;
4. a relevant academic/research/robotics/wind/prototyping project only when useful;
5. a truthful transfer/gap paragraph when appropriate;
6. a specific closing.

German remains B1/actively learning. Full-time applications are not reframed as thesis applications. Redacted identity fields remain redacted.

## 3. Evidence audit now separates truth from trace metadata

The old semantic audit effectively treated a missing evidence ID as if the factual claim itself were unsupported. This caused false failures in the reviewed Alpha, Da Vinci and Akkodis packages.

V1.8.3 audits both the claim content and the trace metadata against the full verified evidence catalog, and classifies each material claim as:

- `SUPPORTED`
- `TRACE_MISSING`
- `TRACE_MISMATCH`
- `MINOR_OVERSTATEMENT`
- `UNSUPPORTED_CONTENT`

`TRACE_MISSING` and `TRACE_MISMATCH` are repaired as metadata when the claim is actually supported. They no longer automatically block an otherwise truthful package.

## 4. Full evidence catalog available to document auditing

Document generation still uses a focused evidence subset for efficient tailoring, but the semantic audit receives the complete verified registry. This allows legitimate existing CV claims—such as the underwater-welding robot (`CTRL_001`) or the current wind-inflow thesis (`WIND_THS_001/002`)—to be matched to their correct evidence even when those objects were not selected in the initial job-specific subset.

Each package now also writes `evidence_audit_catalog.json` for audit transparency.

## 5. One bounded automatic content-repair pass

If a claim remains genuinely overstated or unsupported after trace repair, the agent performs one bounded correction pass:

- CV: revise/remove only flagged claims while preserving design and protected identity tokens.
- Cover letter: revise/remove flagged claims while preserving the preferred substantive structure.
- The revised claims are audited again once.

The package is still blocked if material unsupported content remains after that correction pass.

## 6. PDF success is validated from the artifact

`compile_latex()` no longer relies solely on the compiler process return code. It now validates that the generated file is a readable PDF (and uses `pdfinfo` when available). A non-zero compiler code with a readable PDF is recorded as a warning rather than automatically setting `cv_pdf=false` / `cover_pdf=false`.

Stale PDFs are removed before compilation so an old file cannot create a false success.

## 7. Recovery/repair dashboard telemetry

Recovery and package-repair runs now also update `output/last_run_report.json`. The dashboard therefore shows the correct execution mode, document-generation status, Codex calls, runtime and zero HTTP activity instead of `UNKNOWN / 0 calls / 0.0s`.

## 8. Repair existing needs-review packages without another job search

New VS Code helper:

```python
result = repair_packages()
```

New CLI command:

```powershell
python agent.py repair-packages
```

This regenerates application packages already recorded as `needs_ai_or_review` using cached completed deep matches. It performs no discovery, page fetching, SCREEN calls or deep job matching.

`resume_packages()` remains for interrupted runs that have deep matches but no application record yet.

## 9. Matching cache compatibility

The matching `analysis_version` intentionally remains `1.8.2`. V1.8.3 changes document generation/auditing, not the job-fit model. Existing V1.8.2 deep-match results can therefore be reused instead of spending Codex usage to repeat them.

## Validation

- 76 / 76 automated tests passed.
- Python compile-all passed.
- Both sanitized cover-letter templates render and compile to one-page PDFs in the validation fixture.
- All five sanitized source CVs compile successfully to two pages.
- Windows-safe package naming from Hotfix 1 remains in place.
- Per-host HTTP throttling remains unchanged.
- Automatic application submission remains disabled.
