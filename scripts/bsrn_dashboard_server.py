"""Local BSRN user workflow: acquisition, scientific QC and readable exports."""
from __future__ import annotations

import argparse
import copy
import csv
import gzip
import hashlib
import json
import mimetypes
import os
import re
import secrets
import shutil
import sys
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if (ROOT / '.packages').is_dir():
    sys.path.insert(0, str(ROOT / '.packages'))
sys.path.insert(0, str(ROOT / 'tools/qc-graphs'))
os.environ.setdefault('MPLCONFIGDIR', str(ROOT / 'output/.matplotlib'))
from scripts.bsrn_download_check import (Job, JobStatus, attach_minute_completeness,
    dat_blocks, download_job, load_config, read_dat_text, run_python_format_check)
from scripts.bsrn_data_exports import EXPORT_RECORDS, generate_data_exports_for_status

OUTPUT = ROOT / 'output'
TOKEN = secrets.token_urlsafe(32)
LOCK = threading.RLock()
STATE = {'busy': False, 'action': '', 'done': 0, 'total': 0, 'rows': [], 'message': '', 'run': '', 'archive': None}
LABELS = {'0100': 'Basic radiation & meteorology', '0300': 'Upward radiation',
    '0500': 'Ultraviolet', '1000': 'SYNOP', '1100': 'Radiosonde', '1200': 'Ozone',
    '1300': 'Expanded measurements', '3010': 'Radiation at 10 m', '3030': 'Radiation at 30 m'}

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def save():
    OUTPUT.mkdir(exist_ok=True)
    temporary = OUTPUT / 'state.tmp'
    temporary.write_text(json.dumps(STATE, indent=2), encoding='utf-8')
    os.replace(temporary, OUTPUT / 'state.json')

def update(**values):
    with LOCK:
        STATE.update(values)
        save()

def snapshot():
    with LOCK:
        return copy.deepcopy(STATE)

def safe_path(base, relative):
    if not isinstance(relative, str):
        raise ValueError('Invalid file path')
    path = (base / relative).resolve()
    if not path.is_relative_to(base.resolve()):
        raise ValueError('File path is outside the permitted folder')
    return path

def stations():
    return json.loads((ROOT / 'config/stations.json').read_text(encoding='utf-8'))

def validate_load(data):
    source = data.get('source')
    if source == 'local':
        names = data.get('files', [])
        if not isinstance(names, list) or not names:
            raise ValueError('Select at least one DAT file from the input folder.')
        paths = list(dict.fromkeys(str(safe_path(ROOT / 'input', name)) for name in names))
        if any(not Path(p).is_file() or Path(p).suffix.lower() != '.dat' for p in paths):
            raise ValueError('Only existing .dat files in the input folder can be loaded.')
        return paths
    if source != 'ftp':
        raise ValueError('Choose FTP or local input.')
    selected = data.get('stations', [])
    known = {s['code'] for s in stations()}
    if not isinstance(selected, list) or not selected or any(s not in known for s in selected):
        raise ValueError('Select one or more stations.')
    try:
        start, end = (date.fromisoformat(data[k] + '-01') for k in ('start', 'end'))
    except (ValueError, KeyError, TypeError):
        raise ValueError('Choose valid start and end months.')
    if start > end or start.year < 1992 or end > date.today().replace(day=1):
        raise ValueError('Choose a date range from 1992 through the current month.')
    jobs = []
    month = start
    while month <= end:
        jobs.extend(Job(s, month.year, month.month) for s in dict.fromkeys(selected))
        month = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
    if len(jobs) > 5000:
        raise ValueError('Select at most 5,000 station-months per batch.')
    return jobs

