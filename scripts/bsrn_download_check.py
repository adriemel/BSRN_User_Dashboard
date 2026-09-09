# Scientific helpers adapted from BSRN_Dashboard.
from __future__ import annotations
import argparse
import calendar
import configparser
import ftplib
import os
import re
import ssl
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]

@dataclass(frozen=True)
class Job:
    station: str
    year: int
    month: int

    @property
    def base(self) -> str:
        return f'{self.station.lower()}{self.month:02d}{self.year % 100:02d}'

    @property
    def gz_name(self) -> str:
        return f'{self.base}.dat.gz'

    @property
    def dat_name(self) -> str:
        return f'{self.base}.dat'

    @property
    def label(self) -> str:
        return f'{self.station.upper()}_{self.year}-{self.month:02d}'

@dataclass
class JobStatus:
    job: str
    dat_path: str | None = None
    minute_completeness: dict = field(default_factory=dict)

class WorkflowError(Exception):
    pass

class RemoteFileUnavailable(WorkflowError):
    """The transfer server explicitly reported a missing remote file."""
    pass


def load_config(path: Path) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    if path.exists():
        cfg.read(path, encoding='utf-8')
    return cfg

def parse_job_code(code: str) -> Job:
    name = Path(code).name.lower()
    if name.endswith('.dat.gz'):
        name = name[:-7]
    elif name.endswith('.dat'):
        name = name[:-4]
    if len(name) != 7:
        raise argparse.ArgumentTypeError(f'Invalid BSRN job/file code: {code}')
    station = name[:3].upper()
    try:
        month = int(name[3:5])
        yy = int(name[5:7])
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f'Invalid BSRN job/file code: {code}') from exc
    year = 1900 + yy if yy >= 92 else 2000 + yy
    return Job(station=station, year=year, month=month)

