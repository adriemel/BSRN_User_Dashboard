# Scientific helpers adapted from BSRN_Dashboard.
from __future__ import annotations
import csv
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
from scripts.bsrn_download_check import JobStatus, dat_blocks, read_dat_text, workflow_path

class DataExportError(Exception):
    pass
EXPORT_RECORDS = {'0100', '0300', '0500', '1000', '1100', '1200', '1300', '3010', '3030'}
LR0100_HEADERS = {'Date/Time': 'Date/Time', 'Height': 'Height above ground [m]', 'SWD': 'Short-wave downward radiation [W/m**2]', 'SWD_sd': 'Short-wave downward radiation, standard deviation [W/m**2]', 'SWD_min': 'Short-wave downward radiation, minimum [W/m**2]', 'SWD_max': 'Short-wave downward radiation, maximum [W/m**2]', 'DIR': 'Direct normal radiation [W/m**2]', 'DIR_sd': 'Direct normal radiation, standard deviation [W/m**2]', 'DIR_min': 'Direct normal radiation, minimum [W/m**2]', 'DIR_max': 'Direct normal radiation, maximum [W/m**2]', 'DIF': 'Diffuse short-wave downward radiation [W/m**2]', 'DIF_sd': 'Diffuse short-wave downward radiation, standard deviation [W/m**2]', 'DIF_min': 'Diffuse short-wave downward radiation, minimum [W/m**2]', 'DIF_max': 'Diffuse short-wave downward radiation, maximum [W/m**2]', 'LWD': 'Long-wave downward radiation [W/m**2]', 'LWD_sd': 'Long-wave downward radiation, standard deviation [W/m**2]', 'LWD_min': 'Long-wave downward radiation, minimum [W/m**2]', 'LWD_max': 'Long-wave downward radiation, maximum [W/m**2]', 'T2': 'Air temperature [deg C]', 'RH': 'Relative humidity [%]', 'P': 'Atmospheric pressure [hPa]'}
LR0300_HEADERS = {'Date/Time': 'Date/Time', 'SWU': 'Short-wave upward radiation [W/m**2]', 'SWU_sd': 'Short-wave upward radiation, standard deviation [W/m**2]', 'SWU_min': 'Short-wave upward radiation, minimum [W/m**2]', 'SWU_max': 'Short-wave upward radiation, maximum [W/m**2]', 'LWU': 'Long-wave upward radiation [W/m**2]', 'LWU_sd': 'Long-wave upward radiation, standard deviation [W/m**2]', 'LWU_min': 'Long-wave upward radiation, minimum [W/m**2]', 'LWU_max': 'Long-wave upward radiation, maximum [W/m**2]'}
LR1100_HEADERS = {'Date/Time': 'Date/Time', 'Altitude': 'Altitude [m]', 'Pressure': 'Pressure [hPa]', 'Temperature': 'Temperature [deg C]', 'Dew/frost point': 'Dew/frost point [deg C]', 'Wind direction': 'Wind direction [deg]', 'Wind speed': 'Wind speed [m/sec]', 'Ozone': 'Ozone [mPa]'}
LR1300_HEADERS = {'Date/Time': 'Date/Time', 'Total cloud amount': 'Total cloud amount', 'Cloud base height': 'Cloud base height [m]', 'Cloud liquid water': 'Cloud liquid water', 'AOD wavelength 1': 'Aerosol optical depth, wavelength 1', 'AOD wavelength 2': 'Aerosol optical depth, wavelength 2', 'AOD wavelength 3': 'Aerosol optical depth, wavelength 3'}

def read_blocks(dat_path: Path) -> dict[str, list[str]]:
    return dat_blocks(read_dat_text(dat_path).splitlines())

def export_metadata_from_blocks(status: JobStatus, blocks: dict[str, list[str]], dat_path: Path):
    from scripts.bsrn_record_parsers import StationJobMetadata, first_lr0004_lat_lon
    lr0001 = blocks.get('0001') or []
    station = status.job.split('_', 1)[0].upper() if status.job else dat_path.stem[:3].upper()
    station_id = 0
    year = month = 0
    if lr0001:
        first = lr0001[0]
        try:
            station_id = int(first[0:3].strip())
            month = int(first[4:6].strip())
            year = int(first[7:11].strip())
        except ValueError:
            pass
    if not year or not month:
        raise DataExportError(f'{dat_path.name}: LR0001 station month/year is missing or invalid.')
    latitude, longitude = first_lr0004_lat_lon(blocks)
    return StationJobMetadata(station_id=station_id, event_label=station, station_name=station, source_id=-999, author_id=-999, author_name='', year=year, month=month, pangaea_reference_id=-999, latitude=latitude, longitude=longitude)

def rename_rows(rows: list[dict[str, object]], headers: dict[str, str]) -> list[dict[str, object]]:
    renamed = []
    for row in rows:
        renamed.append({target: row.get(source) for source, target in headers.items() if source in row})
    return shrink_empty_columns(renamed)

