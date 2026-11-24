"""Exercise the real gallery node without importing ComfyUI's HTTP server."""
import ast
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
try:
    import numpy as np
    import torch
except ImportError:
    np = torch = None

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import catalog
import media
import taxonomy


def node_class():
    source = ast.parse((ROOT / '__init__.py').read_text())
    definition = next(node for node in source.body if isinstance(node, ast.ClassDef) and node.name == 'ExpressionClayGallery')
    namespace = {'catalog': catalog, 'Image': Image, 'ImageOps': __import__('PIL.ImageOps', fromlist=['ImageOps']),
                 'np': np, 'torch': torch, 'json': json, 'hashlib': __import__('hashlib')}
    exec(compile(ast.Module(body=[definition], type_ignores=[]), str(ROOT / '__init__.py'), 'exec'), namespace)
    return namespace['ExpressionClayGallery']


@unittest.skipIf(torch is None, 'Node image tests require the ComfyUI Python environment')
class NodeOutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.environment = patch.dict(os.environ, COMFYUI_EXPRESSION_LIBRARY=str(self.root))
        self.environment.start()
        (self.root / '.gallery').mkdir()
        Image.new('RGB', (64, 48), '#cccccc').save(self.root / 'happy_F01HA_00001_.png')
        (self.root / '.gallery/catalog.json').write_text(json.dumps({'total': 1, 'records': [
            {'id': 'F01HA', 'filename': 'happy_F01HA_00001_.png', 'width': 64, 'height': 48}]}))
        catalog.payload()
        self.node = node_class()

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def test_public_outputs_are_image_and_bilingual_expression(self):
        self.assertEqual(self.node.RETURN_TYPES, ('IMAGE', 'STRING', 'STRING'))
        self.assertEqual(self.node.RETURN_NAMES, ('image', 'expression_en', 'expression_zh'))
        result = self.node().load_expression('F01HA')
        self.assertEqual(len(result), 3)
        self.assertEqual(tuple(result[0].shape), (1, 48, 64, 3))
        self.assertEqual(result[1:], ('happy', '开心'))

    def test_edited_expression_tags_change_the_two_text_outputs(self):
        data = catalog.payload()
        taxonomy.annotate(self.root, catalog.raw_records(), {'revision': data['taxonomy']['revision'],
            'ids': ['F01HA'], 'type_ids': ['type_shy'], 'mode': 'replace'})
        self.assertEqual(self.node().load_expression('F01HA')[1:], ('shy', '害羞'))

    def test_custom_names_and_transparent_image_still_work(self):
        output = BytesIO()
        Image.new('RGBA', (32, 40), (20, 40, 80, 0)).save(output, 'PNG')
        row = media.import_image(self.root, output.getvalue(), filename='reference.png', metadata={
            'revision': catalog.payload()['taxonomy']['revision'], 'name_zh': '自定义笑容', 'name_en': 'Custom smile'})
        result = self.node().load_expression(row['id'], 'en')
        self.assertEqual(result[1:], ('Custom smile', '自定义笑容'))
        self.assertEqual(tuple(result[0].shape), (1, 40, 32, 3))
        self.assertEqual(float(result[0].min()), 1.)


if __name__ == '__main__':
    unittest.main()
