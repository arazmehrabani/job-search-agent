# Development history reconstruction

The Git history was reconstructed from archived source trees rather than invented from memory.

## Exact archived snapshots

| Tag | Verified focus |
|---|---|
| v1.3 | Oldest recoverable baseline |
| v1.4 | ATS parsing, enrichment, canonicalization, classification |
| v1.4.1 | SuccessFactors parsing and dashboard corrections |
| v1.4.2 | Manual-job freshness/filter fixes |
| v1.5 | Evidence registry, fit vs priority, feedback/digest/dashboard server |
| v1.5.1 | Evidence/config typing hotfix |
| v1.6 | HTTP safety/reliability and evidence validation |
| v1.7 | Broader German discovery and source-health reporting |
| v1.8 | Relevance gating and local-first AI allocation |
| v1.8.1 | Freshness staging and German location normalization |
| v1.8.2 | Explicit run modes and global deep-candidate allocation |
| v1.8.3 | Document/package resilience and evidence-trace repair |
| v1.9.0 | Resource-governed provider execution |

## Documented releases without exact snapshots

Historical changelogs also describe:

- `v1.7.1`
- `v1.8.2-hotfix1`

No standalone source archives were recovered for those states. Their changes are visible inside the next available snapshot delta, but creating separate commits/tags would pretend to know an exact filesystem state that is not available. They are therefore documented but intentionally untagged.

## Reconstruction rules

1. The filesystem diff determines what changed.
2. Release changelogs explain intent and are used as supporting evidence.
3. Tests and code structure are used to verify implementation details.
4. No intermediate coding steps are invented between archived snapshots.
5. Historical dates are not fabricated from ZIP packaging timestamps.
6. Public-history privacy transformations are narrowly scoped and documented.

## Public-history sanitization

The uploaded archives already used identity placeholders for name, email, phone, LinkedIn, and related CV fields. The public reconstruction additionally sanitizes:

- a local Windows user directory that appeared in v1.9.0 documentation;
- account-specific provider-usage percentage/reset-date state.

The provider usage hint remains fail-safe in the public history by using a generic locked value. Application source code is not rewritten for presentation purposes.
