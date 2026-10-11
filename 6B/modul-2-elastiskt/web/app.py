"""Enkel labbserver bakom Nginx. Körs endast på loopback."""
import json
import logging
import mimetypes
import re
import uuid
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from storage import save_blob

MAX_BODY = 2 * 1024 * 1024
MAX_FILE = 1024 * 1024
ALLOWED = {'.txt', '.pdf', '.png', '.jpg', '.jpeg'}


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, value):
        body = json.dumps(value, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == '/api/health':
            self.reply(200, {'status': 'ok'})
        else:
            self.reply(404, {'error': 'Sidan finns inte.'})

    def do_POST(self):
        if self.path != '/api/tickets':
            return self.reply(404, {'error': 'Sidan finns inte.'})
        try:
            origin = self.headers.get('Origin')
            host = self.headers.get('Host', '')
            if origin and origin not in ('http://' + host, 'https://' + host):
                return self.reply(403, {'error': 'Otillåten avsändare.'})
            length = int(self.headers.get('Content-Length', '0'))
            content_type = self.headers.get('Content-Type', '')
            if not 0 < length <= MAX_BODY:
                return self.reply(413, {'error': 'För stor eller tom begäran.'})
            if not content_type.startswith('multipart/form-data'):
                return self.reply(400, {'error': 'Formulärdata krävs.'})
            if '\r' in content_type or '\n' in content_type or len(content_type) > 300:
                return self.reply(400, {'error': 'Felaktigt formulär.'})
            body = self.rfile.read(length)
            if len(body) != length:
                return self.reply(400, {'error': 'Ofullständig begäran.'})
            message = BytesParser(policy=policy.default).parsebytes(
                ('Content-Type: ' + content_type + '\r\nMIME-Version: 1.0\r\n\r\n').encode('ascii') + body)
            if not message.is_multipart():
                return self.reply(400, {'error': 'Felaktigt formulär.'})
            fields = {}; attachment = None
            for part in message.iter_parts():
                name = part.get_param('name', header='content-disposition')
                filename = part.get_filename()
                data = part.get_payload(decode=True) or b''
                if filename and name == 'attachment':
                    if attachment is not None:
                        return self.reply(400, {'error': 'Endast en bilaga tillåts.'})
                    extension = Path(filename).suffix.lower()
                    if extension not in ALLOWED or len(data) > MAX_FILE:
                        return self.reply(400, {'error': 'Bilagan måste vara txt, pdf, png eller jpg och högst 1 MB.'})
                    attachment = (extension, data)
                elif name in ('name', 'email', 'message'):
                    if name in fields:
                        return self.reply(400, {'error': 'Dubbla formulärfält.'})
                    fields[name] = data.decode('utf-8').strip()
            if not all(fields.get(key) for key in ('name', 'email', 'message')):
                return self.reply(400, {'error': 'Fyll i namn, e-post och meddelande.'})
            if len(fields['name']) > 100 or len(fields['email']) > 254 or len(fields['message']) > 4000:
                return self.reply(400, {'error': 'Ett formulärfält är för långt.'})
            if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', fields['email']):
                return self.reply(400, {'error': 'Ange en giltig e-postadress.'})
            ticket = uuid.uuid4().hex
            record = {'id': ticket, **fields, 'attachment': None}
            if attachment:
                extension, data = attachment
                blob_name = f'{ticket}/bilaga{extension}'
                save_blob(blob_name, data, mimetypes.guess_type(blob_name)[0] or 'application/octet-stream')
                record['attachment'] = blob_name
            save_blob(f'{ticket}/arende.json', json.dumps(record, ensure_ascii=False).encode('utf-8'), 'application/json; charset=utf-8')
            notification = 'event_pending'
            text = 'Ditt ärende och eventuell bilaga har sparats. Azure behandlar ärendenotisen.'
            self.reply(201, {'id': ticket, 'notification': notification, 'message': text})
        except (ValueError, UnicodeError):
            self.reply(400, {'error': 'Felaktigt formulär.'})
        except (HTTPError, URLError, TimeoutError, OSError, RuntimeError):
            logging.exception('Lagringen kunde inte bekräfta ärendet')
            self.reply(503, {'error': 'Ärendet kunde inte sparas. Försök igen senare.'})

    def log_message(self, format, *args):
        # Formulärinnehåll, e-post och token skrivs aldrig i HTTP-loggen.
        logging.info('%s', format % args)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    ThreadingHTTPServer(('127.0.0.1', 8080), Handler).serve_forever()
