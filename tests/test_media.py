from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import catalog
import media
import taxonomy


def image_bytes(fmt='PNG', size=(40, 30), transparent=False):
    image = Image.new('RGBA' if transparent else 'RGB', size, (255, 0, 0, 0) if transparent else 'white')
    ImageDraw.Draw(image).ellipse((10, 8, 25, 24), fill='blue')
    out = BytesIO()
    image.save(out, format=fmt)
    return out.getvalue()


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, COMFYUI_EXPRESSION_LIBRARY=str(self.root))
        self.env.start()
        (self.root / '.gallery/thumbs').mkdir(parents=True)
        self.rows = []
        for identity, en, zh in [('F01AF', 'afraid', '恐惧'), ('M35SU', 'surprised', '惊讶')]:
            filename = en + '_' + identity + '_00001_.png'
            content = image_bytes()
            (self.root / filename).write_bytes(content)
            with Image.open(BytesIO(content)) as im:
                im.save(self.root / '.gallery/thumbs' / (identity + '.webp'), 'WEBP')
            self.rows.append({'id': identity, 'actor': identity[:3], 'code': identity[-2:], 'filename': filename,
                              'width': 40, 'height': 30, 'expression_en': en, 'expression_zh': zh,
                              'source_filename': identity + '.jpg', 'sha256': hashlib.sha256(content).hexdigest()})
        (self.root / '.gallery/catalog.json').write_text(json.dumps({'total': 2, 'records': self.rows}))
        catalog.payload()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def revision(self):
        return catalog.payload()['taxonomy']['revision']

    def upload(self, **metadata):
        return media.import_image(self.root, image_bytes(transparent=True), filename='face.png',
                                  metadata={'revision': self.revision(), 'name_zh': '自定义表情', **metadata})

    def plan(self, ids, mode='removed'):
        return media.plan(self.root, catalog.source_rows(), {'revision': self.revision(), 'ids': ids, 'mode': mode})

    def apply(self, plan):
        return media.apply(self.root, catalog.source_rows(), {'request': plan['request'], 'token': plan['token']})

    def test_upload_preserves_alpha_names_and_tag_assignments(self):
        row = self.upload(name_en='Custom face', type_ids=['type_shy'], action_ids=['action_lips_pressed'], intensity_id='intensity_mild')
        self.assertRegex(row['id'], r'^u-[a-f0-9]{32}$')
        actual = catalog.record(row['id'])
        self.assertEqual(actual['origin'], 'user')
        self.assertEqual(actual['type_ids'], ['type_shy'])
        self.assertEqual(actual['action_ids'], ['action_lips_pressed'])
        self.assertEqual(actual['intensity_id'], 'intensity_mild')
        self.assertTrue(actual['reviewed'])
        self.assertEqual(catalog.payload()['meta']['user_count'], 1)
        with Image.open(catalog.asset('full', row['id'])) as image:
            self.assertEqual(image.mode, 'RGBA')
            self.assertEqual(image.getpixel((0, 0))[3], 0)
        with Image.open(catalog.asset('thumbs', row['id'])) as image:
            self.assertGreater(min(image.convert('RGB').getpixel((0, 0))), 240)

    def test_custom_only_without_builtin_index(self):
        (self.root / '.gallery/catalog.json').unlink()
        row = self.upload(name_zh='', name_en='Only English')
        self.assertEqual(catalog.record(row['id'])['name_zh'], 'Only English')
        self.assertEqual(catalog.payload()['meta']['total'], 1)
        self.assertFalse(catalog.record(row['id'])['reviewed'])

    def test_custom_rename_and_delete(self):
        row = self.upload()
        media.edit_name(self.root, catalog.source_rows(), {'id': row['id'], 'revision': self.revision(), 'name_zh': '新的名称', 'name_en': 'New name'})
        self.assertEqual(catalog.record(row['id'])['name_en'], 'New name')
        full, thumb = catalog.asset('full', row['id']), catalog.asset('thumbs', row['id'])
        self.apply(self.plan([row['id']]))
        self.assertFalse(full.exists())
        self.assertFalse(thumb.exists())
        with self.assertRaises(FileNotFoundError):
            catalog.record(row['id'])
        self.assertEqual(catalog.payload()['meta']['user_count'], 0)

    def test_deletion_removes_builtins_and_preserves_input_independent_files(self):
        unrelated = self.root / 'unrelated.txt'
        unrelated.write_text('keep')
        plan = self.plan(['F01AF', 'M35SU'])
        self.assertEqual(plan['file_count'], 4)
        self.assertGreater(plan['release_bytes'], 0)
        result = self.apply(plan)
        self.assertEqual(len(result['completed']), 2)
        self.assertEqual(catalog.records(), [])
        self.assertTrue(unrelated.exists())
        self.assertTrue((self.root / '.gallery/catalog.json').exists())
        self.assertEqual(catalog.payload()['meta']['total'], 0)
        with taxonomy.connection(self.root) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM tags').fetchone()[0], 121)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM annotations').fetchone()[0], 2)

    def test_deleted_intent_stays_hidden_if_files_are_copied_back(self):
        self.apply(self.plan(['F01AF']))
        (self.root / self.rows[0]['filename']).write_bytes(image_bytes())
        self.assertNotIn('F01AF', {row['id'] for row in catalog.records()})
        with self.assertRaises(media.MediaError):
            self.plan(['F01AF'], 'default')
        (self.root / '.gallery/thumbs/F01AF.webp').write_bytes(image_bytes('WEBP'))
        self.apply(self.plan(['F01AF'], 'default'))
        self.assertTrue(catalog.record('F01AF')['original_available'])

    def test_keep_thumbnail_cannot_be_used_as_full_reference(self):
        self.apply(self.plan(['F01AF'], 'thumb_only'))
        row = catalog.record('F01AF')
        self.assertFalse(row['original_available'])
        self.assertTrue(catalog.asset('thumbs', 'F01AF').exists())
        with self.assertRaises(FileNotFoundError):
            catalog.asset('full', 'F01AF')
        status = media.status(self.root, catalog.source_rows())
        self.assertEqual(next(r for r in status['records'] if r['id']=='F01AF')['management_state'], 'thumb_only')

    def test_changed_files_or_revision_reject_stale_plan(self):
        plan = self.plan(['F01AF'])
        target = self.root / self.rows[0]['filename']
        target.write_bytes(image_bytes(size=(41, 31)))
        with self.assertRaises(media.MediaError):
            self.apply(plan)
        self.assertTrue(target.exists())
        plan = self.plan(['F01AF'])
        taxonomy.annotate(self.root, catalog.raw_records(), {'revision': self.revision(), 'ids': ['F01AF'], 'type_ids': []})
        with self.assertRaises(taxonomy.Conflict):
            self.apply(plan)

    def test_upload_rejects_invalid_data_and_filename(self):
        for content, filename in [(b'broken', 'face.png'), (image_bytes(), '../face.png'), (image_bytes(), 'a\\b.png'), (image_bytes('BMP'), 'face.bmp')]:
            with self.assertRaises(media.MediaError):
                media.import_image(self.root, content, filename=filename, metadata={'revision': self.revision(), 'name_en':'Face'})
        with patch.object(media, 'MAX_BYTES', 2):
            with self.assertRaises(media.MediaError):
                self.upload()

    def test_animation_and_pixel_limits(self):
        out = BytesIO()
        frames = [Image.new('RGBA', (12,12), color) for color in ['red','green']]
        frames[0].save(out, format='PNG', save_all=True, append_images=frames[1:])
        with self.assertRaises(media.MediaError):
            media.import_image(self.root, out.getvalue(), filename='animated.png', metadata={'revision':self.revision(),'name_en':'Face'})
        with patch.object(media, 'MAX_PIXELS', 10):
            with self.assertRaises(media.MediaError):
                self.upload()

    def test_invalid_tag_and_stale_upload_leave_no_image_files(self):
        with self.assertRaises(ValueError):
            self.upload(type_ids=['action_eyes_closed'])
        with self.assertRaises(taxonomy.Conflict):
            media.import_image(self.root, image_bytes(), filename='face.png', metadata={'revision':0,'name_en':'Face'})
        self.assertEqual(list((self.root/'.gallery/custom').glob('*.png')), [])
        self.assertEqual(catalog.payload()['meta']['user_count'], 0)

    def test_symlink_paths_and_invalid_ids_are_rejected(self):
        target = self.root / self.rows[0]['filename']
        target.unlink()
        target.symlink_to(self.root / self.rows[1]['filename'])
        with self.assertRaises(media.MediaError):
            media.status(self.root, catalog.source_rows())
        with self.assertRaises(ValueError):
            catalog.asset('full', '../F01AF')

    def test_concurrent_uploads_do_not_drop_records(self):
        revision = self.revision()
        def upload(name):
            try:
                return media.import_image(self.root, image_bytes(), filename='face.png',
                    metadata={'revision': revision, 'name_en': name})
            except taxonomy.Conflict:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(upload, ['First', 'Second']))
        self.assertEqual(sum(row is not None for row in results), 1)
        second = self.upload(name_en='Retried after reload')
        self.assertNotEqual(next(row['id'] for row in results if row), second['id'])
        self.assertEqual(catalog.payload()['meta']['user_count'], 2)


if __name__ == '__main__':
    unittest.main()
