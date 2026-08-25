# V1.4.1 hotfix

- Restored compact dashboard layout with 13 useful columns instead of 21 wide columns.
- Company and role text are clipped/wrapped safely in the UI.
- Dashboard labels heuristic results as **PRE** and Codex/API results as **AI**.
- Fixed TÜV SÜD SuccessFactors pages whose first H1 is `Welcome to TÜV SÜD Group Job Portal!`.
- Extracts the actual vacancy title from the `Job Description` block, with URL-slug fallback.
- SuccessFactors metadata now requires real `Label:` syntax, preventing a D&I sentence containing `company` from becoming the company field.
- Added English/German SuccessFactors metadata labels.
- Trims portal/cookie/D&I boilerplate from the text used for matching.
- Recalculates heuristic pre-scores every run, so repaired parsing immediately updates the score.
- VS Code setup check shows whether the `codex` executable is visible to the same Python process.
