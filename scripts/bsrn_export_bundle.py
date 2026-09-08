"""Combine the basic and upward radiation tables without losing source rows."""
import csv
from collections import defaultdict
from pathlib import Path


def combine_radiation_exports(paths: list[Path]) -> list[Path]:
    basic = next((p for p in paths if '_LR0100_' in p.name), None)
    upward = next((p for p in paths if '_LR0300_' in p.name), None)
    if basic is None or upward is None:
        return paths

    def read(path):
        with path.open(newline='', encoding='utf-8') as handle:
            reader = csv.DictReader(handle)
            columns = reader.fieldnames or []
            if 'Date/Time' not in columns:
                raise ValueError(f'{path.name}: Date/Time is required for combined export.')
            grouped = defaultdict(list)
            for row in reader:
                if not row['Date/Time']:
                    raise ValueError(f'{path.name}: a row has no timestamp.')
                grouped[row['Date/Time']].append(row)
            return columns, grouped

    left_columns, left = read(basic)
    right_columns, right = read(upward)
    overlap = (set(left_columns) & set(right_columns)) - {'Date/Time'}
    if overlap:
        raise ValueError('Conflicting radiation columns: ' + ', '.join(sorted(overlap)))
    columns = left_columns + [c for c in right_columns if c != 'Date/Time']
    combined = basic.with_name(basic.name.replace('_LR0100_', '_LR0100+0300_'))
    temporary = combined.with_suffix('.partial')
    with temporary.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for timestamp in sorted(left.keys() | right.keys()):
            # Pair repeated timestamps in their source order, without a Cartesian
            # product or discarding an unmatched occurrence from either table.
            a, b = left.get(timestamp, []), right.get(timestamp, [])
            for index in range(max(len(a), len(b))):
                row = {'Date/Time': timestamp}
                if index < len(a):
                    row.update(a[index])
                if index < len(b):
                    row.update(b[index])
                writer.writerow(row)
    temporary.replace(combined)
    return [combined if p == basic else p for p in paths if p != upward]
