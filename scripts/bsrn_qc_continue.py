# Scientific helpers adapted from BSRN_Dashboard.
from __future__ import annotations
import datetime as dt
from pathlib import Path
LR0500_UV_B_MILLIWATT_STATIONS = {'BON', 'BOS', 'DRA', 'FPE', 'GCR', 'MAN', 'NAU', 'PAY', 'PSU', 'SXF', 'TOR'}

def generate_interactive_report(dat_path: Path, qc_root: Path, *, parsed_data=None) -> Path:
    import bsrn_qc
    from interactive_report import generate_interactive_report as write_interactive_report
    df, metadata = bsrn_qc.parse_dat_file(dat_path) if parsed_data is None else parsed_data
    df = bsrn_qc.compute_solar_auxiliary(df, metadata['latitude'], metadata['longitude'])
    lr4000_report = bsrn_qc.check_lr4000(df, metadata)
    df = bsrn_qc.run_qc_checks(df)
    qc_summary = bsrn_qc.summarize_qc_flags(df)
    report_path = qc_root / f"{metadata['station_code']}_{metadata['year']}-{metadata['month']:02d}_QC_report_interactive.html"
    write_interactive_report(df, metadata, qc_summary, report_path, lr4000_report)
    return report_path

def extract_optional_logical_records(dat_path: Path, year: int, month: int, station_code: str, latitude: float, longitude: float) -> dict[str, list[dict[str, object]]]:
    lines = dat_path.read_text(encoding='utf-8', errors='ignore').splitlines()
    blocks: dict[str, list[str]] = {}
    current_record: str | None = None
    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith(('*C', '*U')):
            record_id = line[2:].strip()
            if not record_id.isdigit():
                current_record = None
            else:
                current_record = record_id.zfill(4)
            if current_record is not None:
                blocks.setdefault(current_record, [])
            continue
        if current_record is not None:
            blocks[current_record].append(raw_line)
    extracted: dict[str, list[dict[str, object]]] = {}
    if '0500' in blocks:
        rows = parse_lr0500(blocks['0500'], year, month, station_code)
        if rows:
            extracted['LR0500'] = rows
    if '1000' in blocks:
        rows = parse_lr1000(blocks['1000'], year, month, dat_path.stem[:3].upper(), latitude, longitude)
        if rows:
            extracted['LR1000'] = rows
    if '1200' in blocks:
        rows = parse_lr1200(blocks['1200'], year, month)
        if rows:
            extracted['LR1200'] = rows
    if '3010' in blocks:
        rows = parse_lr3010(blocks['3010'], year, month)
        if rows:
            extracted['LR3010'] = rows
    return extracted

