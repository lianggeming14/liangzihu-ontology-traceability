"""Required static assets remain mandatory; a runtime network fallback is optional."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/check_repository_layout.py'
spec = importlib.util.spec_from_file_location('repository_layout', SCRIPT)
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)


class ReferenceTests(unittest.TestCase):
    def test_missing_optional_network_snapshot_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertFalse(checks.ui_reference(Path(directory), 'data/ontology-network.json'))

    def test_required_assets_and_other_json_are_not_optional(self):
        with tempfile.TemporaryDirectory() as directory:
            for link in ('assets.js', 'data/manifest.json', 'data/map.json'):
                with self.subTest(link=link), self.assertRaises(AssertionError):
                    checks.ui_reference(Path(directory), link)

    def test_existing_asset_is_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'assets.js').write_text('')
            self.assertTrue(checks.ui_reference(Path(directory), 'assets.js'))

    def test_escape_is_not_allowed_even_if_file_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            child = parent / 'review'
            child.mkdir()
            (parent / 'ontology-network.json').write_text('{}')
            with self.assertRaises(AssertionError):
                checks.ui_reference(child, '../ontology-network.json')


if __name__ == '__main__':
    unittest.main()
