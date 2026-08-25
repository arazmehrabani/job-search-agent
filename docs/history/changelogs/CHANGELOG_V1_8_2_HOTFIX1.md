# V1.8.2 Hotfix 1

This hotfix addresses the first real FULL_APPLICATION_PREP crash observed on Windows.

## Fixed

- Windows path-length failure during cover-letter creation for long company/job names.
- Application package folders are now bounded and collision-safe using an 8-character job fingerprint.
- Document filenames no longer repeat the full company and role; this preserves MAX_PATH headroom for `.tex`, `.pdf`, `.aux`, and `.log` files.
- A single document-generation exception no longer aborts the complete search run. Errors are written under `output/package_errors/YYYY-MM-DD/` and the agent continues with other jobs.
- Added `resume_packages()` recovery mode in `vscode_runner.py`. It uses already completed deep matches from the existing database and performs **no discovery, page fetching, job screening, or deep job matching**. It only runs the document-generation AI work needed for CV tailoring, cover letter generation, and semantic claim audit.
- Recovery writes `output/resume_packages_report.json`.

## Important cache compatibility

The matching `analysis_version` deliberately remains `1.8.2`. This means an existing V1.8.2 database can reuse the successful screen/deep-match results from the interrupted run instead of spending Codex usage to repeat them.

## Validation

73/73 automated tests pass, including a simulated long Jobtimum/Maritime Windows path and a regression proving that one package-generation error no longer terminates the whole pipeline.
