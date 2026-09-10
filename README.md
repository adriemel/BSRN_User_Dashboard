# BSRN User Dashboard

A local dashboard for downloading BSRN station-month files, exploring scientific quality control, and exporting readable data. It is independent of the BSRN curator dashboard and does not check or update PANGAEA reference IDs or generate import files.
Note that mass download of station-to-archive files with this Dashboard will take a while, so if you want to work with a lot of files you might want to download them separately and then use the "input" folder of the BSRN User Dashboard to load the files.

## Short instruction
Clone the repo, change config/bsrn_workflow.ini.example to config/bsrn_workflow.ini and enter the login credentials you obtained from amelie.driemel@awi.de, then double click on **Start-BSRN-User-Dashboard.cmd** and start the work! :) Download station-to-archive files, QC them or export the data into tabular csv/tsv format. You need a working Python environment and the packages listed in requirements.txt

## Start

Double-click **Start-BSRN-User-Dashboard.cmd**. The dashboard opens at **http://127.0.0.1:8766**. The BSRN curator dashboard is running on port 8765 and could theoretically be used in parallel.

For a fresh checkout, install Python 3.10 or newer and run `python -m pip install -r requirements.txt` from this folder. Start with the Windows launcher or `python scripts/bsrn_launch_dashboard.py`. The launcher can also use a locally available Codex Python runtime and `.packages` directory; neither is included in the repository. Do not copy binary dependencies between different Python versions or operating systems; install requirements instead.

## Get data

- **FTP:** select one or more stations and a first/last month. The range is inclusive. Some station-months will not exist; a missing month is reported individually.
- **Local:** place `.dat` files in this project's `input` folder, choose **Use input folder**, refresh the list, and select files. Subfolders are supported. Files are copied into the batch workspace before processing.
- Loading creates a new batch without deleting previous batches. All batches remain under `output/runs`. The interface shows the latest batch after restart.

FTP credentials belong in `config/bsrn_workflow.ini`; use the adjacent example for a new installation. Environment variables `BSRN_FTP_USER` and `BSRN_FTP_PASSWORD` override stored credentials. The repository contains only a placeholder configuration example, not working credentials. Copy `config/bsrn_workflow.ini.example` to `config/bsrn_workflow.ini` and enter your BSRN read-account credentials before downloading. The private configuration, local DATs, dependencies, and generated outputs are ignored by Git. Do not include private configuration when distributing the project.

**Connection mode:** the example configuration uses `protocol = ftps-control`: authentication and commands are encrypted and the public station data payload is unencrypted. This avoids the encrypted-data-channel stall reproduced on this connection. Use `protocol = ftps` for encryption of both login and data where the network/server supports it. There is no automatic downgrade between modes.

Transfers run concurrently (1–4 workers, controlled by `download_workers`) while completed files are checked. Failed transfers get up to three attempts total; confirmed unavailable files are not retried. **Reuse verified local downloads** avoids transfers when the local DAT still matches its stored SHA-256 checksum. Leave reuse off to retrieve upstream corrections. Reuse verifies local integrity; it does not check whether the FTP copy has changed. After an interruption, reload the same selection with reuse enabled; completed cached transfers are retained.

## Explore & QC

Select a station-month, review minute coverage and format results, and generate QC plots for that file. **Run QC for all loaded files** processes the entire batch. A format warning remains visible but does not prevent attempting QC or export. A QC failure affects that file only.

Interactive reports appear directly in the dashboard. An **Additional plots** gallery offers the original daily SWD/SumSW panels, all-days overlay and available optional-record figures, with links to full-resolution PNGs. Re-run QC on older results to generate the gallery. A small animated sun accompanies batch progress and respects reduced-motion preferences. They include radiation and flag plots, meteorology, scatter/ratio diagnostics, missing data, summaries and minima. The Plotly library is embedded so plots work offline. Station coordinates are shown without remote map tiles. LR4000 diagnostics remain available when present; LR4000 is not exported.

QC flags indicate observations to investigate, not automatic rejection. The report's overall flag percentage counts parameter-time entries, rather than distinct timestamps. Scientific thresholds and checks are inherited from the curator version.

