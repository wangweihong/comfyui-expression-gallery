"""Custom imports and explicit, fingerprinted deletion of expression assets."""
from datetime import datetime, timezone
from io import BytesIO
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import uuid

from PIL import Image, ImageOps, UnidentifiedImageError

if __package__:
    from . import taxonomy
else:
    import taxonomy

MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 32_000_000
USER_ID = re.compile(r'u-[a-f0-9]{32}')
LOCK = threading.RLock()
MODES = {'default', 'thumb_only', 'removed'}


class MediaError(ValueError):
    def __init__(self, code, status=400):
        self.code, self.status = code, status
        super().__init__(code)


def safe_path(root, relative):
    root = Path(root).resolve()
    target = root / relative
    if not target.resolve().is_relative_to(root):
        raise MediaError('unsafe_path')
    current = target
    while current != root:
        if current.is_symlink():
            raise MediaError('unsafe_path')
        current = current.parent
    return target


def paths(root, row):
    relative = '.gallery/custom/' + row['filename'] if row['origin'] == 'user' else row['filename']
    return {'full': safe_path(root, relative),
            'thumbs': safe_path(root, '.gallery/thumbs/' + row['id'] + '.webp')}


def _text(value, required=False):
    if not isinstance(value, str) or len(value.strip()) > 120 or any(ord(c) < 32 for c in value):
        raise MediaError('invalid_metadata')
    if required and not value.strip():
        raise MediaError('name_required')
    return value.strip()


def _custom(row):
    identity = row.get('id', '')
    if not USER_ID.fullmatch(identity) or row.get('filename') != identity + '.png':
        raise MediaError('invalid_metadata')
    _text(row.get('name_zh'), True)
    _text(row.get('name_en'), True)
    if (type(row.get('width')) is not int or type(row.get('height')) is not int
            or min(row['width'], row['height']) < 1 or row['width'] * row['height'] > MAX_PIXELS
            or not re.fullmatch('[a-f0-9]{64}', row.get('sha256', ''))):
        raise MediaError('invalid_metadata')
    return row


def _rows(db, root, builtins):
    registry = {row['id']: dict(row) for row in db.execute('SELECT * FROM media_assets')}
    rows = [dict(row, origin='builtin', name_zh=row['id'], name_en=row['id']) for row in builtins]
    for identity, stored in registry.items():
        if stored['origin'] == 'user':
            row = _custom(json.loads(stored['metadata']))
            if row['id'] != identity:
                raise MediaError('invalid_metadata')
            rows.append(dict(row, origin='user'))
        elif stored['origin'] != 'builtin':
            raise MediaError('invalid_metadata')
    result = []
    for source in rows:
        row = dict(source)
        stored = registry.get(row['id'])
        state = stored['state'] if stored else 'default'
        if state not in MODES or (stored and stored['origin'] != row['origin']):
            raise MediaError('invalid_metadata')
        locations = paths(root, row)
        row.update(management_state=state, installed_original=locations['full'].is_file(),
                   installed_thumb=locations['thumbs'].is_file(),
                   original_available=state == 'default' and locations['full'].is_file(),
                   asset_version=stored['change_revision'] if stored else row.get('sha256', ''))
        row['disk_bytes'] = sum(p.stat().st_size for p in locations.values() if p.is_file())
        version = row['asset_version']
        row['image_url'] = f'/expression_gallery/assets/full/{row["id"]}?v={version}'
        row['thumb_url'] = f'/expression_gallery/assets/thumbs/{row["id"]}?v={version}'
        result.append(row)
    return result


def overlay(root, builtins, include_removed=False):
    with taxonomy.connection(root) as db:
        rows = _rows(db, root, builtins)
    if include_removed:
        return rows
    return [r for r in rows if r['management_state'] != 'removed' and
            (r['original_available'] or (r['management_state'] == 'thumb_only' and r['installed_thumb']))]


