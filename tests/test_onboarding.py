import io
import json
import os
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from opendots.__main__ import main
from opendots.setup import initialize, default_config
from opendots.config import load_config


class OnboardingTests(unittest.TestCase):
    def test_no_implicit_demo_or_placeholder_goal(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); project=root/'project';project.mkdir()
            with self.assertRaisesRegex(ValueError,'workspace'): initialize(root/'config')
            with self.assertRaisesRegex(ValueError,'goal'): initialize(root/'config',project)
            self.assertFalse((root/'config').exists())
            path=initialize(root/'config',project,goal='My actual objective',heartbeat=300)
            config=load_config(path)
            self.assertEqual(config.backend,'claude')
            self.assertEqual(config.targets[0].objective,'My actual objective')
            self.assertEqual(config.targets[0].write_paths,())
            self.assertEqual(config.targets[0].relevance['mode'],'model')
            self.assertFalse(config.targets[0].recipes)
            self.assertEqual(config.schedules[0]['interval_seconds'],300)
            self.assertFalse((path.parent/'workspaces').exists())

    def test_default_config_never_selects_checkout_demo(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'XDG_CONFIG_HOME':directory}):
            self.assertEqual(default_config(),Path(directory)/'opendots/config.json')

    def test_demo_requires_explicit_flag_and_no_real_goal(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with self.assertRaises(ValueError):initialize(root/'bad',root,backend='demo',goal='Goal')
            with self.assertRaises(ValueError):initialize(root/'bad',demo=True,goal='Goal')
            config=load_config(initialize(root/'demo',demo=True))
            self.assertEqual(config.backend,'demo')
            self.assertEqual(len(config.targets),2)


class MissingConfigCliTests(unittest.TestCase):
    def _run(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch('sys.argv', argv), redirect_stdout(stdout), redirect_stderr(stderr):
            code = main()
        return code, stdout.getvalue(), stderr.getvalue()

    def _assert_setup_hint(self, code, stdout, stderr, path):
        self.assertEqual(code, 1)
        self.assertEqual(stdout, '')
        self.assertNotIn('Traceback', stderr)
        self.assertIn(f'Configuration file not found: {path}', stderr)
        self.assertIn('opendots init --workspace', stderr)
        self.assertIn('--goal', stderr)
        self.assertIn('opendots init --help', stderr)

    def test_explicit_missing_config_explains_init(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = root / 'opendots-no-config.json'
            code, stdout, stderr = self._run(['opendots', '--config', str(missing), 'doctor'])
            self._assert_setup_hint(code, stdout, stderr, missing.resolve())
            self.assertEqual(list(root.iterdir()), [])

    def test_default_missing_config_explains_init(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_home, data_home = root / 'config', root / 'data'
            config_home.mkdir(); data_home.mkdir()
            expected = (config_home / 'opendots' / 'config.json').resolve()
            with patch.dict(os.environ, {'XDG_CONFIG_HOME': str(config_home), 'XDG_DATA_HOME': str(data_home)}):
                code, stdout, stderr = self._run(['opendots', 'doctor'])
            self._assert_setup_hint(code, stdout, stderr, expected)
            self.assertEqual(list(config_home.iterdir()), [])
            self.assertEqual(list(data_home.iterdir()), [])

    def test_malformed_json_is_not_a_missing_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'config.json'
            path.write_text('{')
            code, stdout, stderr = self._run(['opendots', '--config', str(path), 'doctor'])
            self.assertEqual(code, 1)
            self.assertEqual(stdout, '')
            self.assertNotIn('Traceback', stderr)
            self.assertNotIn('Configuration file not found', stderr)
            self.assertNotIn('opendots init', stderr)
            self.assertIn('Expecting property name', stderr)
            self.assertEqual([item.name for item in root.iterdir()], ['config.json'])

    def test_other_load_failures_stay_specific(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'config.json'
            path.write_text(json.dumps({'targets': [{
                'id': 'project', 'name': 'Project', 'objective': 'Ship',
                'workspace': 'missing-workspace',
                'subscriptions': [{'types': ['input.*']}],
            }]}))
            code, stdout, stderr = self._run(['opendots', '--config', str(path), 'status'])
            self.assertEqual(code, 1)
            self.assertNotIn('Configuration file not found', stderr)
            self.assertNotIn('opendots init', stderr)
            self.assertIn('Workspace does not exist', stderr)
            self.assertFalse((root / '.opendots').exists())
            code, stdout, stderr = self._run(['opendots', '--config', directory, 'doctor'])
            self.assertEqual(code, 1)
            self.assertNotIn('Configuration file not found', stderr)
            self.assertNotIn('opendots init', stderr)
            self.assertIn('Is a directory', stderr)

    def test_existing_config_still_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / 'project'
            project.mkdir()
            path = initialize(root / 'cfg', project, goal='Keep the build green')
            code, stdout, stderr = self._run(['opendots', '--config', str(path), 'doctor'])
            self.assertNotIn('Configuration file not found', stderr)
            self.assertNotIn('Traceback', stderr)
            report = json.loads(stdout)
            configuration = next(item for item in report['checks'] if item['name'] == 'configuration')
            self.assertTrue(configuration['ok'])
            self.assertIn(str(path.resolve()), configuration['detail'])
            self.assertFalse((root / 'cfg' / 'data').exists())
            self.assertFalse((root / 'cfg' / 'workspaces').exists())
            self.assertIn(code, (0, 1))
