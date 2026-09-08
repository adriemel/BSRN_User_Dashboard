# Scientific helpers adapted from BSRN_Dashboard.
from __future__ import annotations
import datetime as dt
from dataclasses import dataclass

@dataclass(frozen=True)
class StationJobMetadata:
    station_id: int
    event_label: str
    station_name: str
    source_id: int
    author_id: int
    author_name: str
    year: int
    month: int
    pangaea_reference_id: int
    latitude: float
    longitude: float

    @property
    def yyyy_mm(self) -> str:
        return f'{self.year:04d}-{self.month:02d}'

def qmid(line: str, start: int, length: int) -> str:
    return line[start:start + length].strip()

def as_float(text: str) -> float | None:
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    if value in {-999.0, -9999.0, -99.9}:
        return None
    return value

def as_lr0300_net_float(text: str) -> float | None:
    value = as_float(text)
    if value is None:
        return None
    return None if value <= -99.0 else value

def as_int(text: str) -> int | None:
    try:
        return int(text)
    except (TypeError, ValueError):
        return None

def make_datetime(year: int, month: int, day: int, minute: int) -> str:
    return (dt.datetime(year, month, day) + dt.timedelta(minutes=minute)).isoformat(timespec='minutes')

def first_lr0004_lat_lon(blocks: dict[str, list[str]]) -> tuple[float, float]:
    lr0004 = blocks.get('0004') or []
    for line in lr0004:
        parts = line.split()
        if len(parts) >= 2:
            try:
                return (float(parts[0]) - 90.0, float(parts[1]) - 180.0)
            except ValueError:
                continue
    return (0.0, 0.0)

def parse_lr0100_rows(blocks: dict[str, list[str]], meta: StationJobMetadata) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    lines = [line.strip() for line in blocks.get('0100', []) if line.strip()]
    for index in range(0, len(lines) - 1, 2):
        p1 = lines[index].split()
        p2 = lines[index + 1].split()
        if len(p1) < 10 or len(p2) < 11:
            continue
        day = as_int(p1[0])
        minute = as_int(p1[1])
        if day is None or minute is None:
            continue
        rows.append({'Date/Time': make_datetime(meta.year, meta.month, day, minute), 'Height': 2, 'SWD': as_float(p1[2]), 'SWD_sd': as_float(p1[3]), 'SWD_min': as_float(p1[4]), 'SWD_max': as_float(p1[5]), 'DIR': as_float(p1[6]), 'DIR_sd': as_float(p1[7]), 'DIR_min': as_float(p1[8]), 'DIR_max': as_float(p1[9]), 'DIF': as_float(p2[0]), 'DIF_sd': as_float(p2[1]), 'DIF_min': as_float(p2[2]), 'DIF_max': as_float(p2[3]), 'LWD': as_float(p2[4]), 'LWD_sd': as_float(p2[5]), 'LWD_min': as_float(p2[6]), 'LWD_max': as_float(p2[7]), 'T2': as_float(p2[8]), 'RH': as_float(p2[9]), 'P': as_float(p2[10])})
    return rows

def parse_lr0300_rows(blocks: dict[str, list[str]], meta: StationJobMetadata) -> dict[str, dict[str, object]]:
    rows: dict[str, dict[str, object]] = {}
    for line in blocks.get('0300', []):
        parts = line.split()
        if len(parts) < 10:
            continue
        day = as_int(parts[0])
        minute = as_int(parts[1])
        if day is None or minute is None:
            continue
        timestamp = make_datetime(meta.year, meta.month, day, minute)
        row = {'SWU': as_float(parts[2]), 'SWU_sd': as_float(parts[3]), 'SWU_min': as_float(parts[4]), 'SWU_max': as_float(parts[5]), 'LWU': as_float(parts[6]), 'LWU_sd': as_float(parts[7]), 'LWU_min': as_float(parts[8]), 'LWU_max': as_float(parts[9])}
        if len(parts) >= 14:
            row.update({'NET': as_lr0300_net_float(parts[10]), 'NET_sd': as_float(parts[11]), 'NET_min': as_lr0300_net_float(parts[12]), 'NET_max': as_lr0300_net_float(parts[13])})
        rows[timestamp] = row
    return rows

def parse_lr1100_rows(blocks: dict[str, list[str]], meta: StationJobMetadata) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in blocks.get('1100', []):
        parts = line.split()
        if len(parts) >= 10:
            day = as_int(parts[0])
            minute = as_int(parts[1])
            if day is None or minute is None:
                continue
            row = {'Date/Time': make_datetime(meta.year, meta.month, day, minute), 'Altitude': as_float(parts[4]), 'Pressure': None if parts[3] == '-999' else as_float(parts[3]), 'Temperature': lr1100_number(parts[5], '-99.9'), 'Dew/frost point': lr1100_number(parts[6], '-999.9'), 'Wind direction': None if parts[7] == '-99' else as_float(parts[7]), 'Wind speed': None if parts[8] == '-99' else as_float(parts[8]), 'Ozone': None if parts[9] == '-9.9' else as_float(parts[9])}
        else:
            day = as_int(qmid(line, 1, 2))
            minute = as_int(qmid(line, 4, 4))
            if day is None or minute is None:
                continue
            row = {'Date/Time': make_datetime(meta.year, meta.month, day, minute), 'Altitude': as_float(qmid(line, 21, 5)), 'Pressure': as_float(qmid(line, 16, 4)) if qmid(line, 16, 4) != '-999' else None, 'Temperature': lr1100_number(qmid(line, 27, 5), '-99.9'), 'Dew/frost point': lr1100_number(qmid(line, 33, 6), '-999.9'), 'Wind direction': as_float(qmid(line, 40, 3)) if qmid(line, 40, 3) != '-99' else None, 'Wind speed': as_float(qmid(line, 44, 3)) if qmid(line, 44, 3) != '-99' else None, 'Ozone': as_float(qmid(line, 48, 4)) if qmid(line, 48, 4) != '-9.9' else None}
        if row['Altitude'] is not None and any((row.get(key) is not None for key in row if key not in {'Date/Time', 'Altitude'})):
            rows.append(row)
    return rows

