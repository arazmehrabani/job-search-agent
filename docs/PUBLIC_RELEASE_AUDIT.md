# Public release audit

## Summary

The archived project is technically substantial and well tested, but the v1.9.0 landing page was written primarily as an internal recovery/upgrade note. The public release therefore changes presentation and repository hygiene without rewriting the underlying implementation history.

## Kept public

- source code and tests;
- historical changelogs and validation report;
- sanitized CV/profile templates and verified evidence registry;
- example environment/configuration files;
- career-scope configuration;
- public-safe documentation of the resource-governed architecture.

These files help a reviewer understand not only what the agent does but how it constrains hallucination, resource usage, duplicate work, and unsafe automation.

## Excluded or ignored

- `.env` and secrets;
- SQLite/runtime databases;
- generated dashboards, digests, application packages, caches, and telemetry;
- raw exported email alerts;
- Python/pytest caches;
- LaTeX build artifacts;
- editor/OS metadata.

## Privacy transformations

The archives already contain identity placeholders rather than real contact information. The public-history reconstruction additionally removes an account-specific Windows home-directory component and replaces account-specific provider usage quota/date values with a generic locked template.

## Presentation changes

- Replace the incident-focused root README with a project overview.
- Preserve detailed v1.9.0 recovery information in release/history artifacts rather than making it the first thing a reviewer sees.
- Add architecture and development-history documentation.
- Add a synthetic dashboard demo screenshot.
- Add CI for the existing regression suite.
- Expand `.gitignore` for public development hygiene.

## Technical strengths visible to reviewers

- clear separation between deterministic/local and provider-backed work;
- explicit source-health and HTTP politeness controls;
- evidence registry and traceability rather than unconstrained generation;
- distinction between match quality and application priority;
- SQLite state/migration behavior and deduplicated notifications;
- regression suites accumulated alongside release evolution;
- failure-aware AI budgets and cross-project usage accounting;
- human review before application submission.

## Remaining improvement opportunities

These are good future engineering tasks, not blockers for publication:

1. Break up large modules such as `src/pipeline.py` and `src/ai.py` into smaller services.
2. Reduce the number of broad `except Exception` handlers by narrowing expected failure classes and logging structured context.
3. Add type checking (for example, mypy/pyright) and a formatter/linter to CI.
4. Add dependency pinning/lock-file strategy for reproducible environments.
5. Add unit-level coverage reporting rather than relying only on regression pass count.
6. Add connector contract tests with recorded fixtures for external-source schema changes.
7. Decide on an explicit repository license before inviting external reuse/contributions.

## Publication verdict

Suitable for a public portfolio repository after the documented sanitization and README/CI/demo changes. The strongest story is the engineering evolution from a simple search tool into a stateful, evidence-constrained, resource-governed automation workflow.

## Archive provenance

SHA-256 values of the uploaded source archives used for this reconstruction:

```text
45acf2e45185e676af0c09de16980dc934c23591eb97bcdaa249a5ed5276e56f  job_search_agent_v1_3 to v1_8_3.zip
83b82af3ff4cadae605b649e8f8beab9ec86fb48edaa31b3d56291f3e5e130d0  job_search_agent_v1_9_0.zip
```