def shrink_empty_columns(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    if not rows:
        return rows
    keep = {key for row in rows for key, value in row.items() if key == 'Date/Time' or value not in {None, ''}}
    return [{key: value for key, value in row.items() if key in keep} for row in rows]

def write_rows_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

def write_record_export(export_dir: Path, station: str, yyyy_mm: str, record: str, label: str, rows: list[dict[str, object]]) -> Path | None:
    rows = shrink_empty_columns(rows)
    if not rows:
        return None
    path = export_dir / f'{station}_{yyyy_mm}_{record}_{label}.csv'
    write_rows_csv(path, rows)
    return path

def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()

def _export_cache_key(status: JobStatus, dat_path: Path) -> str:
    sources = ('bsrn_data_exports.py', 'bsrn_download_check.py', 'bsrn_record_parsers.py', 'bsrn_qc_continue.py')
    parts = ['1', sys.version, status.job, str(dat_path.resolve()), _file_digest(dat_path)]
    parts.extend((_file_digest(PROJECT_ROOT / 'scripts' / name) for name in sources))
    return hashlib.sha256(json.dumps(parts).encode('utf-8')).hexdigest()

def generate_data_exports_for_status(status: JobStatus, run_root: Path) -> tuple[list[Path], list[str]]:
    """Reuse exports only when input, parser sources and every CSV still match."""
    if not status.dat_path or not workflow_path(status.dat_path).is_file():
        return _generate_data_exports_for_status(status, run_root)
    dat_path = workflow_path(status.dat_path)
    export_dir = run_root / 'data_exports'
    identity = hashlib.sha256((status.job + str(dat_path.resolve())).encode('utf-8')).hexdigest()
    manifest = export_dir / '.cache' / f'{identity}.json'
    key = None
    try:
        key = _export_cache_key(status, dat_path)
        cached = json.loads(manifest.read_text(encoding='utf-8'))
        if cached['key'] == key and cached['outputs']:
            outputs = []
            for item in cached['outputs']:
                path = export_dir / item['name']
                if path.resolve().parent != export_dir.resolve() or path.suffix != '.csv':
                    raise ValueError('Invalid cached export path')
                if _file_digest(path) != item['sha256']:
                    raise ValueError('Export has changed')
                outputs.append(path)
            warnings = cached['warnings']
            if not isinstance(warnings, list) or not all((isinstance(warning, str) for warning in warnings)):
                raise ValueError('Invalid cached warnings')
            return (outputs, warnings)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    outputs, warnings = _generate_data_exports_for_status(status, run_root)
    temporary = None
    try:
        if key is not None and outputs and (_export_cache_key(status, dat_path) == key):
            payload = {'key': key, 'warnings': warnings, 'outputs': [{'name': path.name, 'sha256': _file_digest(path)} for path in outputs]}
            manifest.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=manifest.parent, delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(payload, handle)
            os.replace(temporary, manifest)
    except OSError:
        pass
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return (outputs, warnings)

def _generate_data_exports_for_status(status: JobStatus, run_root: Path) -> tuple[list[Path], list[str]]:
    """Generate separate readable CSVs for supported data logical records."""
    if not status.dat_path:
        return ([], [f'Data export warning: {status.job} has no DAT file yet.'])
    dat_path = workflow_path(status.dat_path)
    if not dat_path.exists():
        return ([], [f'Data export warning: DAT file not found: {dat_path}'])
    from scripts.bsrn_record_parsers import parse_lr0100_rows, parse_lr0300_rows, parse_lr1100_rows, parse_lr1300_rows, parse_lr3x30_rows
    from scripts.bsrn_qc_continue import extract_optional_logical_records
    blocks = read_blocks(dat_path)
    meta = export_metadata_from_blocks(status, blocks, dat_path)
    export_dir = run_root / 'data_exports'
    export_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    warnings: list[str] = []
    station = meta.event_label.upper()
    yyyy_mm = meta.yyyy_mm
    lr0100 = rename_rows(parse_lr0100_rows(blocks, meta), LR0100_HEADERS)
    path = write_record_export(export_dir, station, yyyy_mm, 'LR0100', 'radiation', lr0100)
    if path is not None:
        outputs.append(path)
    lr0300 = [{'Date/Time': timestamp, **row} for timestamp, row in sorted(parse_lr0300_rows(blocks, meta).items())]
    path = write_record_export(export_dir, station, yyyy_mm, 'LR0300', 'upward_radiation', rename_rows(lr0300, LR0300_HEADERS))
    if path is not None:
        outputs.append(path)
    optional_rows = extract_optional_logical_records(dat_path, meta.year, meta.month, meta.event_label, meta.latitude, meta.longitude)
    for record_name, label in (('LR0500', 'ultraviolet'), ('LR1000', 'synop'), ('LR1200', 'ozone')):
        rows = optional_rows.get(record_name, [])
        path = write_record_export(export_dir, station, yyyy_mm, record_name, label, rows)
        if path is not None:
            outputs.append(path)
    path = write_record_export(export_dir, station, yyyy_mm, 'LR1100', 'radiosonde', rename_rows(parse_lr1100_rows(blocks, meta), LR1100_HEADERS))
    if path is not None:
        outputs.append(path)
    path = write_record_export(export_dir, station, yyyy_mm, 'LR1300', 'expanded', rename_rows(parse_lr1300_rows(blocks, meta), LR1300_HEADERS))
    if path is not None:
        outputs.append(path)
    for record, height in (('3010', 10), ('3030', 30)):
        rows = parse_lr3x30_rows(blocks, meta, record)
        for row in rows:
            row['Height above ground [m]'] = height
        path = write_record_export(export_dir, station, yyyy_mm, f'LR{record}', f'radiation_{height}m', rows)
        if path is not None:
            outputs.append(path)
    detected_data_records = sorted((record for record in blocks if record.isdigit() and 100 <= int(record) <= 3030 and (record not in EXPORT_RECORDS)))
    for record in detected_data_records:
        warnings.append(f'Data export warning: LR{record} is not yet available as a readable CSV export.')
    if not outputs:
        warnings.append(f'Data export warning: no supported data logical records were exported for {dat_path.name}.')
    return (outputs, warnings)
