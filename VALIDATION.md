# Validation — 8 September 2026

## Passed

- Six regression tests: input/date validation and path confinement; bounded parallel transfers and failure isolation; retries, cache integrity and refresh; real-file selective CSV/TSV equivalence and export caching; absence of curator entry points; localhost API protections and rejection of curator actions.
- TAT April 2026, BON January 2025, and IZA May 2026 loaded and passed the inherited format checker.
- All 15 readable CSV outputs from those files have identical SHA-256 hashes to outputs from the original curator exporter. Export warnings also match.
- QC summary hashes and parsed row counts match the original scientific pipeline: TAT 43,200 rows; BON and IZA 44,640 rows each.
- Browser verification: three-stage navigation, loaded-file selection, coverage, embedded TAT QC plots, and bulk TSV export.
- Plotly is embedded in generated reports. Station coordinates replace the external map dependency. The overall displayed flag percentage uses parameter-time entries as its denominator; scientific flag calculations are unchanged.
- JavaScript syntax check passed.
- Original project source/input/config/document hashes remained unchanged. All work was staged outside the curator project.

## Live FTP limitation

The live CAB March 2025 FTPS check reached the BSRN server and obtained the expected file size, but no payload bytes arrived before timeout. Both the existing curl transport and Python FTPS transport timed out. The default encrypted transport and local credentials were preserved; no plaintext fallback was introduced. Retry/concurrency/cache behavior passed controlled tests, but successful live FTP delivery and a network speedup could not be verified in this session.

## Scope

This is a local first version. Tables remain separate by station-month and logical record. LR0001–LR0009 and LR4000 are not exported. Bulk multi-month merged tables, a hosted service, and a historical-run browser are outside this version. Earlier runs remain on disk. QC for a large batch is sequential to bound memory; reports are generated on request.

## FTP follow-up

The fully encrypted data channel repeatedly stalled, including with passive-mode and TLS-version variations and explicit session reuse. Encrypted login with clear public data transfer (`ftps-control`) successfully downloaded CAB May 2026 (1,909,905 compressed bytes; 12,866,165 DAT bytes) in 0.91 seconds, with gzip validation. The explicit mode is visible in Download options and retains certificate-verified encrypted login. No automatic fallback to plaintext login was added. A regression test verifies the login remains FTP_TLS and the plain FTP client is not used.

## Combined exports and additional plots

Eleven regression tests passed, including real TAT LR0100+0300 CSV and TSV exports checked cell-for-cell against the separate source tables, timestamp outer joins, duplicate preservation, and single-record selection. The additional plot gallery was verified on PAY January and February 2025: five figures each (daily panels, all-days overlay, LR0500, LR1200 and LR3010), without plot warnings. The solar loading indicator respects reduced-motion preferences.
