import argparse
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import bsrn_launch_dashboard as launcher


class DashboardRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.args = argparse.Namespace(host='127.0.0.1', port=8766, timeout=2, no_open=True)

    def test_current_server_is_reused(self):
        with patch.object(launcher, 'dashboard_responds', return_value=True), \
                patch.object(launcher, 'source_version', return_value='current'), \
                patch.object(launcher, 'api_request', return_value={'server_version': 'current'}) as api:
            self.assertTrue(launcher.ensure_current_server(self.args))
            api.assert_called_once_with('127.0.0.1', 8766, '/api/config')

    def test_outdated_server_is_stopped_before_replacement(self):
        with patch.object(launcher, 'dashboard_responds', side_effect=[True, False]), \
                patch.object(launcher, 'source_version', return_value='current'), \
                patch.object(launcher, 'api_request', side_effect=[
                    {'server_version': 'old', 'api_version': 1, 'token': 'test'}, {'busy': False}, {'ok': True}]) as api:
            self.assertFalse(launcher.ensure_current_server(self.args))
            self.assertEqual(api.call_args.args[2], '/api/shutdown')
            self.assertEqual(api.call_args.kwargs, {'token': 'test'})

    def test_busy_server_is_never_restarted(self):
        with patch.object(launcher, 'dashboard_responds', return_value=True), \
                patch.object(launcher, 'source_version', return_value='current'), \
                patch.object(launcher, 'api_request', side_effect=[{'server_version': 'old'}, {'busy': True}]) as api, \
                patch.object(launcher, 'stop_legacy_server') as stop:
            with self.assertRaisesRegex(RuntimeError, 'batch is running'):
                launcher.ensure_current_server(self.args)
            stop.assert_not_called()
            self.assertEqual(api.call_count, 2)

    def test_legacy_server_takes_verified_stop_path(self):
        with patch.object(launcher, 'dashboard_responds', side_effect=[True, False]), \
                patch.object(launcher, 'source_version', return_value='current'), \
                patch.object(launcher, 'api_request', side_effect=[{'token': 'old'}, {'busy': False}]), \
                patch.object(launcher, 'stop_legacy_server') as stop:
            self.assertFalse(launcher.ensure_current_server(self.args))
            stop.assert_called_once_with('127.0.0.1', 8766)

    def test_legacy_process_must_name_this_exact_server_script(self):
        self.assertTrue(launcher.legacy_process_matches({
            'Name': 'python.exe', 'CommandLine': f'python.exe "{launcher.SERVER_SCRIPT}" --port 8766'}))
        for command in ['python.exe other.py', 'python.exe bsrn_dashboard_server.py',
                        f'python.exe "{launcher.SERVER_SCRIPT}.backup"']:
            self.assertFalse(launcher.legacy_process_matches({'Name': 'python.exe', 'CommandLine': command}))


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / 'requirements.txt').write_text('numpy\n', encoding='utf-8')
        patches = patch.multiple(launcher, PROJECT_ROOT=root, REQUIREMENTS=root / 'requirements.txt',
                                 VENV_DIR=root / '.venv', VENV_MARKER=root / '.venv/.bsrn-requirements-sha256')
        patches.start()
        self.addCleanup(patches.stop)
        self.root = root

    def make_venv(self, marker):
        python = launcher.venv_python()
        python.parent.mkdir(parents=True)
        python.write_text('', encoding='utf-8')
        launcher.VENV_MARKER.write_text(marker, encoding='utf-8')
        return python

    def test_up_to_date_environment_is_reused_without_installing(self):
        digest = hashlib.sha256((self.root / 'requirements.txt').read_bytes()).hexdigest()
        python = self.make_venv(digest)
        with patch.object(launcher.subprocess, 'run') as run:
            self.assertEqual(launcher.ensure_environment(), str(python))
            run.assert_not_called()

    def test_changed_requirements_are_installed_and_recorded(self):
        python = self.make_venv('outdated')
        with patch.object(launcher.subprocess, 'run') as run:
            run.return_value.returncode = 0
            self.assertEqual(launcher.ensure_environment(), str(python))
        self.assertEqual(run.call_args.args[0][:4], [str(python), '-m', 'pip', 'install'])
        self.assertNotEqual(launcher.VENV_MARKER.read_text(encoding='utf-8').strip(), 'outdated')

    def test_failed_install_is_reported_and_not_recorded(self):
        self.make_venv('outdated')
        with patch.object(launcher.subprocess, 'run') as run:
            run.side_effect = [Mock(returncode=0), Mock(returncode=1)]  # pip present, install fails
            with self.assertRaisesRegex(RuntimeError, 'Installing the required packages failed'):
                launcher.ensure_environment()
        self.assertEqual(launcher.VENV_MARKER.read_text(encoding='utf-8'), 'outdated')

    def test_legacy_packages_directory_keeps_calling_python(self):
        (self.root / '.packages').mkdir()
        with patch.object(launcher.subprocess, 'run') as run:
            self.assertEqual(launcher.ensure_environment(), sys.executable)
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
