import importlib.util
import json
import os
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
spec = importlib.util.spec_from_file_location('expression_catalog', Path(__file__).resolve().parents[1] / 'catalog.py')
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, COMFYUI_EXPRESSION_LIBRARY=str(self.root))
        self.env.start()
        (self.root / '.gallery').mkdir()
        self.row = {'id': 'F01AF', 'filename': 'afraid_F01AF_00001_.png', 'expression_en': 'incorrect'}
        (self.root / self.row['filename']).write_bytes(b'fixture')
        self.write([self.row])

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def write(self, rows):
        (self.root / '.gallery/catalog.json').write_text(json.dumps({'records': rows}))

    def test_labels_are_derived_from_validated_codes(self):
        row = catalog.record('F01AF')
        self.assertEqual((row['expression_en'], row['expression_zh']), ('afraid', '恐惧'))
        self.assertEqual(catalog.payload()['meta']['completed'], 1)

    def test_missing_file_is_not_advertised(self):
        (self.root / self.row['filename']).unlink()
        self.assertEqual(catalog.records(), [])
        with self.assertRaises(FileNotFoundError):
            catalog.record('F01AF')

    def test_rejects_path_escape_duplicate_and_invalid_actor(self):
        for row in [{**self.row, 'filename': '../outside.png'}, {**self.row, 'id': 'F99AF'}]:
            self.write([row])
            with self.assertRaises(ValueError):
                catalog.records()
        self.write([self.row, self.row])
        with self.assertRaises(ValueError):
            catalog.records()
        with self.assertRaises(ValueError):
            catalog.asset('full', '../F01AF')

    def test_symlink_escape_is_rejected(self):
        target = self.root / self.row['filename']
        target.unlink()
        target.symlink_to('/etc/passwd')
        with self.assertRaises(ValueError):
            catalog.asset('full', 'F01AF')

    def test_catalog_refreshes_without_process_restart(self):
        self.assertEqual(len(catalog.records()), 1)
        row = {'id': 'M35SU', 'filename': 'surprised_M35SU_00001_.png'}
        (self.root / row['filename']).write_bytes(b'fixture')
        self.write([self.row, row])
        self.assertEqual(len(catalog.records()), 2)
        self.assertEqual(catalog.record('M35SU')['expression_en'], 'surprised')

    def test_thumbnail_falls_back_to_original(self):
        self.assertEqual(catalog.asset('thumbs', 'F01AF'), catalog.asset('full', 'F01AF'))
        with self.assertRaises(ValueError):
            catalog.asset('unknown', 'F01AF')


if __name__ == '__main__':
    unittest.main()
