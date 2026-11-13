# DATA CARD: Verdict real-filings corpus (v2)

- **What:** SEC EDGAR 10-K/10-Q filings, rendered to text pages from the primary financial statements; gold labels from the filer's own XBRL facts for 8 fields.
- **Built by:** `python -m abstention.data.edgar_corpus` on the author's machine (sec.gov is not reachable from the cloud sandbox). Declared User-Agent, at most 8 requests/s, local cache in `corpus/cache/` (git-ignored).
- **Frozen by:** `corpus/manifest.json` (accession numbers, SHA-256 of every input and label file) and its `corpus_hash`, pinned in PREREG.md.
- **Splits:** DEV 100 / TEST 300 filings, split by company; at most 2 test filings per company; stratified by SIC division. TEST is readable only through `experiment/lockbox.py`.
- **Not in the corpus:** loan applications, bank statements, tax returns, scanned or photographed documents. Public companies are a stand-in, not small-business lending documents.
- **Known weaknesses:** gold labels derive from filer tagging, which the SEC says it cannot guarantee; the statement-page locator is a heuristic; filings after 2026-07-01 are 10-Q-heavy; smaller-reporting-company status is recorded (`filer_category`) but not filtered on.
- **Licence/terms:** SEC filings are public documents; follow sec.gov access rules. Confirm current terms yourself.
