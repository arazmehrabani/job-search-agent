# V1.4 Validation Report

## Regression suite

`python -m unittest discover -s tests -v` -> **19 tests passed**.

V1.4 adds regression coverage for: international != internship; `fluent in German`; `German is advantageous`; Ashby tracking/application URL canonicalization; Ashby company/location/source-ID enrichment; SuccessFactors/TÜV company/location/employment/requisition extraction.

## Important limitation

Live ATS markup can change. V1.4 uses structured data and platform-aware fallbacks, but any page that blocks automated HTTP access is reported as an enrichment/parse failure rather than silently inventing company, location or employment type.

---


Validated on 2026-08-13.

## Source CV integration

Configured factual sources: 5

- mechanical_en
- mechanical_de
- wind_en
- wind_de
- wind_thesis_en

The four newly provided CVs were copied into the project only after sanitizing identity/contact/account-link fields. Engineering, education, project and skill content remains available to the evidence library.

## LaTeX compilation

All five source templates compile successfully without a photo file because the working templates use a safe optional-photo placeholder.

- `mechanical_de_master.tex` — 2 pages
- `mechanical_en_master.tex` — 2 pages
- `wind_de_master.tex` — 2 pages
- `wind_en_master.tex` — 2 pages
- `wind_thesis_en_master.tex` — 2 pages

## Automated tests

13 tests pass:

1. age filtering
2. broad CAE heuristic matching
3. career-family classification
4. EN/DE + Mechanical/Wind base selection
5. database deduplication
6. employment-type detection
7. English-language detection
8. multi-CV evidence sharing
9. stable fingerprinting
10. German-language detection
11. German B2/C1 requirement risk signal without hard rejection
12. identity-placeholder masking/restoration
13. specialist wind-thesis base selection

## Privacy check

The working CV folder was checked for the real contact/account identifiers from the uploaded four files. They are not carried into the V1.4 templates. Project/account links are represented by placeholders as well.

## Search-plan smoke test

With no API/Codex backend available in the validation environment, the static search planner still builds 32 queries in a cycle and rotates the rest of the broad career map over subsequent cycles.

## Base-selection smoke examples

- German `Berechnungsingenieur FEM` -> `mechanical_de`
- English `Wind Turbine Loads Engineer` -> `wind_en`
- English `Test Engineer Mechanical Systems` -> `mechanical_en`

The selected base is only a layout/emphasis choice; all configured CVs remain factual evidence during AI matching/tailoring.
