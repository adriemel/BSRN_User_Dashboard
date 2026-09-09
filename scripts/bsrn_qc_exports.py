"""Attach LR0100 QC codes without modifying the cached plain-data exports."""
import csv
import math
from collections import Counter, defaultdict
from pathlib import Path

from scripts.bsrn_data_exports import LR0100_HEADERS
from scripts.bsrn_qc_continue import prepare_qc_data

QC_PARAMETERS = ('SWD', 'DIR', 'DIF', 'LWD', 'T2')
QC_COLUMNS = [p + 'Qc' for p in QC_PARAMETERS]
QC_LEGEND = """LR0100 quality-control flags
Columns: SWDQc (global downward short-wave), DIRQc (direct normal),
DIFQc (diffuse downward short-wave), LWDQc (downward long-wave),
T2Qc (air temperature).
Codes use the same calculation pipeline as the interactive QC report.
Flags are calculated from the full source file, regardless of which records
are selected for export. No flags for LR0300 or other records are exported.

Each integer is a bit mask. Add the values for all raised checks:
  1 = below physically possible limit
  2 = above physically possible limit
  4 = below extremely rare limit
  8 = above extremely rare limit
 16 = below comparison limit
 32 = above comparison limit
Example: 10 = 2 + 8 (above physically possible and extremely rare limits).
0 means no flags were raised by the available checks. It does not mean that
every check was applicable or that the observation is certified valid.
An empty flag means a missing/non-finite observation or one that could not
be aligned with the QC parser. Alignment warnings appear in manifest.json.
Rows present only in LR0300 have empty LR0100 flag fields.

Alignment uses UTC timestamp and occurrence order for repeated timestamps,
with matching row counts and observation values required. Data rows are
never filtered, duplicated, or replaced by QC values.
"""


def with_qc_flags(path: Path, dat_path: Path) -> tuple[Path, list[str]]:
    df, _, _ = prepare_qc_data(dat_path)
    return attach_qc_flags(path, df)


def attach_qc_flags(path: Path, df) -> tuple[Path, list[str]]:
    """Write a distinct flagged LR0100 table; ambiguous matches stay blank."""
    with path.open(newline='', encoding='utf-8') as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames or []
        rows = list(reader)
    if 'Date/Time' not in columns or any(not r['Date/Time'] for r in rows):
        raise ValueError('LR0100 QC export requires a timestamp for every row.')
    if set(QC_COLUMNS) & set(columns):
        raise ValueError('Expected an unflagged LR0100 export.')
    if not set(QC_COLUMNS).issubset(df.columns):
        raise ValueError('The QC calculation did not produce all LR0100 flag columns.')

    # Count both sides first: a skipped duplicate must not shift subsequent flags.
    grouped = defaultdict(list)
    for timestamp, values in zip(df.index, df.to_dict('records')):
        grouped[timestamp.isoformat(timespec='minutes')].append(values)
    counts = Counter(r['Date/Time'] for r in rows)
    seen = Counter()
    unaligned = 0
    for row in rows:
        timestamp = row['Date/Time']
        matches = grouped[timestamp]
        occurrence = seen[timestamp]
        seen[timestamp] += 1
        row.update(dict.fromkeys(QC_COLUMNS, ''))
        if len(matches) != counts[timestamp]:
            unaligned += 1
            continue
        match = matches[occurrence]
        # Verify all LR0100 mean observations to catch parser disagreement,
        # including a reordered duplicate with different RH or pressure.
        mismatch = False
        for parameter in (*QC_PARAMETERS, 'RH', 'P'):
            value = row.get(LR0100_HEADERS[parameter], '')
            qc_value = match.get(parameter, float('nan'))
            value_present = bool(value) and math.isfinite(float(value))
            qc_present = math.isfinite(float(qc_value))
            if value_present != qc_present:
                mismatch = True
                break
            if value_present:
                if not math.isclose(float(value), float(qc_value), rel_tol=1e-10, abs_tol=1e-10):
                    mismatch = True
                    break
        if mismatch:
            unaligned += 1
            continue
        for parameter in QC_PARAMETERS:
            value = row.get(LR0100_HEADERS[parameter], '')
            qc_value = match.get(parameter, float('nan'))
            if value and math.isfinite(float(value)) and math.isfinite(float(qc_value)):
                row[parameter + 'Qc'] = int(match[parameter + 'Qc'])

    output = path.with_name(path.stem + '_with_QC.csv')
    temporary = output.with_suffix('.partial')
    with temporary.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=columns + QC_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(output)
    warnings = ([f'QC flags left blank for {unaligned} LR0100 rows because the data and QC parsers could not be aligned.']
                if unaligned else [])
    return output, warnings
