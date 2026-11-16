#!/usr/bin/env python3
"""Start or reuse the local BSRN dashboard server, then open the dashboard."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import shlex
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Iterable

try:
    from scripts.bsrn_runtime import source_version
except ModuleNotFoundError:
    from bsrn_runtime import source_version


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_SCRIPT = PROJECT_ROOT / "scripts" / "bsrn_dashboard_server.py"
LOG_PATH = PROJECT_ROOT / "output" / "logs" / "dashboard_launcher_server.log"
REQUIREMENTS = PROJECT_ROOT / "requirements.txt"
VENV_DIR = PROJECT_ROOT / ".venv"
VENV_MARKER = VENV_DIR / ".bsrn-requirements-sha256"
MIN_PYTHON = (3, 10)


def venv_python() -> Path:
    return VENV_DIR / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def ensure_environment() -> str:
    """Return the Python that runs the server, installing requirements into .venv when needed.

    A private virtual environment keeps the dashboard independent of system or
    distribution packages (apt, conda, ...), which may be outdated or repackaged.
    An existing .packages directory (legacy local setup) is used unchanged.
    """
    if (PROJECT_ROOT / ".packages").is_dir():
        return sys.executable
    if sys.version_info < MIN_PYTHON:
        raise RuntimeError(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer is required; "
                           f"this is Python {sys.version.split()[0]}.")
    if not REQUIREMENTS.is_file():
        raise RuntimeError(f"Missing {REQUIREMENTS}. Restore it from the repository.")
    wanted = hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()
    python = venv_python()
    if python.is_file() and VENV_MARKER.is_file() and VENV_MARKER.read_text(encoding="utf-8").strip() == wanted:
        return str(python)
    has_pip = python.is_file() and subprocess.run(
        [str(python), "-m", "pip", "--version"], capture_output=True).returncode == 0
    if not has_pip:
        print(f"Creating the dashboard's Python environment in {VENV_DIR} ...", flush=True)
        # --clear only empties a missing or unusable .venv (no working pip).
        created = subprocess.run([sys.executable, "-m", "venv", "--clear", str(VENV_DIR)])
        if created.returncode != 0:
            hint = (" On Debian/Ubuntu, run 'sudo apt install python3-venv' first."
                    if sys.platform.startswith("linux") else "")
            raise RuntimeError("Could not create the Python environment." + hint)
    print("Installing the required Python packages (first start or after an update; needs internet) ...", flush=True)
    installed = subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check",
                                "-r", str(REQUIREMENTS)], cwd=PROJECT_ROOT)
    if installed.returncode != 0:
        raise RuntimeError("Installing the required packages failed. Check the internet connection "
                           "and the pip messages above, then start the dashboard again.")
    VENV_MARKER.write_text(wanted + "\n", encoding="utf-8")
    return str(python)


def api_request(host, port, path, *, token=None):
    conn = http.client.HTTPConnection(host, port, timeout=5)
    try:
        headers = {'Content-Type': 'application/json', 'X-CSRF-Token': token} if token else {}
        conn.request('POST' if token else 'GET', path, body='{}' if token else None, headers=headers)
        response = conn.getresponse()
        data = json.loads(response.read())
        if response.status != 200:
            raise RuntimeError(data.get('error', 'Dashboard request failed.'))
        return data
    finally:
        conn.close()


def legacy_process_matches(process):
    """Never stop another Python server or another dashboard checkout."""
    if process.get('Name', '').lower() not in ('python.exe', 'pythonw.exe'):
        return False
    arguments = shlex.split(process.get('CommandLine') or '', posix=False)
    return any(Path(arg.strip('"')).is_absolute() and
               Path(arg.strip('"')).resolve() == SERVER_SCRIPT.resolve() for arg in arguments[1:])


def stop_legacy_server(host, port):
    if sys.platform != 'win32' or host != '127.0.0.1':
        raise RuntimeError('Stop the existing dashboard server, then run the launcher again.')
    command = (
        f"$ids = @(Get-NetTCPConnection -LocalPort {int(port)} -State Listen -ErrorAction Stop | "
        "Select-Object -ExpandProperty OwningProcess -Unique); "
        "@(foreach ($serverId in $ids) { Get-CimInstance Win32_Process -Filter \"ProcessId=$serverId\" }) | "
        "Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress"
    )
    result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', command],
                            capture_output=True, text=True, check=True,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    processes = json.loads(result.stdout)
    if isinstance(processes, dict):
        processes = [processes]
    if len(processes) != 1 or not legacy_process_matches(processes[0]):
        raise RuntimeError('The server on this port could not be verified as this dashboard. Stop it manually before relaunching.')
    if api_request(host, port, '/api/state').get('busy'):
        raise RuntimeError('A batch is running. Wait until it finishes, then run the launcher again.')
    process = processes[0]
    # Recheck the command line immediately before stopping the verified legacy process.
    expected = process['CommandLine'].replace("'", "''")
    command = (f"$p = Get-CimInstance Win32_Process -Filter 'ProcessId={int(process['ProcessId'])}'; "
               f"if ($p.CommandLine -ceq '{expected}') {{ Stop-Process -Id $p.ProcessId -ErrorAction Stop }} "
               "else { throw 'Dashboard process changed; restart aborted.' }")
    subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', command],
                   capture_output=True, text=True, check=True,
                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def ensure_current_server(args):
    if not dashboard_responds(args.host, args.port):
        return False
    config = api_request(args.host, args.port, '/api/config')
    if config.get('server_version') == source_version(PROJECT_ROOT):
        return True
    if api_request(args.host, args.port, '/api/state').get('busy'):
        raise RuntimeError('A batch is running. Wait until it finishes, then run the launcher again to apply the update.')
    print('Dashboard update detected. Restarting the idle server; saved results are retained.')
    if config.get('api_version'):
        api_request(args.host, args.port, '/api/shutdown', token=config['token'])
    else:
        stop_legacy_server(args.host, args.port)
    deadline = time.monotonic() + args.timeout
    while dashboard_responds(args.host, args.port):
        if time.monotonic() >= deadline:
            raise RuntimeError('The old dashboard server did not stop. No replacement was started.')
        time.sleep(0.1)
    return False


def dashboard_responds(host: str, port: int) -> bool:
    try:
        conn = http.client.HTTPConnection(host, port, timeout=1.0)
        conn.request("GET", "/")
        response = conn.getresponse()
        body = response.read(4096).decode("utf-8", errors="ignore")
        return response.status == 200 and "BSRN User Dashboard" in body
    except OSError:
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def start_server(host: str, port: int, python: str = sys.executable) -> subprocess.Popen:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_handle = LOG_PATH.open("a", encoding="utf-8", errors="replace")
    log_handle.write(f"\n--- starting dashboard server on {host}:{port} ---\n")
    log_handle.flush()
    creationflags = 0
    if sys.platform.startswith("win"):
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    return subprocess.Popen(
        [python, str(SERVER_SCRIPT), "--host", host, "--port", str(port)],
        cwd=PROJECT_ROOT,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
        close_fds=True,
    )


def wait_for_server(host: str, port: int, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if dashboard_responds(host, port):
            return True
        time.sleep(0.25)
    return False


def launch_dashboard(args: argparse.Namespace) -> int:
    url = f"http://{args.host}:{args.port}/"
    try:
        if not ensure_current_server(args):
            python = sys.executable if args.no_venv else ensure_environment()
            start_server(args.host, args.port, python)
            if not wait_for_server(args.host, args.port, args.timeout):
                raise RuntimeError(f"Could not start BSRN dashboard at {url}. See {LOG_PATH}.")
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not args.no_open:
        webbrowser.open(url)
    print(f"BSRN dashboard: {url}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8766, type=int)
    parser.add_argument("--timeout", default=12.0, type=float)
    parser.add_argument("--no-open", action="store_true", help="Start/reuse the server but do not open a browser")
    parser.add_argument("--no-venv", action="store_true",
                        help="Run the server with this Python and its installed packages instead of the project's .venv")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    return launch_dashboard(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