def fetch(job, cfg, reuse):
    cache = OUTPUT / 'download_cache'
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / job.dat_name
    checksum = cache / (job.dat_name + '.sha256')
    if reuse and target.is_file() and checksum.is_file() and checksum.read_text() == digest(target):
        return target, True
    error = None
    for attempt in range(3):
        try:
            gz = download_job(job, cfg, cache)
            temporary = cache / (job.dat_name + '.partial')
            with gzip.open(gz, 'rb') as src, temporary.open('wb') as dest:
                shutil.copyfileobj(src, dest)
            os.replace(temporary, target)
            checksum.write_text(digest(target))
            gz.unlink(missing_ok=True)
            return target, False
        except Exception as exc:
            error = exc
            if attempt < 2:
                time.sleep(attempt + 1)
    raise ValueError(f'{job.base}: download failed after 3 attempts. {error}')

def inspect_file(path, run, source, reused=False):
    blocks = dat_blocks(read_dat_text(path).splitlines())
    first = (blocks.get('0001') or [''])[0]
    try:
        sid, month, year = int(first[:3]), int(first[4:6]), int(first[7:11])
        date(year, month, 1)
    except (ValueError, IndexError):
        raise ValueError(f'{path.name}: missing or invalid station/date in LR0001.')
    candidates = [s['code'] for s in stations() if s['id'] == sid]
    hint = path.stem[:3].upper()
    station = hint if hint in candidates else candidates[0] if candidates else hint
    if not re.fullmatch(r'[A-Z0-9]{3}', station):
        raise ValueError('Could not identify the station code.')
    job = Job(station, year, month)
    destination = run / 'dat' / job.dat_name
    if destination.exists():
        raise ValueError(f'{job.label}: another file for this station-month is already in this batch.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)
    status = JobStatus(job=job.label, dat_path=str(destination))
    attach_minute_completeness(status)
    ok, report, _ = run_python_format_check(destination, run / 'format_reports')
    present = sorted(set(blocks) & EXPORT_RECORDS)
    unsupported = sorted(r for r in blocks if r.isdigit() and 100 <= int(r) < 4000 and r not in EXPORT_RECORDS)
    return {'id': job.label, 'dat': str(destination.relative_to(OUTPUT)), 'source': source,
        'reused': reused, 'records': present, 'unsupported': unsupported, 'format_ok': ok,
        'format_report': str(report.relative_to(OUTPUT)), 'coverage': status.minute_completeness,
        'qc': None, 'qc_error': '', 'error': '', 'warnings': []}

def load_batch(data, items):
    run_id = time.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8]
    run = OUTPUT / 'runs' / run_id
    run.mkdir(parents=True)
    update(run=str(run.relative_to(OUTPUT)), rows=[], archive=None, total=len(items), done=0)
    def collect(item, result=None, error=None):
        label = item.label if isinstance(item, Job) else Path(item).name
        try:
            if error:
                raise error
            path, reused = result if result else (Path(item), False)
            row = inspect_file(path, run, label, reused)
            if isinstance(item, Job) and row['id'] != item.label:
                raise ValueError(f'{item.label}: downloaded file identifies itself as {row["id"]}.')
        except Exception as exc:
            row = {'id': label, 'error': str(exc), 'records': [], 'qc': None, 'warnings': []}
        with LOCK:
            STATE['rows'].append(row)
            STATE['done'] += 1
            save()
    if data['source'] == 'local':
        for item in items:
            collect(item)
    else:
        cfg = load_config(ROOT / 'config/bsrn_workflow.ini')
        workers = max(1, min(4, cfg.getint('ftp', 'download_workers', fallback=3)))
        # Transfers continue while the coordinator checks completed files.
        with ThreadPoolExecutor(max_workers=workers) as pool:
            pending = {pool.submit(fetch, job, cfg, bool(data.get('reuse'))): job for job in items}
            for future in as_completed(pending):
                try:
                    result = future.result()
                except Exception as exc:
                    collect(pending[future], error=exc)
                else:
                    collect(pending[future], result=result)
    failed = sum(bool(r.get('error')) for r in STATE['rows'])
    update(message=f"Loaded {len(items) - failed} of {len(items)} files. " + (f'{failed} need attention.' if failed else 'Ready to explore or export.'))

