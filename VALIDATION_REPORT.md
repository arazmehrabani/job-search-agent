# Job Search Agent V1.8.2 — Validation Report

## Automated tests

```text
71 passed
```

The suite includes all prior V1.3–V1.8.1 regression coverage plus V1.8.2 tests for:

- globally ranked deep-AI budget allocation;
- `deep_pending` carry-over to the next cycle without repeating the screen;
- MATCH_ONLY reporting eligible would-generate packages while writing no application files;
- FULL_APPLICATION_PREP invoking package generation and high-priority notification paths;
- local Customer Support Engineer / Tender Manager rejection;
- post-enrichment Bundesagentur `bei <company>` title cleanup.

## Source CV compilation

Validated with the installed LaTeX toolchain:

```text
mechanical_en_master.tex   OK  2 pages
mechanical_de_master.tex   OK  2 pages
wind_en_master.tex         OK  2 pages
wind_de_master.tex         OK  2 pages
wind_thesis_en_master.tex  OK  2 pages
```

Compiler output decoding is now explicit UTF-8 with replacement handling, avoiding false failures on German TeX output.

## Safety / workflow checks

- `MATCH_ONLY` never invokes `generate_package()` and never sends a desktop notification.
- `FULL_APPLICATION_PREP` generates only for completed deep matches above the configured package-priority threshold.
- PRE/SCREEN-only matches are prevented from final `HIGH/APPLY` status.
- Application auto-submission remains disabled.
- The 1.5 s + jitter per-host throttle, robots policy, retries and page cache remain enabled.
- Semantic claim-vs-evidence audit remains required for READY status.
- Source CVs are never overwritten.