def download_job(job: Job, cfg: configparser.ConfigParser, download_dir: Path) -> Path:
    download_dir.mkdir(parents=True, exist_ok=True)
    host = cfg.get('ftp', 'host', fallback='ftp.bsrn.awi.de')
    user = os.environ.get('BSRN_FTP_USER') or cfg.get('ftp', 'user', fallback='anonymous')
    password = os.environ.get('BSRN_FTP_PASSWORD') or cfg.get('ftp', 'password', fallback='anonymous@')
    timeout = cfg.getint('ftp', 'timeout_seconds', fallback=60)
    protocol = cfg.get('ftp', 'protocol', fallback='ftps').strip().lower()
    remote_dir = cfg.get('ftp', 'remote_root', fallback='/').rstrip('/')
    remote_path = f'{remote_dir}/{job.station.lower()}/{job.gz_name}' if remote_dir else f'/{job.station.lower()}/{job.gz_name}'
    local_path = download_dir / job.gz_name
    if protocol in {'ftps', 'ftp_tls', 'ftpes'}:
        curl = shutil.which('curl')
        if curl:
            url = f'ftp://{host}{remote_path}'
            command = [curl, '--fail', '--silent', '--show-error', '--location', '--ssl-reqd', '--connect-timeout', str(timeout), '--max-time', str(timeout), '--config', '-', '--output', str(local_path), url]
            if os.name == 'nt':
                command.insert(4, '--ssl-no-revoke')
            credential_blob = f'{user}:{password}'.replace('\\', '\\\\').replace('"', '\\"')
            proc = subprocess.run(command, text=True, capture_output=True, input=f'user = "{credential_blob}"\n', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if proc.returncode != 0:
                if local_path.exists():
                    local_path.unlink()
                if proc.returncode == 78:
                    raise RemoteFileUnavailable(f'{job.gz_name}: remote file unavailable.')
                raise WorkflowError(f'FTPS download failed for {job.gz_name}: {proc.stderr.strip() or proc.stdout.strip()}')
            return local_path
        ftp_class = ftplib.FTP_TLS
        ftp_kwargs = {'context': ssl.create_default_context()}
    elif protocol == 'ftps-control':
        # Encrypt authentication and control; transfer public data without TLS.
        ftp_class = ftplib.FTP_TLS
        ftp_kwargs = {'context': ssl.create_default_context()}
    elif protocol == 'ftp':
        ftp_class = ftplib.FTP
        ftp_kwargs = {}
    else:
        raise WorkflowError(f"Unsupported FTP protocol {protocol!r}; use 'ftps', 'ftps-control' or 'ftp'.")
    with ftp_class(host, timeout=timeout, **ftp_kwargs) as ftp:
        ftp.login(user=user, passwd=password)
        if protocol in {'ftps', 'ftp_tls', 'ftpes'}:
            ftp.prot_p()
        with local_path.open('wb') as handle:
            try:
                ftp.retrbinary(f'RETR {remote_path}', handle.write)
            except ftplib.error_perm as exc:
                if str(exc).startswith('550') and any(message in str(exc).lower() for message in ('no such file', 'not found', 'does not exist')):
                    raise RemoteFileUnavailable(f'{job.gz_name}: remote file unavailable.') from exc
                raise
    return local_path
_DAT_TEXT_CACHE: dict[str, tuple[int, int, str]] = {}
_DAT_TEXT_CACHE_MAX = 4

def read_dat_text(dat_path: Path) -> str:
    key = str(dat_path)
    try:
        stat = dat_path.stat()
    except OSError:
        stat = None
    if stat is not None:
        cached = _DAT_TEXT_CACHE.get(key)
        if cached is not None and cached[0] == stat.st_mtime_ns and (cached[1] == stat.st_size):
            return cached[2]
    content = dat_path.read_bytes()
    text = None
    for encoding in ('utf-8', 'cp1252', 'latin-1'):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = content.decode('latin-1', errors='replace')
    if stat is not None:
        if len(_DAT_TEXT_CACHE) >= _DAT_TEXT_CACHE_MAX:
            _DAT_TEXT_CACHE.pop(next(iter(_DAT_TEXT_CACHE)))
        _DAT_TEXT_CACHE[key] = (stat.st_mtime_ns, stat.st_size, text)
    return text

def dat_blocks(lines: list[str]) -> dict[str, list[str]]:
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(('*C', '*U')) and len(stripped) >= 6 and stripped[2:6].isdigit():
            current = stripped[2:6]
            blocks.setdefault(current, [])
            continue
        if current is not None:
            blocks[current].append(line)
    return blocks

def attach_minute_completeness(status: JobStatus) -> None:
    """Store non-blocking LR0100/LR0300 monthly minute coverage details."""
    if not status.dat_path:
        status.minute_completeness = {}
        return
    try:
        year, month = parse_status_year_month(status.job)
        dat_path = workflow_path(status.dat_path)
        blocks = dat_blocks(read_dat_text(dat_path).splitlines())
        expected = calendar.monthrange(year, month)[1] * 24 * 60
        records: dict[str, object] = {'LR0100': minute_record_completeness(blocks.get('0100') or [], year, month, expected, paired_lines=True)}
        if '0300' in blocks:
            records['LR0300'] = minute_record_completeness(blocks.get('0300') or [], year, month, expected, paired_lines=False)
        else:
            records['LR0300'] = {'status': 'not_available', 'expected': expected, 'complete': 0, 'missing': expected, 'duplicate': 0, 'invalid': 0, 'present': False}
        status.minute_completeness = {'year': year, 'month': month, 'expected_minutes': expected, 'records': records}
    except Exception as exc:
        status.minute_completeness = {'status': 'error', 'error': str(exc)}

def parse_status_year_month(job_label: str) -> tuple[int, int]:
    match = re.fullmatch('[A-Z0-9]{3}_(\\d{4})-(\\d{2})', job_label)
    if not match:
        raise WorkflowError(f'Cannot parse station month/year from status job label: {job_label}')
    return (int(match.group(1)), int(match.group(2)))

def minute_record_completeness(lines: list[str], year: int, month: int, expected: int, paired_lines: bool) -> dict[str, object]:
    minutes, invalid = minute_offsets_from_record(lines, year, month, paired_lines=paired_lines)
    unique = set(minutes)
    duplicate = max(0, len(minutes) - len(unique))
    missing = max(0, expected - len(unique))
    status = 'ok' if missing == 0 and duplicate == 0 and (invalid == 0) else 'warning'
    return {'status': status, 'expected': expected, 'complete': len(unique), 'missing': missing, 'duplicate': duplicate, 'invalid': invalid, 'present': bool(lines)}

def parse_int(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None

def minute_offsets_from_record(lines: list[str], year: int, month: int, paired_lines: bool) -> tuple[list[int], int]:
    days_in_month = calendar.monthrange(year, month)[1]
    clean_lines = [line.strip() for line in lines if line.strip()]
    step = 2 if paired_lines else 1
    offsets: list[int] = []
    invalid = 0
    for index in range(0, len(clean_lines), step):
        parts = clean_lines[index].split()
        if len(parts) < 2:
            invalid += 1
            continue
        day = parse_int(parts[0])
        minute = parse_int(parts[1])
        if day is None or minute is None or day < 1 or (day > days_in_month) or (minute < 0) or (minute > 1439):
            invalid += 1
            continue
        offsets.append((day - 1) * 1440 + minute)
    if paired_lines and len(clean_lines) % 2:
        invalid += 1
    return (offsets, invalid)

def run_python_format_check(dat_path: Path, reports_dir: Path) -> tuple[bool, Path, str]:
    """Python-native port of the legacy BSRN f_check gate used by normal runs."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f'{dat_path.stem}.rep'
    report_lines = ['', '**********', f'File name: {dat_path.name}', '**********', '*Python-native BSRN format checker']
    raw = dat_path.read_bytes()
    line_length_errors, missing_final_newline = check_format_line_lengths(raw)
    if missing_final_newline:
        report_lines.append("*ERROR: Missing 'new line' at the end of file.")
        report_path.write_text('\n'.join(report_lines) + '\n', encoding='utf-8')
        return (False, report_path, '\n'.join(report_lines))
    if line_length_errors:
        report_lines.extend(format_line_length_errors(line_length_errors))
        report_path.write_text('\n'.join(report_lines) + '\n', encoding='utf-8')
        return (False, report_path, '\n'.join(report_lines))
    report_lines.append('*Check for line length.......... OK')
    text = read_dat_text(dat_path)
    lines = text.splitlines()
    illegal_errors = check_format_illegal_characters(lines)
    if illegal_errors:
        report_lines.extend(format_illegal_character_errors(illegal_errors))
        report_path.write_text('\n'.join(report_lines) + '\n', encoding='utf-8')
        return (False, report_path, '\n'.join(report_lines))
    report_lines.append('*Check for illegal characters... OK')
    format_errors = check_format_record_lines(lines)
    if format_errors:
        report_lines.extend(format_record_line_errors(format_errors))
        report_path.write_text('\n'.join(report_lines) + '\n', encoding='utf-8')
        return (False, report_path, '\n'.join(report_lines))
    report_lines.append('*Check for line format.......... OK')
    report_path.write_text('\n'.join(report_lines) + '\n', encoding='utf-8')
    return (True, report_path, '\n'.join(report_lines))

def check_format_line_lengths(raw: bytes) -> tuple[list[tuple[int, str]], bool]:
    if raw and (not raw.endswith((b'\n', b'\r'))):
        return ([], True)
    errors: list[tuple[int, str]] = []
    for line_no, line in enumerate(raw.splitlines(keepends=True), start=1):
        content = line[:-2] if line.endswith(b'\r\n') else line[:-1] if line.endswith((b'\n', b'\r')) else line
        if len(content) > 80:
            preview = content[:20].decode('latin-1', errors='replace')
            errors.append((line_no, preview))
            if len(errors) >= 5:
                break
    return (errors, False)

def format_line_length_errors(errors: list[tuple[int, str]]) -> list[str]:
    lines = ['*ERROR: A line longer than 80 characters or missing line separator.', '', '        For help the number and the first 20 characters of the line', '        causing the problem are printed below.', '        -------------------------------------------', '        | line number:  |  first 20 characters:   |', '        -------------------------------------------']
    for line_no, preview in errors:
        lines.append(f'        |   {line_no:6d}      |  {preview:.20s}   |')
        lines.append('        -------------------------------------------')
    if len(errors) >= 5:
        lines.append('        NOTE: Only first 5 wrong lines are printed.')
    return lines
_ILLEGAL_NUMERIC_RE = re.compile('[^ +\\-.0-9]')
_ILLEGAL_PRINTABLE_RE = re.compile('[^\\x20-\\x7e]')
_ILLEGAL_PRINTABLE_TAB_RE = re.compile('[^\\x20-\\x7e\\t]')

def check_format_illegal_characters(lines: list[str]) -> list[tuple[int, int, int, str]]:
    errors: list[tuple[int, int, int, str]] = []
    rec_num = 0
    for line_no, line in enumerate(lines, start=1):
        if line.startswith('*'):
            match = re.match('^\\*[CU](\\d{4})', line.strip())
            if match:
                rec_num = int(match.group(1))
                continue
            errors.append((rec_num, line_no, 1, line[:1] or ' '))
            break
        if rec_num == 0:
            errors.append((rec_num, line_no, 1, line[:1] or ' '))
            break
        if rec_num > 99 and rec_num != 1000:
            scanner = _ILLEGAL_NUMERIC_RE
        elif rec_num == 3:
            scanner = _ILLEGAL_PRINTABLE_TAB_RE
        else:
            scanner = _ILLEGAL_PRINTABLE_RE
        hit = scanner.search(line)
        if hit is not None:
            errors.append((rec_num, line_no, hit.start() + 1, hit.group(0)))
        if len(errors) >= 5:
            break
    return errors

def format_illegal_character_errors(errors: list[tuple[int, int, int, str]]) -> list[str]:
    lines = ['*ERROR: An illegal character occurred.', '', '        Allowed ASCII characters:', '           - in logical records 1000 and less than 100: printable ASCII characters', '             and tabulator in logical record 3.', "           - in all other logical records: space, '+', '-', '.', and digits.", '', '        --------------------------------------------------------------------', '        |  log. record:  | line number:  |  position:  |  wrong character  |', '        --------------------------------------------------------------------']
    for rec_num, line_no, pos, char in errors:
        printable = char if ' ' <= char <= '~' else ' '
        lines.append(f'        |      {rec_num:4d}      |   {line_no:6d}      |      {pos:2d}     |   {printable}   |  {ord(char):02X} (hex) |')
        lines.append('        --------------------------------------------------------------------')
    if len(errors) >= 5:
        lines.append('        NOTE: Only first 5 lines with illegal characters are printed.')
    return lines

def check_format_record_lines(lines: list[str]) -> list[str]:
    errors: list[str] = []
    rec_num = 0
    index_in_record = 0
    prev_day = prev_min = 0
    prev_seq = prev_height = 0
    band4 = False
    for line_no, line in enumerate(lines, start=1):
        if line.startswith('*'):
            match = re.match('^\\*[CU](\\d{4})$', line.strip())
            if not match:
                errors.append(f'Line {line_no}: incorrect record marker.')
                break
            rec_num = int(match.group(1))
            index_in_record = 0
            prev_day = prev_min = 0
            prev_seq = prev_height = 0
            band4 = False
            continue
        if rec_num in {3, 1000}:
            continue
        if line == '':
            errors.append(f'Log. record {rec_num}, line {line_no}: empty line.')
            break
        values = line.split()
        record_error = validate_format_line_tokens(rec_num, index_in_record, values, band4)
        if record_error:
            errors.append(f'Log. record {rec_num}, line {line_no}: {record_error}')
            break
        day_min = data_record_day_min(rec_num, index_in_record, values)
        if day_min is not None:
            day, minute = day_min
            if rec_num == 1100:
                seq = int(values[2])
                height = int(values[4])
                if (prev_seq >= seq or prev_height >= height) and (prev_day, prev_min) == (day, minute):
                    errors.append(f'Log. record {rec_num}, line {line_no}: wrong seq. no. or height; both have to increase within one time.')
                    break
                if prev_day > day or (prev_day == day and prev_min > minute):
                    errors.append(f'Log. record {rec_num}, line {line_no}: time of measurement cannot decrease.')
                    break
                prev_seq, prev_height = (seq, height)
            elif prev_day > day or (prev_day == day and prev_min >= minute):
                errors.append(f'Log. record {rec_num}, line {line_no}: time of measurement has to increase.')
                break
            prev_day, prev_min = (day, minute)
        index_in_record, band4 = next_format_line_index(rec_num, index_in_record, values, band4)
    return errors[:5]

def validate_format_line_tokens(rec_num: int, index: int, values: list[str], band4: bool) -> str | None:
    expected = expected_format_token_count(rec_num, index, values, band4)
    if expected is None:
        return 'incorrect record number.'
    if expected == -1:
        return None
    if len(values) != expected:
        return f'expected {expected} fields, found {len(values)}.'
    numeric_records = {1, 9, 100, 200, 300, 400, 500, 1100, 1200, 1300, 1500, 3010, 3025, 3030, 3300, 4000, 4010, 4030}
    if rec_num in numeric_records:
        for value in values:
            if not re.fullmatch('[+-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)', value):
                return f'numeric field expected, found {value!r}.'
    return None

def expected_format_token_count(rec_num: int, index: int, values: list[str], band4: bool) -> int | None:
    if rec_num == 1:
        return 4 if index == 0 else 8
    if rec_num == 2:
        return [3, -1, -1, -1][index % 4]
    if rec_num == 4:
        return [3, 2, -1, -1, -1, 4, 3, 22][index % 8]
    if rec_num == 5:
        return [4, -1, -1][index % 3]
    if rec_num == 6:
        return [4, -1, -1][index % 3]
    if rec_num == 7:
        return 3 if index == 0 else 6 if index == 6 else -1
    if rec_num == 8:
        if index == 0:
            return 4
        if index == 1:
            return -1
        if index == 2:
            return -1
        if index == 3:
            return 12 if len(values) > 10 else 10
        if index == 4:
            return -1
        if index in {5, 6, 7} or (band4 and index == 8):
            return -1
        if index in {8, 9}:
            return -1
        return None
    if rec_num == 9:
        return 6
    if rec_num == 100:
        return [10, 11][index % 2]
    if rec_num in {200, 300}:
        return 14
    if rec_num == 400:
        return [14, 12, 12][index % 3]
    if rec_num == 500:
        return [10, 12][index % 2]
    if rec_num == 1100:
        return 10
    if rec_num == 1200:
        return 3
    if rec_num == 1300:
        return 8
    if rec_num == 1500:
        return 8
    if rec_num in {3010, 3025, 3030, 3300}:
        return [10, 10][index % 2]
    if rec_num in {4000, 4010, 4030}:
        return 12
    return None

def data_record_day_min(rec_num: int, index: int, values: list[str]) -> tuple[int, int] | None:
    if rec_num in {100, 400, 500, 3010, 3025, 3030, 3300} and index % (2 if rec_num != 400 else 3) == 0:
        return (int(values[0]), int(values[1]))
    if rec_num in {200, 300, 1100, 1200, 1300, 1500, 4000, 4010, 4030}:
        return (int(values[0]), int(values[1]))
    return None

def next_format_line_index(rec_num: int, index: int, values: list[str], band4: bool) -> tuple[int, bool]:
    if rec_num in {1, 9, 200, 300, 1100, 1200, 1300, 1500, 4000, 4010, 4030}:
        return (1 if rec_num == 1 else 0, band4)
    if rec_num in {2, 5, 6, 100, 400, 500, 3010, 3025, 3030, 3300}:
        cycle = {2: 4, 5: 3, 6: 3, 100: 2, 400: 3, 500: 2, 3010: 2, 3025: 2, 3030: 2, 3300: 2}[rec_num]
        return ((index + 1) % cycle, band4)
    if rec_num == 4:
        return (7 if index >= 7 else index + 1, band4)
    if rec_num == 7:
        return (0 if index == 6 else index + 1, band4)
    if rec_num == 8:
        if index == 3:
            return (4, len(values) > 10)
        if index == 7 and band4:
            return (8, False)
        return ((index + 1) % 10, band4)
    return (index + 1, band4)

def format_record_line_errors(errors: list[str]) -> list[str]:
    lines = ['*ERROR: Incorrect format.', '', '        For each logical record the line number from the beginning of', '        the file and the first wrong-format message are printed below.', '']
    lines.extend((f'        +{error}' for error in errors))
    return lines

def workflow_path(value: str | Path | None) -> Path:
    path = Path(value or '')
    return path if path.is_absolute() else PROJECT_ROOT / path
