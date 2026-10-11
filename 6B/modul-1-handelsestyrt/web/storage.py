"""Blob Storage via hanterad identitet. Inga lagringsnycklar används."""
import json
import os
from email.utils import formatdate
import urllib.parse
import urllib.request

ACCOUNT = os.environ['STORAGE_ACCOUNT']
CONTAINER = os.environ.get('STORAGE_CONTAINER', 'arenden')
CLIENT_ID = os.environ['MANAGED_IDENTITY_CLIENT_ID']


def token(client_id=CLIENT_ID):
    query = urllib.parse.urlencode({
        'api-version': '2018-02-01',
        'resource': 'https://storage.azure.com/',
        'client_id': client_id,
    })
    request = urllib.request.Request(
        'http://169.254.169.254/metadata/identity/oauth2/token?' + query,
        headers={'Metadata': 'true'},
    )
    # Anropa IMDS direkt; skicka aldrig tokenbegäran till en HTTP-proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=10) as response:
        return json.load(response)['access_token']


def blob_request(method, name, data=None, content_type='application/octet-stream',
                 client_id=CLIENT_ID, container=CONTAINER):
    path = urllib.parse.quote(name, safe='/')
    url = f'https://{ACCOUNT}.blob.core.windows.net/{container}/{path}'
    headers = {'Authorization': 'Bearer ' + token(client_id),
               'x-ms-version': '2023-11-03',
               'x-ms-date': formatdate(usegmt=True)}
    if method == 'PUT':
        headers.update({'x-ms-blob-type': 'BlockBlob',
                        'Content-Type': content_type,
                        'If-None-Match': '*'})
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    # HTTPS-certifikatet kontrolleras av Pythons normala TLS-hantering.
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.status, response.read()


def save_blob(name, data, content_type):
    status, _ = blob_request('PUT', name, data, content_type)
    if status != 201:
        raise RuntimeError('Lagringen bekräftade inte uppladdningen.')