def selected_rows(data):
    ids = data.get('jobs', [])
    if not isinstance(ids, list) or not ids:
        raise ValueError('Select at least one loaded file.')
    rows = [r for r in STATE['rows'] if r['id'] in ids and r.get('dat')]
    if not rows:
        raise ValueError('No usable files selected.')
    return rows

def qc_batch(rows):
    from scripts.bsrn_qc_continue import generate_interactive_report
    update(total=len(rows), done=0)
    for row in rows:
        try:
            path = safe_path(OUTPUT, row['dat'])
            folder = path.parent.parent / 'qc'
            folder.mkdir(exist_ok=True)
            report = generate_interactive_report(path, folder)
            with LOCK:
                row['qc'] = str(report.relative_to(OUTPUT))
                row['qc_error'] = ''
        except Exception as exc:
            with LOCK:
                row['qc_error'] = str(exc)
        with LOCK:
            STATE['done'] += 1
            save()
    failed = sum(bool(r.get('qc_error')) for r in rows)
    update(message=f'QC finished for {len(rows) - failed} of {len(rows)} files. Flags identify observations to review; they do not remove data.')

def export_batch(data, rows):
    records = set(data.get('records', []))
    if not records or not records <= EXPORT_RECORDS:
        raise ValueError('Select supported logical records.')
    fmt = data.get('format', 'csv')
    if fmt not in ('csv', 'tsv'):
        raise ValueError('Choose CSV or tab-delimited text.')
    update(total=len(rows), done=0, archive=None)
    run = safe_path(OUTPUT, STATE['run'])
    bundle = run / ('export-' + uuid.uuid4().hex[:8] + '.zip')
    manifest = {'format': fmt, 'records': sorted(records), 'files': [], 'failures': [],
        'notes': 'Original parsed values; no QC filtering. LR0001–0009 and LR4000 excluded.'}
    with zipfile.ZipFile(bundle, 'w', zipfile.ZIP_DEFLATED) as z:
        for row in rows:
            try:
                status = JobStatus(job=row['id'], dat_path=str(safe_path(OUTPUT, row['dat'])))
                files, warnings = generate_data_exports_for_status(status, run)
                chosen = [p for p in files if any('_LR' + r + '_' in p.name for r in records)]
                with LOCK:
                    row['warnings'] = warnings
                for path in chosen:
                    if fmt == 'csv':
                        z.write(path, path.name)
                    else:
                        dest = path.with_suffix('.tsv')
                        with path.open(newline='', encoding='utf-8') as src, dest.open('w', newline='', encoding='utf-8') as out:
                            csv.writer(out, delimiter='\t').writerows(csv.reader(src))
                        z.write(dest, dest.name)
                manifest['files'].append({'job': row['id'], 'source': row['source'],
                    'sha256': digest(status.dat_path), 'exported': [p.with_suffix('.' + fmt).name for p in chosen],
                    'absent_records': sorted(records - set(row['records'])), 'warnings': warnings})
            except Exception as exc:
                manifest['failures'].append({'job': row['id'], 'error': str(exc)})
            with LOCK:
                STATE['done'] += 1
                save()
        z.writestr('manifest.json', json.dumps(manifest, indent=2))
        z.writestr('README.txt', 'BSRN user data exports\nCSV: comma separated. TSV: tab separated. UTF-8 encoding.\nSeparate tables per station-month and logical record. Column headers contain units where available.\nDate/Time follows the BSRN source time convention (UTC); minute 1440 becomes the next day at 00:00.\nMissing values are empty fields. Observations are not filtered by QC flags.\nRecords absent from a source file are listed in manifest.json. Unsupported records are not exported.\n')
    count = sum(len(f['exported']) for f in manifest['files'])
    update(archive=str(bundle.relative_to(OUTPUT)), message=f"Exported {count} tables. {len(manifest['failures'])} file failures; see the included manifest.")

