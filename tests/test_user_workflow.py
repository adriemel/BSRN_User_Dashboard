"""Run: python -B -m unittest discover -s tests -v."""
import configparser
import csv
import gzip
import io
import http.client
import json
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts import bsrn_dashboard_server as app
from scripts.bsrn_data_exports import generate_data_exports_for_status
from scripts.bsrn_download_check import Job, JobStatus


class UserWorkflowTests(unittest.TestCase):
    def setUp(self):
        (app.ROOT / 'output').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=app.ROOT / 'output')
        self.output = Path(self.temp.name)
        self.out_patch = patch.object(app, 'OUTPUT', self.output)
        self.out_patch.start()
        self.state_patch = patch.object(app, 'STATE', {'busy': False, 'rows': [], 'run': '', 'archive': None})
        self.state_patch.start()

    def tearDown(self):
        self.state_patch.stop()
        self.out_patch.stop()
        self.temp.cleanup()

    def test_validation_and_path_confinement(self):
        with self.assertRaises(ValueError):
            app.safe_path(self.output, '../config/bsrn_workflow.ini')
        with self.assertRaises(ValueError):
            app.validate_load({'source': 'ftp', 'stations': ['TAT'], 'start': '2026-04', 'end': '2026-03'})
        with self.assertRaises(ValueError):
            app.validate_load({'source': 'local', 'files': ['../README.md']})
        jobs = app.validate_load({'source': 'ftp', 'stations': ['TAT', 'TAT', 'BON'], 'start': '2025-12', 'end': '2026-01'})
        self.assertEqual([j.label for j in jobs], ['TAT_2025-12', 'BON_2025-12', 'TAT_2026-01', 'BON_2026-01'])

    def test_download_retries_cache_integrity_and_refresh(self):
        calls = []
        def fake(job, cfg, folder):
            calls.append(job)
            if len(calls) == 1:
                raise OSError('temporary disconnect')
            path = folder / job.gz_name
            with gzip.open(path, 'wb') as f:
                f.write(b'valid downloaded data')
            return path
        with patch.object(app, 'download_job', side_effect=fake), patch.object(app.time, 'sleep'):
            job = Job('TAT', 2026, 4)
            path, reused = app.fetch(job, configparser.ConfigParser(), False)
            self.assertFalse(reused)
            self.assertEqual(len(calls), 2)
            self.assertTrue(app.fetch(job, configparser.ConfigParser(), True)[1])
            path.write_bytes(b'changed')
            self.assertFalse(app.fetch(job, configparser.ConfigParser(), True)[1])
            app.fetch(job, configparser.ConfigParser(), False)
            self.assertEqual(len(calls), 4)

    def test_download_queue_continues_and_isolates_failure(self):
        active = peak = 0
        lock = threading.Lock()
        barrier = threading.Barrier(2)
        def fake(job, cfg, reuse):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                if job.month in (1, 2):
                    barrier.wait(5)
                if job.month == 2:
                    raise OSError('missing month')
                return Path(job.dat_name), False
            finally:
                with lock:
                    active -= 1
        def inspect(path, run, source, reused):
            return {'id': 'TAT_2026-' + path.name[3:5], 'error': '', 'records': ['0100']}
        cfg = configparser.ConfigParser()
        cfg['ftp'] = {'download_workers': '2'}
        with patch.object(app, 'fetch', side_effect=fake), patch.object(app, 'inspect_file', side_effect=inspect), patch.object(app, 'load_config', return_value=cfg):
            app.load_batch({'source': 'ftp'}, [Job('TAT', 2026, n) for n in range(1, 5)])
        self.assertEqual(peak, 2)
        self.assertEqual(len(app.STATE['rows']), 4)
        self.assertEqual(sum(bool(r['error']) for r in app.STATE['rows']), 1)

    def test_local_batch_selective_csv_and_tsv_match(self):
        fixture = app.ROOT / 'input/tat0426.dat'
        if not fixture.exists():
            self.skipTest('Place tat0426.dat in input to run the real-data integration test.')
        app.load_batch({'source': 'local'}, [str(fixture)])
        rows = app.STATE['rows']
        self.assertEqual(rows[0]['error'], '')
        self.assertIn('0100', rows[0]['records'])
        self.assertNotIn('4000', rows[0]['records'])
        run = app.safe_path(self.output, app.STATE['run'])
        status = JobStatus(job=rows[0]['id'], dat_path=str(app.safe_path(self.output, rows[0]['dat'])))
        generated, _ = generate_data_exports_for_status(status, run)
        source = next(p for p in generated if '_LR0100_' in p.name)
        before = source.stat().st_mtime_ns
        generate_data_exports_for_status(status, run)
        self.assertEqual(before, source.stat().st_mtime_ns, 'Unchanged CSVs must be cached')
        for fmt in ('csv', 'tsv'):
            app.export_batch({'records': ['0100'], 'format': fmt}, rows)
            with zipfile.ZipFile(app.safe_path(self.output, app.STATE['archive'])) as z:
                tables = [n for n in z.namelist() if n.endswith('.' + fmt)]
                self.assertEqual(len(tables), 1)
                self.assertIn('_LR0100_', tables[0])
                table = list(csv.reader(io.StringIO(z.read(tables[0]).decode()), delimiter=',' if fmt == 'csv' else '\t'))
                with source.open(newline='', encoding='utf-8') as f:
                    self.assertEqual(table, list(csv.reader(f)))
                self.assertFalse(json.loads(z.read('manifest.json'))['failures'])
        # The real paired radiation records must form one table in both formats.
        for fmt in ('csv', 'tsv'):
            app.export_batch({'records': ['0100', '0300'], 'format': fmt}, rows)
            with zipfile.ZipFile(app.safe_path(self.output, app.STATE['archive'])) as z:
                tables = [n for n in z.namelist() if n.endswith('.' + fmt)]
                self.assertEqual(len(tables), 1)
                self.assertIn('_LR0100+0300_', tables[0])
                combined = list(csv.DictReader(io.StringIO(z.read(tables[0]).decode()), delimiter=',' if fmt == 'csv' else '\t'))
                self.assertEqual(len(combined), 43200)
                for original in (p for p in generated if '_LR0100_' in p.name or '_LR0300_' in p.name):
                    with original.open(newline='', encoding='utf-8') as f:
                        expected = list(csv.DictReader(f))
                    self.assertEqual([{k: r[k] for k in expected[0]} for r in combined], expected)

    def test_ftps_control_encrypts_login_without_data_tls(self):
        from unittest.mock import MagicMock
        from scripts import bsrn_download_check as download
        cfg = configparser.ConfigParser()
        cfg['ftp'] = {'protocol': 'ftps-control', 'host': 'example.test', 'user': 'test', 'password': 'test'}
        ftp = MagicMock()
        ftp.__enter__.return_value = ftp
        ftp.retrbinary.side_effect = lambda command, write: write(b'public-file')
        with patch.object(download.ftplib, 'FTP_TLS', return_value=ftp) as secure, patch.object(download.ftplib, 'FTP') as plain:
            output = download.download_job(Job('CAB', 2026, 5), cfg, self.output)
        secure.assert_called_once()
        self.assertTrue(secure.call_args.kwargs['context'].check_hostname)
        ftp.login.assert_called_once()
        ftp.prot_p.assert_not_called()
        plain.assert_not_called()
        self.assertEqual(output.read_bytes(), b'public-file')

    def test_no_curator_entrypoints(self):
        import scripts.bsrn_download_check as core
        for name in ('refresh_reference_ids', 'load_reference_id_cache', 'extract_metadata', 'validate_metadata_ids', 'write_run_index'):
            self.assertFalse(hasattr(core, name), name)
        self.assertFalse((app.ROOT / 'scripts/bsrn_import_files.py').exists())
        self.assertFalse((app.ROOT / 'tools/create-importfiles').exists())

    def test_http_protects_config_and_rejects_curator_actions(self):
        server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def request(method, path, headers=None, body=None):
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port)
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            result = response.status, response.read()
            conn.close()
            return result
        try:
            self.assertEqual(request('GET', '/')[0], 200)
            self.assertEqual(request('GET', '/api/state', {'Host': 'evil.example'})[0], 403)
            self.assertEqual(request('GET', '/files/runs/../../config/bsrn_workflow.ini')[0], 404)
            self.assertEqual(request('POST', '/api/load', body='{}')[0], 403)
            self.assertEqual(request('POST', '/generate-import-files', {'X-CSRF-Token': app.TOKEN}, '{}')[0], 404)
            cfg = json.loads(request('GET', '/api/config')[1])
            self.assertNotIn('password', cfg)
            self.assertNotIn('user', cfg)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

if __name__ == '__main__':
    unittest.main()
