import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import taxonomy


class TaxonomyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.rows = [{'id': 'F01AF', 'code': 'AF'}, {'id': 'M35SU', 'code': 'SU'}]

    def tearDown(self):
        self.tmp.cleanup()

    def state(self):
        return taxonomy.snapshot(self.root, self.rows)

    def revision(self):
        return self.state()[1]['revision']

    def mutate(self, **body):
        return taxonomy.mutate(self.root, self.rows, {'revision': self.revision(), **body})

    def annotate(self, **body):
        return taxonomy.annotate(self.root, self.rows, {'revision': self.revision(), 'ids': ['F01AF'], **body})

    def test_seed_contains_empty_categories_and_no_invented_actions(self):
        rows, state = self.state()
        self.assertEqual(len(state['categories']), 13)
        self.assertEqual(sum(t['dimension'] == 'type' for t in state['tags']), 83)
        self.assertEqual(next(c['count'] for c in state['categories'] if c['id'] == 'cat_social'), 0)
        self.assertEqual(rows[0]['action_ids'], [])
        self.assertEqual(rows[0]['intensity_id'], 'intensity_unrated')
        self.assertFalse(rows[0]['reviewed'])

    def test_batch_add_replace_remove_preserves_other_dimensions(self):
        self.annotate(ids=['F01AF', 'M35SU'], mode='add', type_ids=['type_shy'], action_ids=['action_lips_pressed'], intensity_id='intensity_mild')
        rows, state = self.state()
        self.assertTrue(all('type_shy' in row['type_ids'] for row in rows))
        self.assertTrue(all(row['reviewed'] for row in rows))
        self.annotate(mode='replace', type_ids=['type_dejected'])
        row = self.state()[0][0]
        self.assertEqual(row['type_ids'], ['type_dejected'])
        self.assertEqual(row['action_ids'], ['action_lips_pressed'])
        self.assertEqual(row['intensity_id'], 'intensity_mild')
        self.annotate(mode='remove', action_ids=['action_lips_pressed'])
        self.assertEqual(self.state()[0][0]['action_ids'], [])

    def test_empty_assignment_does_not_reseed_source_type(self):
        self.annotate(type_ids=[])
        self.assertEqual(self.state()[0][0]['type_ids'], [])
        self.assertEqual(self.state()[0][0]['type_ids'], [])

    def test_rename_and_alias_persist(self):
        self.mutate(entity='tag', operation='update', id='type_afraid', category_id='cat_basic', zh='畏惧', en='fearful', aliases=['恐惧','afraid'])
        row = self.state()[0][0]
        self.assertEqual(row['annotation']['types'][0]['en'], 'fearful')
        self.assertIn('恐惧', row['annotation']['types'][0]['aliases'])

    def test_archive_restore_preserves_assignments(self):
        self.mutate(entity='tag', operation='archive', id='type_afraid')
        rows, state = self.state()
        self.assertEqual(rows[0]['type_ids'], [])
        self.assertEqual(next(t['linked_count'] for t in state['tags'] if t['id']=='type_afraid'),1)
        self.mutate(entity='tag', operation='restore', id='type_afraid')
        self.assertEqual(self.state()[0][0]['type_ids'], ['type_afraid'])
        self.mutate(entity='category', operation='archive', id='cat_basic')
        self.assertEqual(self.state()[0][0]['type_ids'], [])
        self.mutate(entity='category', operation='restore', id='cat_basic')
        self.assertEqual(self.state()[0][0]['type_ids'], ['type_afraid'])

    def test_intensity_archive_falls_back_to_unrated(self):
        self.annotate(intensity_id='intensity_strong')
        self.mutate(entity='tag', operation='archive', id='intensity_strong')
        self.assertEqual(self.state()[0][0]['intensity_id'],'intensity_unrated')
        with self.assertRaises(ValueError):
            self.mutate(entity='tag', operation='archive', id='intensity_unrated')

    def test_creation_and_duplicate_validation(self):
        result=self.mutate(entity='category',operation='create',zh='测试',en='Testing',aliases=[])
        tag=self.mutate(entity='tag',operation='create',dimension='type',category_id=result['id'],zh='测试表情',en='Test expression',aliases=['test'])
        self.annotate(type_ids=[tag['id']])
        self.assertEqual(self.state()[0][0]['category_ids'],[result['id']])
        with self.assertRaises(ValueError):
            self.mutate(entity='tag',operation='create',dimension='type',category_id=result['id'],zh='测试表情',en='Different')

    def test_stale_revision_and_invalid_batch_are_atomic(self):
        revision=self.revision()
        self.annotate(action_ids=['action_eyes_closed'])
        with self.assertRaises(taxonomy.Conflict):
            taxonomy.annotate(self.root,self.rows,{'revision':revision,'ids':['F01AF'],'type_ids':[]})
        for changes in [{'type_ids':['action_eyes_closed']},{'ids':['F01AF','missing'],'type_ids':[]},{'intensity_id':['invalid']}]:
            with self.assertRaises(ValueError):
                self.annotate(**changes)
        self.assertEqual(self.state()[0][0]['type_ids'],['type_afraid'])
        self.assertEqual(self.state()[0][0]['action_ids'],['action_eyes_closed'])

    def test_new_images_are_initialized_once(self):
        self.state()
        self.rows.append({'id':'F02HA','code':'HA'})
        self.assertEqual(self.state()[0][-1]['type_ids'],['type_happy'])


if __name__ == '__main__':
    unittest.main()
