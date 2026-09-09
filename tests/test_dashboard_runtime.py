import argparse
import unittest
from unittest.mock import patch

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


if __name__ == '__main__':
    unittest.main()
