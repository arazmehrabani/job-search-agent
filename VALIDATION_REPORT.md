# Job Search Agent V1.8 — Validation Report

## Automated tests

`python -m unittest discover -s tests -q`

Result: **56 / 56 tests passed**.

The suite includes all prior parser, deduplication, German-language, CV selection, feedback, telemetry, HTTP/robots/cache, semantic evidence audit, discovery-source and Windows/Codex Unicode regressions plus V1.8 relevance tests.

## V1.8 regressions added

Validated that:

- `Software Engineer, Backend Focused` is rejected as `PURE_SOFTWARE_BACKEND` and receives PRE 0.
- `mechanical engineer` catalogue search no longer matches a backend role merely because both titles contain `engineer`.
- `Software Engineer - Simulation` remains eligible because a real simulation bridge exists.
- `Control Software Engineer - Wind Turbines` remains eligible because control/wind bridges exist.
- `Finance & Accounting Manager Renewable Energy` is still rejected; an industry keyword cannot rescue a wrong profession.
- `Mechanical Engineer` without explicit full-time metadata is not accidentally filtered as an unsupported `professional` employment state.
- Structural Analysis Engineer scores far above a backend software role.
- Generic `Systems Engineer` requires real mechanical/simulation/validation evidence in the description.
- Dashboard keeps hard rejects auditable but outside the normal attention list.

## Static validation

- `python -m compileall` passes for the source tree, `agent.py`, and `vscode_runner.py`.
- All five sanitized LaTeX CV bases compile successfully and remain 2 pages each.
- Existing V1.6 semantic evidence/claim-audit code and V1.7.1 UTF-8 Codex subprocess handling are unchanged except for analysis-version refresh to `1.8`.

## Recommended real-world validation

Run V1.8 from a fresh folder/database and compare the first discovery cycle with the V1.7 PDF. Expected behavior:

1. raw discovery can remain broad;
2. a large fraction of obvious software/business titles should be counted in `title_gate_rejected`;
3. the main dashboard should be much shorter;
4. mechanical/CAE/wind/simulation jobs should appear before ambiguous adjacent roles;
5. hard-rejected titles should not consume Codex calls.
