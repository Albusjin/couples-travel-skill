"""Release boundaries and an extracted package; no provider calls or installs."""

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_release', ROOT / 'scripts/build_release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class DistributionTests(unittest.TestCase):
    def test_release_is_deterministic_and_verifies_after_extraction(self):
        version, data, count = release.build()
        self.assertEqual(data, release.build()[1])
        with tempfile.TemporaryDirectory(prefix='travel package ') as directory:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                self.assertEqual(len(archive.namelist()), count)
                archive.extractall(directory)
            skill = Path(directory) / 'travel-planner'
            result = subprocess.run([sys.executable, str(skill / 'scripts/verify_package.py')],
                                    capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)['package_version'], version)
            (skill / 'SKILL.md').write_text('tampered', encoding='utf-8')
            result = subprocess.run([sys.executable, str(skill / 'scripts/verify_package.py')],
                                    capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 2)
            self.assertIn('SKILL.md', json.loads(result.stdout)['failed_files'])

    def test_allowlist_excludes_local_data_and_unlisted_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / 'skills/travel-planner'
            skill.mkdir(parents=True)
            (skill / 'VERSION').write_text('1.1.0')
            (skill / 'private.txt').write_text('PRIVATE FIXTURE')
            (skill / 'runtime.local.toml').write_text('PRIVATE FIXTURE')
            (root / 'release-files.json').write_text(json.dumps({'version': '1.1.0', 'files': ['VERSION']}))
            data = release.build(root)[1]
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                self.assertEqual(set(archive.namelist()), {'travel-planner/VERSION', 'travel-planner/MANIFEST.json'})

    def test_private_paths_traversal_and_credentials_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('../escape', '/absolute', 'config/runtime.local.toml', '.env', 'node_modules/a.py'):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    release.checked_file(root, name)
            (root / 'config.txt').write_text('https://example.invalid/?key=' + 'X' * 32)
            with self.assertRaises(ValueError):
                release.checked_file(root, 'config.txt')

    def test_symlinks_are_rejected_even_inside_a_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'real').mkdir()
            (root / 'real/file.txt').write_text('fixture')
            try:
                (root / 'alias').symlink_to(root / 'real', target_is_directory=True)
            except OSError:
                self.skipTest('symlink privileges unavailable')
            with self.assertRaises(ValueError):
                release.checked_file(root, 'alias/file.txt')

    def test_codex_template_starts_disabled_with_exact_routing_allowlists(self):
        config = ROOT / 'skills/travel-planner/config'
        template = tomllib.loads((config / 'mcp-codex.example.toml').read_text(encoding='utf-8'))['mcp_servers']
        routing = tomllib.loads((config / 'mcp-routing.toml').read_text(encoding='utf-8'))['services']
        self.assertEqual(set(template), set(routing))
        for name in routing:
            self.assertIs(template[name]['enabled'], False)
            self.assertEqual(set(template[name]['enabled_tools']), set(routing[name]['tools']))


if __name__ == '__main__':
    unittest.main()