def start_action(action, data):
    with LOCK:
        if STATE['busy']:
            raise ValueError('A batch is already running. Please wait until it finishes.')
        if action == 'load':
            items = validate_load(data)
            work = lambda: load_batch(data, items)
        elif action == 'qc':
            rows = selected_rows(data)
            work = lambda: qc_batch(rows)
        elif action == 'export':
            rows = selected_rows(data)
            if data.get('format') not in ('csv', 'tsv') or not data.get('records') or not set(data['records']) <= EXPORT_RECORDS:
                raise ValueError('Select logical records and CSV or tab-delimited text.')
            work = lambda: export_batch(data, rows)
        else:
            raise ValueError('Unknown action')
        update(busy=True, action=action, message='', done=0, total=0)
    def runner():
        try:
            work()
        except Exception as exc:
            update(message=str(exc))
        finally:
            update(busy=False)
    threading.Thread(target=runner, daemon=True).start()

class Handler(BaseHTTPRequestHandler):
    def valid_host(self):
        return self.headers.get('Host', '') in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')

    def send(self, code, body, kind='application/json; charset=utf-8'):
        if not isinstance(body, bytes):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.valid_host():
            return self.send(403, 'Invalid host', 'text/plain')
        path = unquote(urlsplit(self.path).path)
        if path == '/api/state':
            return self.send(200, json.dumps(snapshot()))
        if path == '/api/config':
            return self.send(200, json.dumps({'token': TOKEN, 'stations': stations(), 'records': LABELS,
                'inputs': sorted(str(p.relative_to(ROOT / 'input')) for p in (ROOT / 'input').rglob('*') if p.is_file() and p.suffix.lower() == '.dat'),
                'ftp_mode': load_config(ROOT / 'config/bsrn_workflow.ini').get('ftp', 'protocol', fallback='ftps'),
                'ftp_configured': (ROOT / 'config/bsrn_workflow.ini').is_file()}))
        if path in ('/', '/app.js', '/style.css'):
            name = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}[path]
            return self.send(200, (ROOT / 'web' / name).read_bytes(), mimetypes.guess_type(name)[0] + '; charset=utf-8')
        if path.startswith('/files/'):
            try:
                target = safe_path(OUTPUT / 'runs', path[len('/files/runs/'):]) if path.startswith('/files/runs/') else None
                if not target or not target.is_file() or target.suffix not in {'.html', '.csv', '.tsv', '.zip', '.rep', '.png'}:
                    raise ValueError('Not a public artifact')
                return self.send(200, target.read_bytes(), mimetypes.guess_type(target.name)[0] or 'text/plain; charset=utf-8')
            except (ValueError, OSError):
                pass
        return self.send(404, 'Not found', 'text/plain')

    def do_POST(self):
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 1024 * 1024:
                raise ValueError('Invalid request size')
            self.connection.settimeout(15)
            body = self.rfile.read(size)
        except (ValueError, OSError) as exc:
            return self.send(400, json.dumps({'error': str(exc)}))
        origin = self.headers.get('Origin')
        if not self.valid_host() or self.headers.get('X-CSRF-Token') != TOKEN or (origin and origin not in (f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}')):
            return self.send(403, json.dumps({'error': 'Invalid request origin or token.'}))
        try:
            data = json.loads(body)
            if not isinstance(data, dict):
                raise ValueError('Expected an object')
            path = urlsplit(self.path).path
            if path not in ('/api/load', '/api/qc', '/api/export'):
                return self.send(404, json.dumps({'error': 'Unknown action'}))
            start_action(path.rsplit('/', 1)[-1], data)
            self.send(202, json.dumps({'ok': True}))
        except (ValueError, TypeError, KeyError) as exc:
            self.send(400, json.dumps({'error': str(exc)}))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', choices=['127.0.0.1'], default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    if (OUTPUT / 'state.json').exists():
        STATE.update(json.loads((OUTPUT / 'state.json').read_text(encoding='utf-8')))
        if STATE['busy']:
            STATE.update(busy=False, message='The previous action was interrupted. Completed results are retained; reload with reuse enabled or retry QC/export.')
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()

if __name__ == '__main__':
    main()
