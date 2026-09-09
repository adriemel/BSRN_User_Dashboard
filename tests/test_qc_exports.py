import csv
import io
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts import bsrn_dashboard_server as app
import pandas as pd
from scripts.bsrn_data_exports import LR0100_HEADERS
from scripts.bsrn_export_bundle import combine_radiation_exports
from scripts.bsrn_qc_continue import generate_interactive_report
from scripts.bsrn_qc_exports import QC_COLUMNS, QC_PARAMETERS, attach_qc_flags


class QCExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def table(self, values):
        path = self.root / 'TAT_2026-04_LR0100_radiation.csv'
        with path.open('w', newline='', encoding='utf-8') as handle:
            writer = csv.writer(handle)
            writer.writerow(['Date/Time', LR0100_HEADERS['SWD']])
            writer.writerows(values)
        return path

    def frame(self, times, values, flags):
        data = {'SWD': values}
        data.update({column: flags if column == 'SWDQc' else [0] * len(times) for column in QC_COLUMNS})
        return pd.DataFrame(data, index=pd.to_datetime(times))

    def read(self, path):
        with path.open(newline='', encoding='utf-8') as handle:
            return list(csv.DictReader(handle))

    def test_duplicates_missing_values_and_upward_only_rows(self):
        t = '2026-04-01T00:00'
        t2 = '2026-04-01T00:01'
        path = self.table([(t, '1'), (t, '2'), (t2, '')])
        original = path.read_bytes()
        flagged, warnings = attach_qc_flags(path, self.frame([t, t, t2], [1, 2, float('nan')], [1, 10, 0]))
        self.assertFalse(warnings)
        self.assertEqual([r['SWDQc'] for r in self.read(flagged)], ['1', '10', ''])
        self.assertEqual(path.read_bytes(), original)
        upward = self.root / 'TAT_2026-04_LR0300_radiation.csv'
        upward.write_text('Date/Time,SWU\n2026-04-01T00:02,12\n')
        combined = self.read(combine_radiation_exports([flagged, upward])[0])
        self.assertEqual(len(combined), 4)
        self.assertTrue(all(combined[-1][col] == '' for col in QC_COLUMNS))
        self.assertNotIn('SWUQc', combined[0])

    def test_ambiguous_duplicate_counts_and_value_mismatch_stay_blank(self):
        t = '2026-04-01T00:00'
        path = self.table([(t, '1'), (t, '2')])
        flagged, warnings = attach_qc_flags(path, self.frame([t], [2], [32]))
        self.assertTrue(warnings)
        self.assertEqual([r['SWDQc'] for r in self.read(flagged)], ['', ''])
        flagged, warnings = attach_qc_flags(path, self.frame([t, t], [2, 1], [32, 1]))
        self.assertTrue(warnings)
        self.assertEqual([r['SWDQc'] for r in self.read(flagged)], ['', ''])

    def test_minute_1440_rollover_and_no_timestamp(self):
        from scripts.bsrn_record_parsers import make_datetime
        t = make_datetime(2026, 4, 30, 1440)
        self.assertEqual(t, '2026-05-01T00:00')
        flagged, warnings = attach_qc_flags(self.table([(t, '2')]), self.frame([t], [2], [8]))
        self.assertEqual(self.read(flagged)[0]['SWDQc'], '8')
        self.assertFalse(warnings)
        with self.assertRaisesRegex(ValueError, 'timestamp'):
            attach_qc_flags(self.table([('', '2')]), self.frame([t], [2], [8]))

    def test_qc_request_requires_lr0100_and_boolean_option(self):
        state = {'busy': False, 'rows': [{'id': 'test', 'dat': 'test.dat'}]}
        with patch.object(app, 'STATE', state), patch.object(app.threading, 'Thread') as thread:
            for records, option in [(['0300'], True), (['0100'], 'false')]:
                with self.assertRaises(ValueError):
                    app.start_action('export', {'jobs': ['test'], 'records': records,
                                                'format': 'csv', 'include_qc': option})
            thread.assert_not_called()

    def test_qc_failure_is_reported_without_silent_unflagged_fallback(self):
        (self.root / 'runs' / 'test').mkdir(parents=True)
        table = self.table([('2026-04-01T00:00', '1')])
        rows = [{'id': 'test', 'dat': table.name, 'source': 'test', 'records': ['0100']}]
        state = {'busy': False, 'run': 'runs/test', 'rows': rows}
        with patch.object(app, 'OUTPUT', self.root), patch.object(app, 'STATE', state), \
                patch.object(app, 'generate_data_exports_for_status', return_value=([table], [])), \
                patch('scripts.bsrn_qc_exports.with_qc_flags', side_effect=ValueError('QC could not run')):
            app.export_batch({'records': ['0100'], 'format': 'csv', 'include_qc': True}, rows)
        with zipfile.ZipFile(self.root / state['archive']) as bundle:
            self.assertFalse(any(n.endswith('.csv') for n in bundle.namelist()))
            manifest = json.loads(bundle.read('manifest.json'))
            self.assertEqual(manifest['failures'][0]['error'], 'QC could not run')

    def test_real_export_matches_dataframe_sent_to_interactive_report(self):
        fixture = app.ROOT / 'input/tat0426.dat'
        if not fixture.exists():
            self.skipTest('Place tat0426.dat in input for real-data QC parity checks.')
        run = self.root / 'runs' / 'test'
        (run / 'dat').mkdir(parents=True)
        source = run / 'dat' / fixture.name
        shutil.copy2(fixture, source)
        with patch('interactive_report.generate_interactive_report') as writer:
            generate_interactive_report(source, run)
            report_df = writer.call_args.args[0]
        rows = [{'id': 'TAT_2026-04', 'dat': 'runs/test/dat/tat0426.dat',
                 'source': fixture.name, 'records': ['0100', '0300'], 'qc': None}]
        state = {'busy': False, 'rows': rows, 'run': 'runs/test'}
        with patch.object(app, 'OUTPUT', self.root), patch.object(app, 'STATE', state):
            for fmt, records in [('csv', ['0100']), ('tsv', ['0100', '0300'])]:
                app.export_batch({'format': fmt, 'records': records, 'include_qc': True}, rows)
                with zipfile.ZipFile(self.root / state['archive']) as bundle:
                    manifest = json.loads(bundle.read('manifest.json'))
                    self.assertFalse(manifest['failures'])
                    self.assertFalse(manifest['files'][0]['warnings'])
                    self.assertEqual(manifest['files'][0]['qc_columns'], QC_COLUMNS)
                    self.assertIn('QC_FLAGS.txt', bundle.namelist())
                    table = next(n for n in bundle.namelist() if n.endswith('.' + fmt))
                    self.assertIn('_with_QC', table)
                    exported = list(csv.DictReader(io.StringIO(bundle.read(table).decode()), delimiter=',' if fmt == 'csv' else '\t'))
                    self.assertEqual(len(exported), len(report_df))
                    for row, (timestamp, expected) in zip(exported, report_df.iterrows()):
                        self.assertEqual(row['Date/Time'], timestamp.isoformat(timespec='minutes'))
                        for parameter in QC_PARAMETERS:
                            flag = '' if pd.isna(expected[parameter]) else str(int(expected[parameter + 'Qc']))
                            self.assertEqual(row[parameter + 'Qc'], flag)
                    self.assertNotIn('SWUQc', exported[0])
                    self.assertNotIn('LWUQc', exported[0])
            # Toggling the option off must not reuse a flagged cached table.
            app.export_batch({'format': 'csv', 'records': ['0100', '0300']}, rows)
            with zipfile.ZipFile(self.root / state['archive']) as bundle:
                table = next(n for n in bundle.namelist() if n.endswith('.csv'))
                self.assertNotIn('_with_QC', table)
                self.assertNotIn('QC_FLAGS.txt', bundle.namelist())
                plain = list(csv.DictReader(io.StringIO(bundle.read(table).decode())))
                self.assertEqual(plain, [{k: v for k, v in r.items() if k not in QC_COLUMNS} for r in exported])


if __name__ == '__main__':
    unittest.main()
