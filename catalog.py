"""A live, confined index of the generated expression references."""
import json
import os
import re
from pathlib import Path
if __package__:
    from . import taxonomy, media
else:
    import taxonomy
    import media

LABELS = {'AF': ('afraid', '恐惧'), 'AN': ('angry', '愤怒'), 'DI': ('disgusted', '厌恶'),
          'HA': ('happy', '开心'), 'NE': ('neutral', '中性'), 'SA': ('sad', '悲伤'), 'SU': ('surprised', '惊讶')}
BUILTIN_ID_PATTERN = re.compile(r'[FM](?:0[1-9]|[12][0-9]|3[0-5])(?:AF|AN|DI|HA|NE|SA|SU)')
ID_PATTERN = re.compile(r'(?:[FM](?:0[1-9]|[12][0-9]|3[0-5])(?:AF|AN|DI|HA|NE|SA|SU)|u-[a-f0-9]{32})')
ROOT = Path(__file__).resolve().parent


def library():
    override = os.environ.get('COMFYUI_EXPRESSION_LIBRARY')
    if override:
        return Path(override).resolve()
    import folder_paths
    return (Path(folder_paths.get_output_directory()) / 'images' / '表情' / '白模').resolve()


def source_rows():
    root = library()
    index = root / '.gallery' / 'catalog.json'
    if not index.is_file():
        return []
    data = json.loads(index.read_text(encoding='utf-8'))
    result, seen = [], set()
    for source in data.get('records', []):
        row = dict(source)
        identity = row.get('id', '')
        if not BUILTIN_ID_PATTERN.fullmatch(identity) or identity in seen:
            raise ValueError('Invalid or duplicate expression ID')
        code = identity[-2:]
        en, zh = LABELS[code]
        filename = row.get('filename', '')
        if not re.fullmatch(re.escape(en + '_' + identity) + r'_\d+_\.png', filename):
            raise ValueError('Invalid expression filename')
        target = (root / filename).resolve()
        if not target.is_relative_to(root):
            raise ValueError('Expression file is outside the library')
        seen.add(identity)
        row.update(actor=identity[:3], code=code, expression_en=en, expression_zh=zh,
                   image_url=f'/expression_gallery/assets/full/{identity}',
                   thumb_url=f'/expression_gallery/assets/thumbs/{identity}')
        result.append(row)
    return result


def raw_records():
    return media.overlay(library(), source_rows())


def records():
    return taxonomy.snapshot(library(), raw_records())[0]


def record(identity):
    if not isinstance(identity, str) or not ID_PATTERN.fullmatch(identity):
        raise ValueError('Invalid expression ID')
    row = next((r for r in records() if r['id'] == identity), None)
    if row is None:
        raise FileNotFoundError('Expression not generated yet: ' + identity)
    return row


def asset(kind, identity):
    if not isinstance(identity, str) or not ID_PATTERN.fullmatch(identity):
        raise ValueError('Invalid expression ID')
    row = next((r for r in raw_records() if r['id'] == identity), None)
    if row is None:
        raise FileNotFoundError(identity)
    root = library()
    paths = media.paths(root, row)
    if kind == 'full':
        if not row['original_available']:
            raise FileNotFoundError('Original deleted; choose an available expression')
        target = paths['full']
    elif kind == 'thumbs':
        target = paths['thumbs']
        if not target.is_file():
            if not row['original_available']:
                raise FileNotFoundError(identity)
            target = paths['full']
    else:
        raise ValueError('Unknown asset kind')
    target = target.resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise FileNotFoundError(identity)
    return target


def payload():
    rows, classification = taxonomy.snapshot(library(), raw_records())
    all_rows = media.overlay(library(), source_rows(), include_removed=True)
    builtins = sum(r['origin'] == 'builtin' for r in rows)
    users = len(rows) - builtins
    removed = sum(r['origin'] == 'builtin' and r['management_state'] == 'removed' for r in all_rows)
    index = library() / '.gallery/catalog.json'
    expected = json.loads(index.read_text(encoding='utf-8')).get('total', len(source_rows())) if index.is_file() else 0
    return {'records': rows, 'taxonomy': classification, 'meta': {'total': max(0, expected-removed)+users, 'completed': len(rows),
            'builtin_count': builtins, 'user_count': users,
            'deleted_count': sum(r['management_state'] == 'removed' for r in all_rows),
            'thumb_only_count': sum(r['management_state'] == 'thumb_only' for r in all_rows),
            'actors': len({r['actor'] for r in rows if r['origin'] == 'builtin'}), 'expressions': [
                {'code': code, 'en': en, 'zh': zh,
                 'count': sum(r['code'] == code for r in rows)} for code, (en, zh) in LABELS.items()]}}
