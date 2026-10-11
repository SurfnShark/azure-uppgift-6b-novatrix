"""Installera integrationen. Azure-händelsen startas av bloben, utan direkt flödesanrop."""
import argparse
import base64
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def az(*args):
    cli = shutil.which('az') or shutil.which('az.cmd')
    if not cli:
        raise RuntimeError('Azure CLI behövs.')
    embedded = Path(cli).resolve().parent.parent / 'python.exe'
    command = [str(embedded), '-X', 'utf8', '-IBm', 'azure.cli'] if embedded.exists() else [cli]
    result = subprocess.run(command + list(args), capture_output=True, encoding='utf-8',
                            env=dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8'))
    if result.returncode:
        raise RuntimeError('Azure-kommandot misslyckades. Kontrollera konto, behörighet och resursnamn.')
    return json.loads(result.stdout) if result.stdout.strip() else None


def script(account, client):
    app = Path(__file__).resolve().parents[1] / 'web'
    commands = ['set -eu', 'install -d -m 755 /opt/novatrix-api']
    files = {'app.py': '/opt/novatrix-api/app.py', 'storage.py': '/opt/novatrix-api/storage.py', 'index.html': '/var/www/html/index.html',
             'nginx.conf': '/etc/nginx/sites-available/default',
             'novatrix-api.service': '/etc/systemd/system/novatrix-api.service'}
    for source, target in files.items():
        encoded = base64.b64encode((app / source).read_bytes()).decode()
        commands += [f"printf '%s' '{encoded}' | base64 -d > '{target}'", f"chmod 644 '{target}'"]
    env = f'STORAGE_ACCOUNT={account}\nSTORAGE_CONTAINER=arenden\nMANAGED_IDENTITY_CLIENT_ID={client}\n'
    encoded = base64.b64encode(env.encode()).decode()
    commands += [f"printf '%s' '{encoded}' | base64 -d > /etc/novatrix-api.env",
                 'chown root:www-data /etc/novatrix-api.env', 'chmod 640 /etc/novatrix-api.env',
                 'systemctl daemon-reload', 'systemctl restart novatrix-api',
                 'nginx -t', 'systemctl reload nginx', 'systemctl is-active novatrix-api',
                 'curl --fail --silent --retry 5 --retry-delay 1 --retry-all-errors http://127.0.0.1/api/health',
                 "printf '\\nNOVATRIX_6B_INSTALL_OK\\n'"]
    return '\n'.join(commands)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--resource-group', required=True)
    parser.add_argument('--storage-account', required=True)
    parser.add_argument('--keep-running-for-test', action='store_true')
    args = parser.parse_args()
    identity = az('identity', 'show', '-g', args.resource_group, '-n', 'id-novatrix-app')
    success = False
    try:
        az('vm', 'start', '-g', args.resource_group, '-n', 'vm-novatrix-web')
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'install.sh'
            file.write_text(script(args.storage_account, identity['clientId']), encoding='utf-8')
            result = az('vm', 'run-command', 'invoke', '-g', args.resource_group, '-n', 'vm-novatrix-web',
                        '--command-id', 'RunShellScript', '--scripts', '@' + str(file))
            success = any('NOVATRIX_6B_INSTALL_OK' in x.get('message', '') for x in result.get('value', []))
            if not success:
                raise RuntimeError('Installationen kunde inte bekräftas.')
            print('Novatrix-integrationen installerad och hälsokontrollen lyckades.')
    finally:
        if not success or not args.keep_running_for_test:
            az('vm', 'deallocate', '-g', args.resource_group, '-n', 'vm-novatrix-web')
