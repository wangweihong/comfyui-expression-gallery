"""Qwen white-clay expression gallery for ComfyUI."""
import asyncio
import hashlib
import json
import sqlite3
import numpy as np
import torch
from PIL import Image, ImageOps
from aiohttp import web
from server import PromptServer
from . import catalog, media
from . import taxonomy


class ExpressionClayGallery:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {
            'expression_id': ('STRING', {'default': 'F01AF', 'tooltip': '浏览表情图库选择白模 / Browse white-clay expressions'}),
            'language': (['zh', 'en'], {'default': 'zh'})}}

    RETURN_TYPES = ('IMAGE', 'INT', 'INT', 'STRING', 'STRING', 'STRING', 'STRING', 'STRING', 'STRING', 'STRING', 'STRING')
    RETURN_NAMES = ('image', 'width', 'height', 'expression_id', 'expression_en', 'expression_zh', 'description',
                    'expression_types_en', 'facial_actions_en', 'intensity_en', 'tags_json')
    FUNCTION = 'load_expression'
    CATEGORY = 'image/Expression Gallery'
    DESCRIPTION = '白模表情图库：大类、表情类型、面部动作与强度标签；支持双语筛选、单张与批量标注。Bilingual expression gallery with editable taxonomy and annotations.'

    @classmethod
    def VALIDATE_INPUTS(cls, expression_id, language='zh'):
        try:
            catalog.asset('full', expression_id)
        except (ValueError, FileNotFoundError, OSError) as exc:
            return str(exc)
        return True

    @classmethod
    def IS_CHANGED(cls, expression_id, language='zh'):
        path = catalog.asset('full', expression_id)
        row = catalog.record(expression_id)
        annotation = {'annotation': row['annotation'], 'reviewed': row['reviewed'],
                      'name_zh': row.get('name_zh'), 'name_en': row.get('name_en')}
        return hashlib.sha256(path.read_bytes() + language.encode() + json.dumps(annotation, sort_keys=True).encode()).hexdigest()

    def load_expression(self, expression_id, language='zh'):
        row = catalog.record(expression_id)
        with Image.open(catalog.asset('full', expression_id)) as source:
            rgba = ImageOps.exif_transpose(source).convert('RGBA')
            im = Image.alpha_composite(Image.new('RGBA', rgba.size, 'white'), rgba).convert('RGB')
            image = torch.from_numpy(np.array(im, dtype=np.float32) / 255.).unsqueeze(0)
            width, height = im.size
        info = row['annotation']
        en = row['name_en'] if row['origin'] == 'user' else ', '.join(tag['en'] for tag in info['types'])
        zh = row['name_zh'] if row['origin'] == 'user' else '、'.join(tag['zh'] for tag in info['types'])
        kind_en = 'custom expression reference' if row['origin'] == 'user' else 'white clay head, frontal view'
        kind_zh = '自定义表情参考' if row['origin'] == 'user' else '正面白模人脸'
        description = (f'{en or "unlabeled"} facial expression, {kind_en}, reference {expression_id}'
                       if language == 'en' else f'{zh or "未标注"}表情，{kind_zh}，参考编号 {expression_id}')
        types = ', '.join(tag['en'] for tag in info['types'])
        actions = ', '.join(tag['en'] for tag in info['actions'])
        intensity = info['intensity']['en']
        field = 'en' if language == 'en' else 'zh'
        details = [tag[field] for tag in info['types'] + info['actions']]
        if info['intensity']['id'] != 'intensity_unrated':
            details.append(info['intensity'][field])
        if details:
            description += ('; Tags: ' if language == 'en' else '；标签：') + ', '.join(details)
        tags_json = json.dumps({'expression_id': expression_id, 'origin': row['origin'],
                                'name_zh': row['name_zh'], 'name_en': row['name_en'],
                                'reviewed': row['reviewed'], **info}, ensure_ascii=False)
        return image, width, height, expression_id, en, zh, description, types, actions, intensity, tags_json


routes = PromptServer.instance.routes


@routes.get('/expression_gallery/gallery')
async def gallery(request):
    return web.FileResponse(catalog.ROOT / 'web' / 'gallery.html', headers={'Cache-Control': 'no-store'})


@routes.get('/expression_gallery/catalog')
async def index(request):
    try:
        result = await asyncio.to_thread(catalog.payload)
        return web.json_response(result, headers={'Cache-Control': 'no-store'})
    except (ValueError, OSError, sqlite3.Error) as exc:
        return web.json_response({'error': str(exc)}, status=500)


async def _mutation(request, operation):
    origin = request.headers.get('Origin')
    if origin and origin != f'{request.scheme}://{request.host}':
        raise web.HTTPForbidden(text='Cross-origin changes are not allowed')
    try:
        body = await request.json()
        result = await asyncio.to_thread(operation, catalog.library(), catalog.raw_records(), body)
        return web.json_response(result, headers={'Cache-Control': 'no-store'})
    except taxonomy.Conflict as exc:
        return web.json_response({'error': str(exc)}, status=409)
    except (ValueError, TypeError, KeyError) as exc:
        return web.json_response({'error': str(exc)}, status=400)
    except (OSError, sqlite3.Error) as exc:
        return web.json_response({'error': str(exc)}, status=500)