def import_image(root, data, *, filename, metadata):
    if not isinstance(data, bytes) or len(data) > MAX_BYTES:
        raise MediaError('file_too_large', 413)
    if (not isinstance(filename, str) or not filename or len(filename) > 255 or Path(filename).name != filename
            or '/' in filename or '\\' in filename or any(ord(c) < 32 for c in filename)):
        raise MediaError('invalid_filename')
    if not isinstance(metadata, dict):
        raise MediaError('invalid_metadata')
    zh, en = _text(metadata.get('name_zh', '')), _text(metadata.get('name_en', ''))
    if not (zh or en):
        raise MediaError('name_required')
    try:
        with Image.open(BytesIO(data)) as source:
            if source.format not in {'PNG', 'JPEG', 'WEBP'}:
                raise MediaError('unsupported_format')
            if getattr(source, 'n_frames', 1) != 1:
                raise MediaError('animated_image')
            if source.width * source.height > MAX_PIXELS:
                raise MediaError('too_many_pixels')
            source.load()
            image = ImageOps.exif_transpose(source).convert('RGBA' if 'A' in source.getbands() or 'transparency' in source.info else 'RGB')
    except MediaError:
        raise
    except Image.DecompressionBombError as exc:
        raise MediaError('too_many_pixels') from exc
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise MediaError('invalid_image') from exc
    root = Path(root).resolve()
    identity = 'u-' + uuid.uuid4().hex
    row = {'id': identity, 'origin': 'user', 'actor': 'custom', 'code': '',
           'name_zh': zh or en, 'name_en': en or zh, 'filename': identity + '.png',
           'source_filename': filename, 'original_filename': filename,
           'width': image.width, 'height': image.height,
           'uploaded_at': datetime.now(timezone.utc).isoformat()}
    locations = paths(root, row)
    for path in locations.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    settings = {'type_ids': metadata.get('type_ids', []), 'action_ids': metadata.get('action_ids', []),
                'intensity_id': metadata.get('intensity_id', 'intensity_unrated')}
    moved, committed = [], False
    with LOCK, tempfile.TemporaryDirectory(prefix='.upload-', dir=root / '.gallery') as staging:
        staging = Path(staging)
        image.save(staging / 'full.png', format='PNG')
        thumb = Image.alpha_composite(Image.new('RGBA', image.size, 'white'), image.convert('RGBA')).convert('RGB')
        thumb.thumbnail((256, 256), Image.Resampling.LANCZOS)
        thumb.save(staging / 'thumb.webp', format='WEBP', quality=88)
        row.update(sha256=hashlib.sha256((staging / 'full.png').read_bytes()).hexdigest(),
                   bytes=(staging / 'full.png').stat().st_size)
        try:
            with taxonomy.connection(root) as db:
                taxonomy._check_revision(db, metadata)
                changes, intensity = taxonomy.prepare_assignments(db, settings)
                if db.execute('SELECT id FROM media_assets WHERE id=?', (identity,)).fetchone() or any(p.exists() for p in locations.values()):
                    raise MediaError('storage_error', 500)
                for kind, staged in [('full', 'full.png'), ('thumbs', 'thumb.webp')]:
                    os.replace(staging / staged, locations[kind])
                    moved.append(locations[kind])
                db.execute('INSERT INTO media_assets(id,origin,state,metadata,change_revision) VALUES(?,?,?,?,?)',
                           (identity, 'user', 'default', taxonomy._json(row), uuid.uuid4().hex))
                taxonomy._ensure_assets(db, [row])
                reviewed = bool(settings['type_ids'] or settings['action_ids'] or intensity != 'intensity_unrated')
                taxonomy.write_assignments(db, [identity], changes, intensity, reviewed=reviewed)
                taxonomy._bump(db)
            committed = True
        finally:
            if not committed:
                for path in moved:
                    path.unlink(missing_ok=True)
    return row