def lr1100_number(text: str, missing_value: str) -> float | None:
    if text.strip() == missing_value:
        return None
    try:
        return float(text)
    except ValueError:
        return None

def parse_lr1300_rows(blocks: dict[str, list[str]], meta: StationJobMetadata) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []

    def valid_above(text: str, threshold: float) -> float | None:
        value = as_float(text)
        return value if value is not None and value > threshold else None
    for line in blocks.get('1300', []):
        parts = line.split()
        if len(parts) >= 8:
            day = as_int(parts[0])
            minute = as_int(parts[1])
            if day is None or minute is None:
                continue
            row = {'Date/Time': make_datetime(meta.year, meta.month, day, minute), 'Total cloud amount': valid_above(parts[2], -9), 'Cloud base height': valid_above(parts[3], -9), 'Cloud liquid water': valid_above(parts[4], -9.8), 'AOD wavelength 1': valid_above(parts[5], -9.998), 'AOD wavelength 2': valid_above(parts[6], -9.998), 'AOD wavelength 3': valid_above(parts[7], -9.998)}
        else:
            day = as_int(qmid(line, 1, 2))
            minute = as_int(qmid(line, 4, 4))
            if day is None or minute is None:
                continue
            total = as_float(qmid(line, 9, 4))
            base = as_float(qmid(line, 14, 5))
            liquid = as_float(qmid(line, 20, 5))
            aod1 = as_float(qmid(line, 28, 6))
            aod2 = as_float(qmid(line, 35, 6))
            aod3 = as_float(qmid(line, 42, 6))
            row = {'Date/Time': make_datetime(meta.year, meta.month, day, minute), 'Total cloud amount': total if total is not None and total > -9 else None, 'Cloud base height': base if base is not None and base > -9 else None, 'Cloud liquid water': liquid if liquid is not None and liquid > -9.8 else None, 'AOD wavelength 1': aod1 if aod1 is not None and aod1 > -9.998 else None, 'AOD wavelength 2': aod2 if aod2 is not None and aod2 > -9.998 else None, 'AOD wavelength 3': aod3 if aod3 is not None and aod3 > -9.998 else None}
        if any((value is not None for key, value in row.items() if key != 'Date/Time')):
            rows.append(row)
    return rows

def parse_lr3x30_rows(blocks: dict[str, list[str]], meta: StationJobMetadata, record: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    clean_lines = [line.strip() for line in blocks.get(record, []) if line.strip()]
    for i in range(0, len(clean_lines) - 1, 2):
        p1 = clean_lines[i].split()
        p2 = clean_lines[i + 1].split()
        if len(p1) < 10 or len(p2) < 10:
            continue
        day, minute = (as_int(p1[0]), as_int(p1[1]))
        if day is None or minute is None:
            continue
        rows.append({'Date/Time': make_datetime(meta.year, meta.month, day, minute), 'Short-wave downward (GLOBAL) radiation [W/m**2]': as_float(p1[2]), 'Short-wave downward (GLOBAL) radiation, standard deviation [W/m**2]': as_float(p1[3]), 'Short-wave downward (GLOBAL) radiation, minimum [W/m**2]': as_float(p1[4]), 'Short-wave downward (GLOBAL) radiation, maximum [W/m**2]': as_float(p1[5]), 'Short-wave upward (REFLEX) radiation [W/m**2]': as_float(p1[6]), 'Short-wave upward (REFLEX) radiation, standard deviation [W/m**2]': as_float(p1[7]), 'Short-wave upward (REFLEX) radiation, minimum [W/m**2]': as_float(p1[8]), 'Short-wave upward (REFLEX) radiation, maximum [W/m**2]': as_float(p1[9]), 'Long-wave downward radiation [W/m**2]': as_float(p2[0]), 'Long-wave downward radiation, standard deviation [W/m**2]': as_float(p2[1]), 'Long-wave downward radiation, minimum [W/m**2]': as_float(p2[2]), 'Long-wave downward radiation, maximum [W/m**2]': as_float(p2[3]), 'Long-wave upward radiation [W/m**2]': as_float(p2[4]), 'Long-wave upward radiation, standard deviation [W/m**2]': as_float(p2[5]), 'Long-wave upward radiation, minimum [W/m**2]': as_float(p2[6]), 'Long-wave upward radiation, maximum [W/m**2]': as_float(p2[7]), 'Air temperature [deg C]': as_float(p2[8]), 'Relative Humidity [%]': as_float(p2[9])})
    return rows