## Export

Select one or more loaded files, one or more available logical records, and CSV or tab-delimited TSV. A ZIP contains tables per station-month, plus a README and manifest describing source hashes, absent records and failures. When both LR0100 and LR0300 are selected and available, they are exported as one `LR0100+0300` table matched on Date/Time. Times found in only one record are retained with empty cells for the other record; repeated timestamps are paired in source order. Selecting only one record still exports it individually.

Supported records: **LR0100, LR0300, LR0500, LR1000, LR1100, LR1200, LR1300, LR3010, LR3030**. LR0001–LR0009 and LR4000 are excluded. Other unsupported data records are shown explicitly. Export does not require QC to finish and does not filter values based on QC flags.

Exports retain the existing parser's readable headers and units. Missing values are empty cells; entirely empty columns may be omitted as in the original exporter. Different files may consequently have different columns. Timestamps use the source BSRN convention. Other logical records remain separate. Multi-month merging is not implemented in this version.

## Project layout

- `web/`: the three-screen user interface.
- `scripts/bsrn_dashboard_server.py`: local API, batch processing and export packaging.
- `scripts/bsrn_record_parsers.py`: scientific parsers extracted from the curator project, without import-generation functions.
- Other `scripts/bsrn_*.py` helpers: format checks, parsing, exports, and optional logical records; no curator CLI entry points.
- `tools/qc-graphs/`: scientific QC and interactive reporting.
- `config/stations.json`: public station IDs, codes and names; no PANGAEA staff, method or reference lookup tables.
- `output/`: latest status, preserved batches and download cache.

The server binds to localhost, checks Host/Origin and a per-process request token, and serves only selected artifact types from its run folders. This is a local desktop tool, not a hosted multi-user service.

## Verification

Run `python -B -m unittest discover -s tests -v` from this folder. The real-data integration test uses `input/tat0426.dat` when available; other tests use controlled fixtures. See `VALIDATION.md` for the implementation-time checks.

Derived from the existing BSRN Dashboard; original license retained. Changes in this separate copy do not automatically propagate to the curator project.

### Session controls

Use **New session** to clear the dashboard and file selections for FTP or local input. Saved output files and verified download cache entries are retained. This control is disabled during active work. Unavailable and failed files appear in their own panel, with a link to the BSRN availability portal. Only explicit missing-file responses are classified as unavailable; other errors retain their details. The header links to the WRMC Curator. Bulk QC processes pending or failed jobs and disables when all loaded files have completed successfully; individual QC reports can still be regenerated.

### Export with QC flags

Select **Export with QC flags (LR0100)** to append `SWDQc`, `DIRQc`, `DIFQc`, `LWDQc`, and `T2Qc` to LR0100 CSV or TSV data. When LR0300 is also selected and available, these columns stay in the combined LR0100+0300 table. LR0300 and other records receive no flag columns. Flags are computed from the full DAT file through the same calculation pipeline as the interactive report; generating plots first is optional. Plain exports and cached source tables remain unchanged.

The ZIP includes `QC_FLAGS.txt`, explaining the bit values 1, 2, 4, 8, 16 and 32. Zero means no flags were raised by applicable checks, not that every check was possible. Missing observations and ambiguous parser alignments have empty flags; alignment warnings are recorded in `manifest.json`. Duplicate timestamps are paired in source order only when counts and values agree. Data values and rows are retained. Flagged table filenames end in `_with_QC`.

### After pulling an update

Double-click **Start-BSRN-User-Dashboard.cmd** after `git pull`, then refresh any existing browser tab. The launcher checks the running server against the code on disk and restarts an outdated idle server while preserving saved sessions, outputs and downloads. It waits for you to finish an active batch before applying an update. On Windows, older servers are identified by their listening port and exact dashboard script path before being stopped. On other systems, an older server without the shutdown API must be stopped manually once.

Refreshing the page alone can otherwise display new controls backed by an older server. The page now detects this mismatch and shows restart instructions instead of allowing unsupported New session or QC export requests.
