# V1.7.1 Changelog

V1.7.1 is a Windows/Codex interoperability hotfix for V1.7 Discovery.

## Fixed

- Codex CLI subprocess communication now explicitly uses UTF-8 for stdin/stdout/stderr. This prevents Windows `UnicodeEncodeError: 'charmap' codec can't encode characters ...` when job descriptions, evidence, company names, locations, or generated prompts contain Unicode characters not representable in the active Windows `cp1252` code page.
- BeautifulSoup's non-fatal `XMLParsedAsHTMLWarning` is suppressed only inside the generic `strip_html()` helper. Some ATS/API descriptions can contain XML declarations/fragments; text extraction remains tolerant and no longer clutters the console.
- Added regression coverage for the Codex UTF-8 subprocess contract and XML-warning suppression.

## Unchanged

- V1.7 broad discovery (Bundesagentur für Arbeit + Arbeitnow)
- Codex-first provider selection
- evidence registry and semantic evidence audit
- HTTP throttling/cache/robots policy
- Fit/Priority/feedback logic
- CV and cover-letter generation behavior
