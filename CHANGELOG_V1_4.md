# Job Search Agent V1.4 changelog

V1.4 is a correctness-focused update based on real manual-link tests against Ashby and TÜV SÜD/SAP SuccessFactors job pages.

## Fixed
- Platform-aware page enrichment via JSON-LD + Ashby + SuccessFactors fallbacks.
- Company, location, employment metadata and platform job/requisition IDs.
- Canonical URLs and tracking-parameter removal.
- Ashby `/application` vs vacancy URL deduplication.
- Legacy V1.3 URL migration and ghost-row cleanup command.
- `intern` no longer matches `international`.
- `fluent in German` is detected as a high German-language requirement.
- `German is advantageous` is detected as preferred, not required.
- German-title weighting improves original vacancy-language detection.
- Employment is modeled as career stage + schedule + contract.
- Parser failures are reported instead of saved as `Unknown job` records.
- Dashboard exposes the new employment and fit fields.

## Validation
19 unit/regression tests pass, including dedicated Ashby and SuccessFactors fixtures.
