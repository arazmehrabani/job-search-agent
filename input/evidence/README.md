# Evidence Registry

`evidence.json` is the verified claim registry used by V1.7 for retrieval, deep matching and document traceability.

Rules:

- Add only facts that are supported by a source CV/project/profile.
- Keep each claim atomic; do not merge two facts into a stronger new claim.
- Use stable IDs once an evidence item is used in application history.
- `source` identifies which sanitized CV(s) support the fact.
- The AI may emphasize or reword evidence, but it must not create claims beyond these factual boundaries.
