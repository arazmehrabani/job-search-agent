# V1.4.2

- Fixes blank manual-job rows caused by the global 7-day freshness hard filter.
- Manual URLs now bypass the age cutoff by default when the vacancy is still active.
- Automated discovery sources still obey `search.max_age_days`.
- Older manually supplied jobs receive a visible age warning in match risks instead of being silently skipped.
- Dashboard shows `Filtered: <reason>` for any future hard-filtered row instead of leaving an unexplained blank row.
- Adds an automatic SQLite migration for the new `filter_reason` field.