def edit_name(root, builtins, body):
    if not isinstance(body, dict) or not isinstance(body.get('id'), str) or not USER_ID.fullmatch(body['id']):
        raise MediaError('invalid_selection')
    zh, en = _text(body.get('name_zh', '')), _text(body.get('name_en', ''))
    if not (zh or en):
        raise MediaError('name_required')
    with LOCK, taxonomy.connection(root) as db:
        taxonomy._check_revision(db, body)
        stored = db.execute("SELECT * FROM media_assets WHERE id=? AND origin='user' AND state<>'removed'", (body['id'],)).fetchone()
        if stored is None:
            raise MediaError('invalid_selection')
        row = _custom(json.loads(stored['metadata']))
        row.update(name_zh=zh or en, name_en=en or zh)
        db.execute('UPDATE media_assets SET metadata=?,change_revision=? WHERE id=?', (taxonomy._json(row), uuid.uuid4().hex, body['id']))
        taxonomy._bump(db)
        return {'id': body['id'], 'revision': taxonomy._revision(db)}


def _plan(db, root, builtins, body):
    if not isinstance(body, dict):
        raise MediaError('invalid_request')
    taxonomy._check_revision(db, body)
    ids, mode = body.get('ids'), body.get('mode')
    rows = {r['id']: r for r in _rows(db, root, builtins)}
    if (not isinstance(ids, list) or not ids or len(ids) > 1000
            or any(not isinstance(key, str) or key not in rows for key in ids) or mode not in MODES):
        raise MediaError('invalid_selection')
    ids = sorted(set(ids))
    items, fingerprint = [], []
    for key in ids:
        row = rows[key]
        locations = paths(root, row)
        if mode == 'default' and not all(p.is_file() for p in locations.values()):
            raise MediaError('restore_missing')
        operations = []
        for kind, path in locations.items():
            stat = path.stat() if path.exists() else None
            if stat is not None and not path.is_file():
                raise MediaError('unsafe_path')
            fingerprint.append([key, kind, str(path), stat.st_mtime_ns if stat else None, stat.st_size if stat else 0])
            if stat and (mode == 'removed' or (mode == 'thumb_only' and kind == 'full')):
                operations.append({'kind': kind, 'action': 'delete', 'bytes': stat.st_size})
        items.append({'id': key, 'origin': row['origin'], 'name_zh': row['name_zh'], 'name_en': row['name_en'],
                      'mode': mode, 'operations': operations})
    canonical = {'ids': ids, 'mode': mode, 'revision': body['revision']}
    token = hashlib.sha256(taxonomy._json([canonical, fingerprint]).encode()).hexdigest()
    return {'request': canonical, 'token': token, 'items': items,
            'file_count': sum(len(r['operations']) for r in items),
            'release_bytes': sum(op['bytes'] for r in items for op in r['operations'])}


def plan(root, builtins, body):
    with LOCK, taxonomy.connection(root) as db:
        return _plan(db, root, builtins, body)


def apply(root, builtins, body):
    if not isinstance(body, dict) or not isinstance(body.get('request'), dict) or not isinstance(body.get('token'), str):
        raise MediaError('invalid_request')
    with LOCK:
        with taxonomy.connection(root) as db:
            result = _plan(db, root, builtins, body['request'])
            if not hmac.compare_digest(result['token'], body['token']):
                raise MediaError('plan_changed', 409)
            rows = {r['id']: r for r in _rows(db, root, builtins)}
            for item in result['items']:
                row = rows[item['id']]
                db.execute('INSERT INTO media_assets(id,origin,state,metadata,change_revision) VALUES(?,?,?,?,?) '
                           'ON CONFLICT(id) DO UPDATE SET state=excluded.state,change_revision=excluded.change_revision',
                           (row['id'], row['origin'], item['mode'], taxonomy._json(row) if row['origin'] == 'user' else '{}', uuid.uuid4().hex))
            taxonomy._bump(db)
        # Commit deletion intent first. Partial file failures remain hidden and can be retried.
        completed, failures, released = [], [], 0
        for item in result['items']:
            try:
                for operation in item['operations']:
                    path = paths(root, rows[item['id']])[operation['kind']]
                    path.unlink(missing_ok=True)
                    released += operation['bytes']
                completed.append(item['id'])
            except (OSError, MediaError):
                failures.append({'id': item['id'], 'error': 'storage_error'})
        return {'completed': completed, 'failures': failures, 'release_bytes': released}


def status(root, builtins):
    with taxonomy.connection(root) as db:
        return {'records': _rows(db, root, builtins), 'revision': taxonomy._revision(db)}