def _check_origin(request):
    origin = request.headers.get('Origin')
    if origin and origin != f'{request.scheme}://{request.host}':
        raise web.HTTPForbidden(text='Cross-origin changes are not allowed')


async def _media_mutation(request, operation):
    _check_origin(request)
    try:
        body = await request.json()
        result = await asyncio.to_thread(operation, catalog.library(), catalog.source_rows(), body)
        return web.json_response(result, headers={'Cache-Control': 'no-store'})
    except taxonomy.Conflict as exc:
        return web.json_response({'error': str(exc)}, status=409)
    except media.MediaError as exc:
        return web.json_response({'error': exc.code}, status=exc.status)
    except (ValueError, TypeError, KeyError):
        return web.json_response({'error': 'invalid_request'}, status=400)
    except (OSError, sqlite3.Error):
        return web.json_response({'error': 'storage_error'}, status=500)


@routes.post('/expression_gallery/upload')
async def upload(request):
    _check_origin(request)
    try:
        if request.content_type != 'multipart/form-data':
            raise media.MediaError('invalid_request')
        multipart = await request.multipart()
        data, filename, metadata = None, None, None
        async for part in multipart:
            if part.filename is not None:
                if part.name != 'image' or data is not None:
                    raise media.MediaError('single_image_only')
                chunks, size = [], 0
                while chunk := await part.read_chunk():
                    size += len(chunk)
                    if size > media.MAX_BYTES:
                        raise media.MediaError('file_too_large', 413)
                    chunks.append(chunk)
                data, filename = b''.join(chunks), part.filename
            else:
                if part.name != 'metadata' or metadata is not None:
                    raise media.MediaError('invalid_metadata')
                chunks, size = [], 0
                while chunk := await part.read_chunk():
                    size += len(chunk)
                    if size > 32768:
                        raise media.MediaError('invalid_metadata')
                    chunks.append(chunk)
                metadata = json.loads(b''.join(chunks).decode('utf-8'))
        if data is None:
            raise media.MediaError('image_required')
        row = await asyncio.to_thread(media.import_image, catalog.library(), data,
                                      filename=filename, metadata=metadata)
        return web.json_response({'id': row['id']}, status=201, headers={'Cache-Control': 'no-store'})
    except taxonomy.Conflict as exc:
        return web.json_response({'error': str(exc)}, status=409)
    except media.MediaError as exc:
        return web.json_response({'error': exc.code}, status=exc.status)
    except (ValueError, TypeError, KeyError, UnicodeError):
        return web.json_response({'error': 'invalid_request'}, status=400)
    except (OSError, sqlite3.Error):
        return web.json_response({'error': 'storage_error'}, status=500)


@routes.post('/expression_gallery/custom/name')
async def edit_custom_name(request):
    return await _media_mutation(request, media.edit_name)


@routes.get('/expression_gallery/manage')
async def management_status(request):
    try:
        result = await asyncio.to_thread(media.status, catalog.library(), catalog.source_rows())
        return web.json_response(result, headers={'Cache-Control': 'no-store'})
    except (ValueError, OSError, sqlite3.Error):
        return web.json_response({'error': 'storage_error'}, status=500)


@routes.post('/expression_gallery/manage/plan')
async def deletion_plan(request):
    return await _media_mutation(request, media.plan)


@routes.post('/expression_gallery/manage/apply')
async def deletion_apply(request):
    return await _media_mutation(request, media.apply)


@routes.post('/expression_gallery/taxonomy')
async def edit_taxonomy(request):
    return await _mutation(request, taxonomy.mutate)


@routes.post('/expression_gallery/annotations')
async def edit_annotations(request):
    return await _mutation(request, taxonomy.annotate)


@routes.get('/expression_gallery/assets/{kind}/{identity}')
async def image_asset(request):
    try:
        path = await asyncio.to_thread(catalog.asset, request.match_info['kind'], request.match_info['identity'])
        return web.FileResponse(path)
    except (ValueError, FileNotFoundError, OSError) as exc:
        raise web.HTTPNotFound(text=str(exc))


@routes.get('/expression_gallery/web/{filename}')
async def static_asset(request):
    name = request.match_info['filename']
    if name not in {'gallery.mjs', 'style.css', 'i18n.mjs', 'icon.svg', 'tag_manager.mjs', 'tag_styles.css', 'tags_i18n.mjs', 'asset_manager.mjs', 'asset_styles.css', 'assets_i18n.mjs'}:
        raise web.HTTPNotFound()
    return web.FileResponse(catalog.ROOT / 'web' / name, headers={'Cache-Control': 'no-cache'})


NODE_CLASS_MAPPINGS = {'ExpressionClayGallery': ExpressionClayGallery}
NODE_DISPLAY_NAME_MAPPINGS = {'ExpressionClayGallery': 'Expression Gallery 白模表情图库'}
WEB_DIRECTORY = './web'
__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS', 'WEB_DIRECTORY']