def parse_lr0500(lines: list[str], year: int, month: int, station_code: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    clean_lines = [line.strip() for line in lines if line.strip()]
    uv_b_in_milliwatts = station_code.upper() in LR0500_UV_B_MILLIWATT_STATIONS
    for i in range(0, len(clean_lines) - 1, 2):
        p1 = clean_lines[i].split()
        p2 = clean_lines[i + 1].split()
        if len(p1) < 10 or len(p2) < 12:
            continue
        day, minute = (parse_int(p1[0]), parse_int(p1[1]))
        if day is None or minute is None:
            continue
        rows.append({'Date/Time': make_datetime(year, month, day, minute), 'date_day': day, 'time_min': minute, 'UV-a global [W/m**2]': clean_number(p1[2]), 'UV-a global, standard deviation [W/m**2]': clean_number(p1[3]), 'UV-a global, minimum [W/m**2]': clean_number(p1[4]), 'UV-a global, maximum [W/m**2]': clean_number(p1[5]), 'UV-b direct [W/m**2]': clean_lr0500_uv_b_number(p1[6], uv_b_in_milliwatts), 'UV-b direct, standard deviation [W/m**2]': clean_lr0500_uv_b_number(p1[7], uv_b_in_milliwatts), 'UV-b direct, minimum [W/m**2]': clean_lr0500_uv_b_number(p1[8], uv_b_in_milliwatts), 'UV-b direct, maximum [W/m**2]': clean_lr0500_uv_b_number(p1[9], uv_b_in_milliwatts), 'UV-b global [W/m**2]': clean_lr0500_uv_b_number(p2[0], uv_b_in_milliwatts), 'UV-b global, standard deviation [W/m**2]': clean_lr0500_uv_b_number(p2[1], uv_b_in_milliwatts), 'UV-b global, minimum [W/m**2]': clean_lr0500_uv_b_number(p2[2], uv_b_in_milliwatts), 'UV-b global, maximum [W/m**2]': clean_lr0500_uv_b_number(p2[3], uv_b_in_milliwatts), 'UV-b diffuse [W/m**2]': clean_lr0500_uv_b_number(p2[4], uv_b_in_milliwatts), 'UV-b diffuse, standard deviation [W/m**2]': clean_lr0500_uv_b_number(p2[5], uv_b_in_milliwatts), 'UV-b diffuse, minimum [W/m**2]': clean_lr0500_uv_b_number(p2[6], uv_b_in_milliwatts), 'UV-b diffuse, maximum [W/m**2]': clean_lr0500_uv_b_number(p2[7], uv_b_in_milliwatts), 'UV upward reflected [W/m**2]': clean_number(p2[8]), 'UV upward reflected, standard deviation [W/m**2]': clean_number(p2[9]), 'UV upward reflected, minimum [W/m**2]': clean_number(p2[10]), 'UV upward reflected, maximum [W/m**2]': clean_number(p2[11])})
    return rows

def clean_lr0500_uv_b_number(value: str, uv_b_in_milliwatts: bool) -> float | None:
    number = clean_number(value)
    if number is None or not uv_b_in_milliwatts:
        return number
    return number / 1000.0

def parse_lr1000(lines: list[str], year: int, month: int, station_code: str, latitude: float, longitude: float) -> list[dict[str, object]]:
    clean_lines = [line.rstrip('\n') for line in lines if line.strip()]
    synop_format = lr1000_station_format(station_code)
    if synop_format == 2:
        return parse_lr1000_format2(clean_lines, year, month, station_code, latitude, longitude)
    if synop_format == 6:
        return parse_lr1000_format6(clean_lines, year, month, station_code, latitude, longitude)
    if synop_format in {1, 3, 4, 5}:
        return parse_lr1000_synop_groups(clean_lines, year, month, station_code, latitude, longitude, synop_format)
    if lr1000_looks_like_fm12_synop_groups(clean_lines):
        return parse_lr1000_synop_groups(clean_lines, year, month, station_code, latitude, longitude, 1)
    rows = []
    for index, line in enumerate(clean_lines, start=1):
        code = line.strip()
        if code:
            rows.append({'line': index, 'SYNOP format': synop_format or 'unknown', 'FM 12-XII Ext. SYNOP code': code})
    return rows

def lr1000_station_format(station_code: str) -> int | None:
    station = station_code.lower()
    if station in {'lin', 'sbo'}:
        return 1
    if station in {'abs', 'fua', 'ish', 'mnm', 'sap', 'syo', 'tat', 'tor'}:
        return 2
    if station == 'tam':
        return 3
    if station == 'pay':
        return 4
    if station == 'son':
        return 5
    if station in {'gvn', 'nya'}:
        return 6
    return None

def lr1000_looks_like_fm12_synop_groups(lines: list[str]) -> bool:
    """Recognize standard YYGGiw IIiii Nddff FM-12 SYNOP groups.

    The original Tool 1 converter has explicit station dispatch for several
    LR1000 layouts. Some valid stations publish standard FM-12 SYNOP groups
    without being present in that older station list, so this fallback applies
    the documented group grammar rather than a station/month-specific override.
    """
    data_lines = [line.strip() for line in lines if line.strip()]
    if not data_lines:
        return False
    checked = 0
    for line in data_lines:
        parts = line.split()
        if len(parts) < 8:
            return False
        if not all((len(part) == 5 for part in parts[:8])):
            return False
        first, station_group, wind_group = (parts[0], parts[1], parts[2])
        if not (first[:4].isdigit() and first[4] in '0123456789/'):
            return False
        if not station_group.isdigit():
            return False
        if not (wind_group[0] in '0123456789/' and all((char.isdigit() or char == '/' for char in wind_group[1:]))):
            return False
        checked += 1
        if checked >= 20:
            break
    return True

def parse_lr1000_format2(lines: list[str], year: int, month: int, station_code: str, latitude: float, longitude: float) -> list[dict[str, object]]:
    fields = [('Temperature, air [deg C]', 9, 5, lambda line: qmid(line, 9, 5) != '-99.0', 'number'), ('Pressure, atmospheric [hPa]', 15, 5, lambda line: qmid(line, 17, 3) != '-99', 'number'), ('Dew/frost point [deg C]', 21, 5, lambda line: qmid(line, 21, 5) != '-99.0', 'number'), ('Wind direction [deg]', 27, 3, lambda line: qmid(line, 27, 3) != '-99', 'number'), ('Wind speed [m/sec]', 31, 3, lambda line: qmid(line, 31, 3) != '-99', 'number'), ('Past weather1 [code]', 35, 1, lambda line: qmid(line, 35, 1) != '/', 'text'), ('Present weather [code]', 37, 2, lambda line: qmid(line, 37, 2) != '//', 'text'), ('Total cloud amount [code]', 40, 1, lambda line: qmid(line, 40, 1) != '/', 'text'), ('Low/middle cloud amount [code]', 42, 1, lambda line: qmid(line, 42, 1) != '/', 'text'), ('Low cloud [code]', 44, 1, lambda line: qmid(line, 44, 1) != '/', 'text'), ('Middle cloud [code]', 46, 1, lambda line: qmid(line, 46, 1) != '/', 'text'), ('High cloud [code]', 48, 1, lambda line: qmid(line, 48, 1) != '/', 'text'), ('Cloud base height [code]', 50, 1, lambda line: qmid(line, 50, 1) != '/', 'text'), ('Present blowing snow [code]', 52, 1, lambda line: qmid(line, 52, 1) != '/', 'text'), ('Past blowing snow [code]', 53, 1, lambda line: qmid(line, 53, 1) != '/', 'text'), ('Horizontal visibility [code]', 55, 2, lambda line: qmid(line, 55, 2) != '//', 'text')]
    active = [any((test(line) for line in lines)) for _, _, _, test, _ in fields]
    rows: list[dict[str, object]] = []
    for line in lines:
        day = parse_int(qmid(line, 1, 2))
        minute = parse_int(qmid(line, 4, 4))
        if day is None or minute is None:
            continue
        row: dict[str, object] = {'Station': station_code.upper(), 'Date/Time': make_datetime(year, month, day, minute), 'Latitude': latitude, 'Longitude': longitude, 'SYNOP format': 2}
        for enabled, (name, start, length, _test, value_type) in zip(active, fields):
            if not enabled:
                continue
            value = qmid(line, start, length).replace('/', '').replace(' ', '')
            if value_type == 'number':
                row[name] = clean_synop_number(value)
            else:
                row[name] = value or None
        row['FM 12-XII Ext. SYNOP code'] = line.strip()
        rows.append(row)
    return rows

def parse_lr1000_format6(lines: list[str], year: int, month: int, station_code: str, latitude: float, longitude: float) -> list[dict[str, object]]:
    fields = [('Cloud base height [code]', 9, 1, lambda line: qmid(line, 9, 1) != '/', 'text'), ('Horizontal visibility [code]', 11, 2, lambda line: qmid(line, 11, 2) != '//', 'text'), ('Wind direction [deg]', 14, 3, lambda line: qmid(line, 14, 3) != '-99', 'number'), ('Wind speed [m/sec]', 18, 5, lambda line: qmid(line, 18, 5) != '-99.0', 'number'), ('Temperature, air [deg C]', 24, 5, lambda line: qmid(line, 24, 5) != '-99.0', 'number'), ('Dew/frost point [deg C]', 30, 5, lambda line: qmid(line, 30, 5) != '-99.0', 'number'), ('Pressure, atmospheric [hPa]', 36, 6, lambda line: qmid(line, 37, 5) != '-99.0', 'number'), ('Characteristic of barometric tendency [code]', 43, 1, lambda line: qmid(line, 43, 1) != '/', 'text'), ('Amount of barometric tendency [hPa]', 45, 5, lambda line: qmid(line, 45, 5) != '-99.0', 'number'), ('Present weather [code]', 51, 2, lambda line: qmid(line, 51, 2) != '//', 'text'), ('Past weather1 [code]', 54, 1, lambda line: qmid(line, 54, 1) != '/', 'text'), ('Past weather2 [code]', 56, 1, lambda line: qmid(line, 56, 1) != '/', 'text'), ('Low cloud [code]', 58, 1, lambda line: qmid(line, 58, 1) != '/', 'text'), ('Middle cloud [code]', 60, 1, lambda line: qmid(line, 60, 1) != '/', 'text'), ('High cloud [code]', 62, 1, lambda line: qmid(line, 62, 1) != '/', 'text'), ('Total cloud amount', 64, 1, lambda line: qmid(line, 64, 1) != '/', 'text'), ('Low/middle cloud amount [code]', 66, 1, lambda line: qmid(line, 66, 1) != '/', 'text'), ('Temperature, air, maximum [deg C]', 68, 5, lambda line: qmid(line, 68, 5) != '-99.0', 'number'), ('Temperature, air, minimum [deg C]', 74, 5, lambda line: qmid(line, 74, 5) != '-99.0', 'number'), ('Present blowing snow [code]', 80, 1, lambda line: qmid(line, 80, 1) != '/', 'text'), ('Past blowing snow [code]', 82, 1, lambda line: qmid(line, 82, 1) != '/', 'text'), ('Whiteout yes/no [y/n]', 84, 1, lambda line: qmid(line, 84, 1) != '/', 'text')]
    active = [any((test(line) for line in lines)) for _, _, _, test, _ in fields]
    rows: list[dict[str, object]] = []
    for line in lines:
        day = parse_int(qmid(line, 1, 2))
        minute = parse_int(qmid(line, 4, 4))
        if day is None or minute is None:
            continue
        row: dict[str, object] = {'Station': station_code.upper(), 'Date/Time': make_datetime(year, month, day, minute), 'Latitude': latitude, 'Longitude': longitude, 'SYNOP format': 6}
        for enabled, (name, start, length, _test, value_type) in zip(active, fields):
            if not enabled:
                continue
            value = qmid(line, start, length).replace('/', '').replace(' ', '')
            if value_type == 'number':
                row[name] = clean_synop_number(value)
            else:
                row[name] = value or None
        row['FM 12-XII Ext. SYNOP code'] = line.strip()
        rows.append(row)
    return rows

def parse_lr1000_synop_groups(lines: list[str], year: int, month: int, station_code: str, latitude: float, longitude: float, synop_format: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        day = parse_int(parts[0][0:2])
        hour = parse_int(parts[0][2:4])
        if day is None or hour is None:
            continue
        row: dict[str, object] = {'Station': station_code.upper(), 'Date/Time': (dt.datetime(year, month, day) + dt.timedelta(hours=hour)).isoformat(timespec='minutes'), 'Latitude': latitude, 'Longitude': longitude, 'SYNOP format': synop_format, 'IIiii': group_value(parts, 1)}
        if synop_format in {1, 5}:
            parse_synop_n_dd_ff(row, group_value(parts, 2))
            parse_synop_temperature(row, 'Temperature, air [deg C]', group_value(parts, 3))
            parse_synop_temperature(row, 'Dew/frost point [deg C]', group_value(parts, 4))
            parse_synop_pressure(row, 'Station Pressure [hPa]', group_value(parts, 5))
            pressure_label = 'Geopotential height [m]' if synop_format == 5 else 'Pressure, atmospheric [hPa]'
            parse_synop_pressure(row, pressure_label, group_value(parts, 6))
            parse_synop_weather(row, group_value(parts, 7))
            parse_synop_clouds(row, group_value(parts, 8))
            parse_synop_layers(row, parts[10:13])
        elif synop_format in {3, 4}:
            offset = 1 if year < 2008 and synop_format == 3 else 0
            if offset:
                parse_synop_visibility_group(row, group_value(parts, 2))
            parse_synop_n_dd_ff(row, group_value(parts, 2 + offset))
            parse_synop_temperature(row, 'Temperature, air [deg C]', group_value(parts, 3 + offset))
            parse_synop_temperature(row, 'Dew/frost point [deg C]', group_value(parts, 4 + offset))
            parse_synop_pressure(row, 'Station Pressure [hPa]', group_value(parts, 5 + offset))
            pressure_label = 'Pressure, atmospheric [hPa]' if synop_format == 4 else 'Geopotential height [m]'
            parse_synop_pressure(row, pressure_label, group_value(parts, 6 + offset))
            parse_synop_weather(row, group_value(parts, 7 + offset))
            parse_synop_clouds(row, group_value(parts, 8 + offset))
            layer_start = 10 + offset
            parse_synop_layers(row, parts[layer_start:layer_start + 3])
        row['FM 12-XII Ext. SYNOP code'] = line.strip()
        rows.append(row)
    return shrink_empty_columns(rows)

def group_value(parts: list[str], index: int) -> str:
    return parts[index] if len(parts) > index else ''

def synop_token(value: str) -> str | None:
    value = value.replace('/', '').strip()
    return value or None

def parse_synop_n_dd_ff(row: dict[str, object], group: str) -> None:
    if len(group) < 5:
        return
    row['Total cloud amount [code]'] = clean_synop_number(synop_token(group[0]) or '')
    dd = synop_token(group[1:3])
    row['Wind direction [deg]'] = int(dd) * 10 if dd and dd.isdigit() else None
    row['Wind speed [m/sec]'] = clean_synop_number(synop_token(group[3:5]) or '')

def parse_synop_temperature(row: dict[str, object], label: str, group: str) -> None:
    if len(group) < 5:
        return
    value = synop_token(group[2:5])
    if value is None or not value.isdigit():
        row[label] = None
        return
    number = int(value) / 10.0
    row[label] = -number if group[1:2] == '1' else number

def parse_synop_pressure(row: dict[str, object], label: str, group: str) -> None:
    if len(group) < 5:
        return
    value = synop_token(group[1:5])
    if value is None or not value.isdigit():
        row[label] = None
        return
    pressure = int(value) / 10.0
    row[label] = pressure + 1000.0 if pressure <= 200.0 and 'Pressure' in label else pressure

def parse_synop_weather(row: dict[str, object], group: str) -> None:
    if len(group) < 5:
        return
    row['Present weather [code]'] = clean_synop_number(synop_token(group[1:3]) or '')
    row['Past weather1 [code]'] = clean_synop_number(synop_token(group[3:4]) or '')
    row['Past weather2 [code]'] = clean_synop_number(synop_token(group[4:5]) or '')

def parse_synop_clouds(row: dict[str, object], group: str) -> None:
    if len(group) < 5:
        return
    row['Low/middle cloud amount [code]'] = clean_synop_number(synop_token(group[1:2]) or '')
    row['Low cloud [code]'] = clean_synop_number(synop_token(group[2:3]) or '')
    row['Middle cloud [code]'] = clean_synop_number(synop_token(group[3:4]) or '')
    row['High cloud [code]'] = clean_synop_number(synop_token(group[4:5]) or '')

def parse_synop_layers(row: dict[str, object], groups: list[str]) -> None:
    for index, group in enumerate(groups, start=1):
        if len(group) < 5:
            continue
        row[f'Ns {index} [code]'] = clean_synop_number(synop_token(group[1:2]) or '')
        row[f'C {index} [code]'] = clean_synop_number(synop_token(group[2:3]) or '')
        row[f'hshs {index} [code]'] = clean_synop_number(synop_token(group[3:5]) or '')

def parse_synop_visibility_group(row: dict[str, object], group: str) -> None:
    if len(group) < 5:
        return
    row['Cloud base height [code]'] = clean_synop_number(synop_token(group[2:3]) or '')
    row['Horizontal visibility [code]'] = clean_synop_number(synop_token(group[3:5]) or '')

def shrink_empty_columns(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    keep = {key for row in rows for key, value in row.items() if value not in {None, ''}}
    return [{key: value for key, value in row.items() if key in keep} for row in rows]

def qmid(line: str, start: int, length: int) -> str:
    return line[start:start + length].strip()

def clean_synop_number(value: str) -> float | int | None:
    if not value:
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    if number <= -90:
        return None
    if number.is_integer():
        return int(number)
    return number

def parse_lr1200(lines: list[str], year: int, month: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        day, minute = (parse_int(parts[0]), parse_int(parts[1]))
        if day is None or minute is None:
            continue
        rows.append({'Date/Time': make_datetime(year, month, day, minute), 'date_day': day, 'time_min': minute, 'Ozone total [DU]': clean_number(parts[2])})
    return rows

def parse_lr3010(lines: list[str], year: int, month: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    clean_lines = [line.strip() for line in lines if line.strip()]
    for i in range(0, len(clean_lines) - 1, 2):
        p1 = clean_lines[i].split()
        p2 = clean_lines[i + 1].split()
        if len(p1) < 10 or len(p2) < 10:
            continue
        day, minute = (parse_int(p1[0]), parse_int(p1[1]))
        if day is None or minute is None:
            continue
        rows.append({'Date/Time': make_datetime(year, month, day, minute), 'date_day': day, 'time_min': minute, 'Short-wave downward (GLOBAL) radiation [W/m**2]': clean_number(p1[2]), 'Short-wave downward (GLOBAL) radiation, standard deviation [W/m**2]': clean_number(p1[3]), 'Short-wave downward (GLOBAL) radiation, minimum [W/m**2]': clean_number(p1[4]), 'Short-wave downward (GLOBAL) radiation, maximum [W/m**2]': clean_number(p1[5]), 'Short-wave upward (REFLEX) radiation [W/m**2]': clean_number(p1[6]), 'Short-wave upward (REFLEX) radiation, standard deviation [W/m**2]': clean_number(p1[7]), 'Short-wave upward (REFLEX) radiation, minimum [W/m**2]': clean_number(p1[8]), 'Short-wave upward (REFLEX) radiation, maximum [W/m**2]': clean_number(p1[9]), 'Long-wave downward radiation [W/m**2]': clean_number(p2[0]), 'Long-wave downward radiation, standard deviation [W/m**2]': clean_number(p2[1]), 'Long-wave downward radiation, minimum [W/m**2]': clean_number(p2[2]), 'Long-wave downward radiation, maximum [W/m**2]': clean_number(p2[3]), 'Long-wave upward radiation [W/m**2]': clean_number(p2[4]), 'Long-wave upward radiation, standard deviation [W/m**2]': clean_number(p2[5]), 'Long-wave upward radiation, minimum [W/m**2]': clean_number(p2[6]), 'Long-wave upward radiation, maximum [W/m**2]': clean_number(p2[7]), 'Air temperature [deg C]': clean_number(p2[8]), 'Relative Humidity [%]': clean_number(p2[9])})
    return rows

def parse_int(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None

def clean_number(value: str) -> float | None:
    try:
        number = float(value)
    except ValueError:
        return None
    if number in {-999.0, -9999.0, -99.9}:
        return None
    return number

def make_datetime(year: int, month: int, day: int, minute: int) -> str:
    return (dt.datetime(year, month, day) + dt.timedelta(minutes=minute)).isoformat(timespec='minutes')
