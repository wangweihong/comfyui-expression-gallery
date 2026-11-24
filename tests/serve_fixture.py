"""Serve an isolated, disposable gallery for browser QA; never edits the real index."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import shutil
import sys
import tempfile
from email.parser import BytesParser
from email.policy import default
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import catalog
import taxonomy
import media


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--library', required=True)
    parser.add_argument('--port', type=int, default=8193)
    args = parser.parse_args()
    source = Path(args.library)
    with tempfile.TemporaryDirectory(prefix='expression-gallery-qa-') as tmp:
        target = Path(tmp)
        (target / '.gallery/thumbs').mkdir(parents=True)
        manifest = json.loads((source / '.gallery/catalog.json').read_text())
        rows = [r for r in manifest['records'] if r['actor'] == 'F01' or r['id'] == 'M35SU']
        manifest['records'] = rows
        for row in rows:
            shutil.copy2(source / row['filename'], target / row['filename'])
            shutil.copy2(source / '.gallery/thumbs' / (row['id'] + '.webp'), target / '.gallery/thumbs' / (row['id'] + '.webp'))
        (target / '.gallery/catalog.json').write_text(json.dumps(manifest))
        os.environ['COMFYUI_EXPRESSION_LIBRARY'] = str(target)

        class Handler(BaseHTTPRequestHandler):
            def json_response(self, body, status=200):
                content = json.dumps(body, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            def do_GET(self):
                path = urlparse(self.path).path
                if path == '/expression_gallery/catalog':
                    return self.json_response(catalog.payload())
                if path == '/expression_gallery/manage':
                    return self.json_response(media.status(target, catalog.source_rows()))
                if path == '/expression_gallery/gallery':
                    file = ROOT / 'web/gallery.html'
                elif path.startswith('/expression_gallery/web/'):
                    file = ROOT / 'web' / Path(path).name
                elif path.startswith('/expression_gallery/assets/'):
                    try:
                        _, _, _, kind, identity = path.split('/')
                        file = catalog.asset(kind, identity)
                    except (ValueError, FileNotFoundError):
                        return self.send_error(404)
                else:
                    return self.send_error(404)
                if not file.is_file():
                    return self.send_error(404)
                self.send_response(200)
                self.send_header('Content-Type', mimetypes.guess_type(str(file))[0] or 'application/octet-stream')
                self.end_headers()
                self.wfile.write(file.read_bytes())

            def do_POST(self):
                path = urlparse(self.path).path
                operation = {'/expression_gallery/taxonomy': taxonomy.mutate,
                             '/expression_gallery/annotations': taxonomy.annotate,
                             '/expression_gallery/custom/name': media.edit_name,
                             '/expression_gallery/manage/plan': media.plan,
                             '/expression_gallery/manage/apply': media.apply}.get(path)
                if operation is None and path != '/expression_gallery/upload':
                    return self.send_error(404)
                try:
                    raw = self.rfile.read(int(self.headers['Content-Length']))
                    if path == '/expression_gallery/upload':
                        message = BytesParser(policy=default).parsebytes(
                            ('Content-Type: ' + self.headers['Content-Type'] + '\r\n\r\n').encode() + raw)
                        parts = {part.get_param('name', header='content-disposition'): part for part in message.iter_parts()}
                        row = media.import_image(target, parts['image'].get_payload(decode=True),
                            filename=parts['image'].get_filename(),
                            metadata=json.loads(parts['metadata'].get_payload(decode=True)))
                        return self.json_response({'id': row['id']}, 201)
                    body = json.loads(raw)
                    rows = catalog.raw_records() if path in {'/expression_gallery/taxonomy', '/expression_gallery/annotations'} else catalog.source_rows()
                    result = operation(target, rows, body)
                    self.json_response(result)
                except taxonomy.Conflict as error:
                    self.json_response({'error': str(error)}, 409)
                except media.MediaError as error:
                    self.json_response({'error': error.code}, error.status)
                except (ValueError, TypeError) as error:
                    self.json_response({'error': str(error)}, 400)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
        print(f'Fixture ready: http://127.0.0.1:{args.port}/expression_gallery/gallery', flush=True)
        server.serve_forever()


if __name__ == '__main__':
    main()
