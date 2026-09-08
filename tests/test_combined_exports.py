import csv
import tempfile
import unittest
from pathlib import Path
from scripts.bsrn_export_bundle import combine_radiation_exports


class CombinedRadiationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def table(self, record, column, rows):
        path = self.root / f'CAB_2026-05_LR{record}_radiation.csv'
        with path.open('w', newline='', encoding='utf-8') as handle:
            writer = csv.writer(handle)
            writer.writerow(['Date/Time', column])
            writer.writerows(rows)
        return path

    def test_outer_join_retains_unmatched_times_and_values(self):
        a = self.table('0100', 'SWD [W/m**2]', [('2026-05-01T00:00', '-1.0'), ('2026-05-01T00:02', '3.25')])
        b = self.table('0300', 'SWU [W/m**2]', [('2026-05-01T00:01', '2.5'), ('2026-05-01T00:02', '')])
        out = combine_radiation_exports([a, b])
        self.assertEqual(len(out), 1)
        self.assertIn('LR0100+0300', out[0].name)
        with out[0].open(newline='', encoding='utf-8') as f:
            self.assertEqual(list(csv.reader(f)), [
                ['Date/Time', 'SWD [W/m**2]', 'SWU [W/m**2]'],
                ['2026-05-01T00:00', '-1.0', ''],
                ['2026-05-01T00:01', '', '2.5'],
                ['2026-05-01T00:02', '3.25', '']])

    def test_repeated_timestamps_do_not_multiply_or_drop_values(self):
        a = self.table('0100', 'SWD', [('t', '1'), ('t', '2'), ('t', '3')])
        b = self.table('0300', 'SWU', [('t', '4'), ('t', '5')])
        out = combine_radiation_exports([a, b])[0]
        with out.open(newline='') as f:
            self.assertEqual(list(csv.reader(f))[1:], [['t', '1', '4'], ['t', '2', '5'], ['t', '3', '']])

    def test_single_selection_and_other_records_remain_separate(self):
        a = self.table('0100', 'SWD', [('t', '1')])
        b = self.table('0300', 'SWU', [('t', '2')])
        other = self.table('0500', 'UV', [('t', '3')])
        self.assertEqual(combine_radiation_exports([a, other]), [a, other])
        self.assertEqual(combine_radiation_exports([b]), [b])
        self.assertEqual(combine_radiation_exports([a, b, other])[-1], other)

    def test_missing_timestamp_is_reported_instead_of_discarded(self):
        a = self.table('0100', 'SWD', [('', '1')])
        b = self.table('0300', 'SWU', [('t', '2')])
        with self.assertRaisesRegex(ValueError, 'no timestamp'):
            combine_radiation_exports([a, b])
