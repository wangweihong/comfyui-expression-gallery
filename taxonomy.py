"""Transactional taxonomy and human annotations, separate from source labels."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import threading
import uuid

SEED = Path(__file__).resolve().parent / 'data' / 'taxonomy.json'
SOURCE_TYPES = {'AF': 'afraid', 'AN': 'angry', 'DI': 'disgusted', 'HA': 'happy',
                'NE': 'neutral', 'SA': 'sad', 'SU': 'surprised'}
DIMENSIONS = {'type', 'action', 'intensity'}
_lock = threading.RLock()


class Conflict(ValueError):
    pass


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


@contextmanager
def connection(root):
    path = Path(root) / '.gallery' / 'annotations.sqlite3'
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        db = sqlite3.connect(path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS categories(
                    id TEXT PRIMARY KEY,zh TEXT NOT NULL,en TEXT NOT NULL,aliases TEXT NOT NULL,
                    position INTEGER NOT NULL,archived INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS tags(
                    id TEXT PRIMARY KEY,dimension TEXT NOT NULL,category_id TEXT REFERENCES categories(id),
                    zh TEXT NOT NULL,en TEXT NOT NULL,aliases TEXT NOT NULL,
                    position INTEGER NOT NULL,archived INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS annotations(
                    asset_id TEXT PRIMARY KEY,intensity_id TEXT REFERENCES tags(id),reviewed INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS asset_tags(
                    asset_id TEXT REFERENCES annotations(asset_id),tag_id TEXT REFERENCES tags(id),
                    PRIMARY KEY(asset_id,tag_id));
                CREATE INDEX IF NOT EXISTS asset_tags_tag ON asset_tags(tag_id);
                CREATE TABLE IF NOT EXISTS media_assets(
                    id TEXT PRIMARY KEY,origin TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'default',
                    metadata TEXT NOT NULL DEFAULT '{}',change_revision TEXT NOT NULL);
            ''')
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT value FROM meta WHERE key='version'").fetchone() is None:
                seed = json.loads(SEED.read_text(encoding='utf-8'))
                for row in seed['categories']:
                    db.execute('INSERT INTO categories(id,zh,en,aliases,position) VALUES(?,?,?,?,?)',
                               (row['id'], row['zh'], row['en'], _json(row['aliases']), row['position']))
                for row in seed['tags']:
                    db.execute('INSERT INTO tags(id,dimension,category_id,zh,en,aliases,position) VALUES(?,?,?,?,?,?,?)',
                               (row['id'], row['dimension'], row['category_id'], row['zh'], row['en'], _json(row['aliases']), row['position']))
                db.executemany('INSERT INTO meta(key,value) VALUES(?,?)', [('version', 1), ('revision', 1)])
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


def _ensure_assets(db, rows):
    changed = False
    for row in rows:
        added = db.execute('INSERT OR IGNORE INTO annotations(asset_id,intensity_id) VALUES(?,?)',
                           (row['id'], 'intensity_unrated')).rowcount
        if added:
            code = SOURCE_TYPES.get(row.get('code'))
            tag = 'type_' + code if code else None
            if tag and db.execute('SELECT id FROM tags WHERE id=? AND archived=0', (tag,)).fetchone():
                db.execute('INSERT INTO asset_tags VALUES(?,?)', (row['id'], tag))
            changed = True
    if changed:
        _bump(db)


def _revision(db):
    return db.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0]


def _bump(db):
    db.execute("UPDATE meta SET value=value+1 WHERE key='revision'")


def _check_revision(db, body):
    if type(body.get('revision')) is not int or body['revision'] != _revision(db):
        raise Conflict('数据已更新，请刷新后重试 / Data changed; reload and retry')


def _decode(row):
    result = dict(row)
    result['aliases'] = json.loads(result['aliases'])
    result['archived'] = bool(result['archived'])
    return result


def _state(db, rows):
    revision = _revision(db)
    categories = [_decode(row) for row in db.execute('SELECT * FROM categories ORDER BY position,id')]
    tags = [_decode(row) for row in db.execute('SELECT * FROM tags ORDER BY position,id')]
    active_categories = {c['id'] for c in categories if not c['archived']}
    lookup = {t['id']: t for t in tags if not t['archived'] and (t['dimension'] != 'type' or t['category_id'] in active_categories)}
    annotations = {r['asset_id']: dict(r) for r in db.execute('SELECT * FROM annotations')}
    links, linked_counts, category_links = {}, {}, {}
    known_assets = {r['id'] for r in rows}
    for row in db.execute('SELECT * FROM asset_tags'):
        if row['asset_id'] in known_assets:
            linked_counts[row['tag_id']] = linked_counts.get(row['tag_id'], 0) + 1
            existing_tag = next((t for t in tags if t['id'] == row['tag_id']), None)
            if existing_tag and existing_tag['category_id']:
                category_links.setdefault(existing_tag['category_id'], set()).add(row['asset_id'])
        if row['tag_id'] in lookup:
            links.setdefault(row['asset_id'], []).append(row['tag_id'])
    enriched, tag_counts, category_counts = [], {}, {}
    for row in rows:
        info = annotations[row['id']]
        tag_ids = sorted(links.get(row['id'], []), key=lambda key: lookup[key]['position'])
        intensity = info['intensity_id'] if info['intensity_id'] in lookup else 'intensity_unrated'
        types = [lookup[k] for k in tag_ids if lookup[k]['dimension'] == 'type']
        actions = [lookup[k] for k in tag_ids if lookup[k]['dimension'] == 'action']
        category_ids = sorted({t['category_id'] for t in types})
        for key in tag_ids + [intensity]:
            tag_counts[key] = tag_counts.get(key, 0) + 1
        for key in category_ids:
            category_counts[key] = category_counts.get(key, 0) + 1
        enriched.append({**row, 'expression_en': ', '.join(t['en'] for t in types) or (row.get('name_en', '') if row.get('origin') == 'user' else ''),
                         'expression_zh': '、'.join(t['zh'] for t in types) or (row.get('name_zh', '') if row.get('origin') == 'user' else ''), 'type_ids': [t['id'] for t in types],
                         'action_ids': [t['id'] for t in actions], 'category_ids': category_ids,
                         'intensity_id': intensity, 'reviewed': bool(info['reviewed']),
                         'annotation': {'types': types, 'actions': actions, 'intensity': lookup[intensity]},
                         'annotation_revision': revision})
    for tag in tags:
        tag['count'] = tag_counts.get(tag['id'], 0)
        tag['linked_count'] = (sum(a['intensity_id'] == tag['id'] for identity, a in annotations.items() if identity in known_assets)
                               if tag['dimension'] == 'intensity' else linked_counts.get(tag['id'], 0))
    for category in categories:
        category['count'] = category_counts.get(category['id'], 0)
        category['linked_count'] = len(category_links.get(category['id'], set()))
    return enriched, {'revision': _revision(db), 'categories': categories, 'tags': tags,
                      'unreviewed': sum(not r['reviewed'] for r in enriched)}


def snapshot(root, rows):
    with connection(root) as db:
        _ensure_assets(db, rows)
        return _state(db, rows)


def _names(body):
    values = {}
    for field in ['zh', 'en']:
        value = body.get(field)
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 100 or any(ord(c) < 32 for c in value):
            raise ValueError('中英文名称均需填写，最多100字符 / Both names are required (max 100 characters)')
        values[field] = value.strip()
    aliases = body.get('aliases', [])
    if not isinstance(aliases, list) or len(aliases) > 30 or any(not isinstance(v, str) or not v.strip() or len(v) > 100 or any(ord(c) < 32 for c in v) for v in aliases):
        raise ValueError('别名格式无效 / Invalid aliases')
    values['aliases'] = list(dict.fromkeys(v.strip() for v in aliases))
    return values


def mutate(root, rows, body):
    if not isinstance(body, dict):
        raise ValueError('Invalid request')
    entity, op = body.get('entity'), body.get('operation')
    if entity not in {'category', 'tag'} or op not in {'create', 'update', 'archive', 'restore'}:
        raise ValueError('Invalid taxonomy operation')
    table = 'categories' if entity == 'category' else 'tags'
    with connection(root) as db:
        _ensure_assets(db, rows)
        _check_revision(db, body)
        current = None
        identity = body.get('id')
        if op != 'create':
            if not isinstance(identity, str):
                raise ValueError('Invalid ID')
            current = db.execute(f'SELECT * FROM {table} WHERE id=?', (identity,)).fetchone()
            if current is None:
                raise ValueError('Unknown taxonomy ID')
            if identity == 'intensity_unrated':
                raise ValueError('“未标注”为保留标签 / Unrated is a reserved tag')
        if op in {'create', 'update'}:
            names = _names(body)
            if entity == 'tag':
                dimension = body.get('dimension') if op == 'create' else current['dimension']
                if dimension not in DIMENSIONS:
                    raise ValueError('Invalid tag dimension')
                category = body.get('category_id') if dimension == 'type' else None
                if dimension == 'type' and (not isinstance(category, str) or not db.execute('SELECT id FROM categories WHERE id=? AND archived=0', (category,)).fetchone()):
                    raise ValueError('请选择有效大类 / Choose an active category')
            for other in db.execute(f'SELECT * FROM {table} WHERE archived=0'):
                if other['id'] == identity or (entity == 'tag' and other['dimension'] != dimension):
                    continue
                if other['zh'].casefold() == names['zh'].casefold() or other['en'].casefold() == names['en'].casefold():
                    raise ValueError('同维度中已有同名标签 / A name already exists in this dimension')
            if op == 'create':
                identity = ('cat_' if entity == 'category' else dimension + '_') + uuid.uuid4().hex
                position = db.execute(f'SELECT COALESCE(MAX(position),0)+1 FROM {table}').fetchone()[0]
                if entity == 'category':
                    db.execute('INSERT INTO categories(id,zh,en,aliases,position) VALUES(?,?,?,?,?)',
                               (identity, names['zh'], names['en'], _json(names['aliases']), position))
                else:
                    db.execute('INSERT INTO tags(id,dimension,category_id,zh,en,aliases,position) VALUES(?,?,?,?,?,?,?)',
                               (identity, dimension, category, names['zh'], names['en'], _json(names['aliases']), position))
            else:
                db.execute(f'UPDATE {table} SET zh=?,en=?,aliases=? WHERE id=?',
                           (names['zh'], names['en'], _json(names['aliases']), identity))
                if entity == 'tag':
                    db.execute('UPDATE tags SET category_id=? WHERE id=?', (category, identity))
        else:
            # Archive preserves assignments and files, allowing restoration.
            if op == 'restore':
                for other in db.execute(f'SELECT * FROM {table} WHERE archived=0 AND id<>?', (identity,)):
                    if entity == 'tag' and other['dimension'] != current['dimension']:
                        continue
                    if other['zh'].casefold() == current['zh'].casefold() or other['en'].casefold() == current['en'].casefold():
                        raise ValueError('同名项已存在，请先修改名称 / A name already exists; rename it first')
            db.execute(f'UPDATE {table} SET archived=? WHERE id=?', (int(op == 'archive'), identity))
        _bump(db)
        return {'id': identity, 'revision': _revision(db)}


def annotate(root, rows, body):
    if not isinstance(body, dict):
        raise ValueError('Invalid request')
    ids = body.get('ids')
    known = {r['id'] for r in rows}
    if not isinstance(ids, list) or not ids or len(ids) > 1000 or any(not isinstance(v, str) or v not in known for v in ids):
        raise ValueError('请选择有效素材 / Select valid images')
    ids = list(dict.fromkeys(ids))
    mode = body.get('mode', 'replace')
    if mode not in {'replace', 'add', 'remove'}:
        raise ValueError('Invalid assignment mode')
    with connection(root) as db:
        _ensure_assets(db, rows)
        _check_revision(db, body)
        changes, intensity = prepare_assignments(db, body)
        write_assignments(db, ids, changes, intensity, mode)
        _bump(db)
        return {'updated': len(ids), 'revision': _revision(db)}


def prepare_assignments(db, body):
    active_categories = {r[0] for r in db.execute('SELECT id FROM categories WHERE archived=0')}
    tags = {r['id']: r for r in db.execute('SELECT * FROM tags WHERE archived=0')}
    changes = {}
    for field, dimension in [('type_ids', 'type'), ('action_ids', 'action')]:
        if field not in body:
            continue
        values = body[field]
        if not isinstance(values, list) or len(values) > 100 or any(not isinstance(key, str) or key not in tags or tags[key]['dimension'] != dimension or (dimension == 'type' and tags[key]['category_id'] not in active_categories) for key in values):
            raise ValueError('标签不存在或维度不匹配 / Unknown tag or mismatched dimension')
        changes[dimension] = list(dict.fromkeys(values))
    intensity = body.get('intensity_id')
    if intensity is not None and (not isinstance(intensity, str) or intensity not in tags or tags[intensity]['dimension'] != 'intensity'):
        raise ValueError('Invalid intensity tag')
    if not changes and intensity is None:
        raise ValueError('请选择至少一个修改项 / Choose a field to update')
    return changes, intensity


def write_assignments(db, ids, changes, intensity, mode='replace', reviewed=True):
    for identity in ids:
        for dimension, values in changes.items():
            if mode == 'replace':
                db.execute('DELETE FROM asset_tags WHERE asset_id=? AND tag_id IN (SELECT id FROM tags WHERE dimension=?)', (identity, dimension))
            for key in values:
                if mode == 'remove':
                    db.execute('DELETE FROM asset_tags WHERE asset_id=? AND tag_id=?', (identity, key))
                else:
                    db.execute('INSERT OR IGNORE INTO asset_tags VALUES(?,?)', (identity, key))
        if intensity is not None:
            db.execute('UPDATE annotations SET intensity_id=? WHERE asset_id=?', (intensity, identity))
        db.execute('UPDATE annotations SET reviewed=? WHERE asset_id=?', (int(reviewed), identity))
