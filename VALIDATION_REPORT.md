# V1.4.1 Validation Report

## Automated tests

- 21/21 tests passing.
- Existing V1.4 regression coverage retained.
- New live-shape SuccessFactors regression reproduces the TÜV SÜD portal pattern where the first H1 is `Welcome to TÜV SÜD Group Job Portal!`, normal D&I prose contains the word `company`, and the actual ATS metadata appears later as `Company:`.
- The test verifies the actual role title is recovered, company is `TÜV SÜD Industrie Service GmbH`, location is `München`, employment is full-time, and `Fluent in German` is detected.
- A scoring regression verifies that correcting the portal title increases the heuristic pre-score instead of leaving the stale wrong-title score cached.

## Dashboard

The dashboard was reduced from 21 columns to 13 main columns. Employment dimensions are combined into compact chips, match-detail fields move into an expandable section, and company/title/location values are clipped and wrapped to prevent a malformed ATS field from destroying the layout. Heuristic values are explicitly marked `PRE`; Codex/API values are marked `AI`.

## Cache behavior

Heuristic scores are recalculated every run. This is intentional and cheap. Therefore a parser correction updates the score on the next run even if the SQLite database already contains a V1.4 heuristic result. Codex/API scores remain cached to avoid unnecessary usage.

## Codex detection

V1.4.1 checks the normal PATH plus the common Windows npm-global location `%APPDATA%\npm\codex.cmd`. An explicit `ai.codex_path` or `CODEX_CLI_PATH` can also be used.

## LaTeX / CV evidence

The five sanitized base/evidence CVs from V1.4 are unchanged. The existing identity-placeholder protection and no-invention rules remain active.
