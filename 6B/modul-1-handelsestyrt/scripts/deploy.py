"""Driftsätt resurser med ARM och publicera funktionskoden med Azure CLI."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def az(*args):
    cli = shutil.which('az') or shutil.which('az.cmd')
    if not cli:
        raise RuntimeError('Azure CLI behövs.')
    embedded = Path(cli).resolve().parent.parent / 'python.exe'
    command = [str(embedded), '-X', 'utf8', '-IBm', 'azure.cli'] if embedded.exists() else [cli]
    run = subprocess.run(command + list(args), capture_output=True, encoding='utf-8',
                         env=dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8'))
    if run.returncode:
        raise RuntimeError(run.stderr)
    return json.loads(run.stdout) if run.stdout.strip() else None


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--resource-group', default='rg-novatrix')
    parser.add_argument('--parameters', required=True)
    parser.add_argument('--events-only', action='store_true')
    parser.add_argument('--code-only', action='store_true')
    options = parser.parse_args()
    values = json.loads(Path(options.parameters).read_text(encoding='utf-8-sig'))['parameters']
    if values['hostStorageName']['value'] == values['sourceStorageName']['value']:
        raise SystemExit('Värdlagring och befintlig ärendelagring måste vara olika.')
    if not options.events_only:
        if not options.code_only:
            for provider in ['Microsoft.Web', 'Microsoft.EventGrid']:
                az('provider', 'register', '-n', provider, '--wait')
            deployer = az('ad', 'signed-in-user', 'show')['id']
            with tempfile.TemporaryDirectory() as folder:
                parameters = Path(folder) / 'parameters.json'
                parameters.write_text(json.dumps({'parameters':dict(values, deployerObjectId={'value':deployer})}), encoding='utf-8')
                az('deployment', 'group', 'create', '-g', options.resource_group, '-n', 'novatrix-6b-infra',
                   '--template-file', str(ROOT / 'infra/main.json'), '--parameters', '@' + str(parameters))
            print('ARM-resurser driftsatta.', flush=True)
        with tempfile.TemporaryDirectory() as folder:
            packages = Path(folder) / '.python_packages' / 'lib' / 'site-packages'
            subprocess.run([sys.executable, '-m', 'pip', 'install', '--target', str(packages),
                            '--platform', 'manylinux2014_x86_64', '--implementation', 'cp',
                            '--python-version', '311', '--only-binary=:all:',
                            '-r', str(ROOT / 'function/requirements.txt')], check=True)
            package = Path(folder) / 'released-package.zip'
            with zipfile.ZipFile(package, 'w', zipfile.ZIP_DEFLATED) as archive:
                for file in (ROOT / 'function').iterdir():
                    if file.is_file():
                        archive.write(file, file.name)
                for file in packages.rglob('*'):
                    if file.is_file():
                        archive.write(file, str(file.relative_to(Path(folder))))
            az('functionapp', 'deployment', 'source', 'config-zip', '-g', options.resource_group,
               '-n', values['functionName']['value'], '--src', str(package), '--timeout', '300')
        az('functionapp', 'restart', '-g', options.resource_group, '-n', values['functionName']['value'])
        app_id = az('functionapp', 'show', '-g', options.resource_group, '-n', values['functionName']['value'])['id']
        deadline = time.monotonic() + 600
        while True:
            try:
                az('rest', '--method', 'post', '--uri', app_id + '/syncfunctiontriggers?api-version=2024-04-01')
                break
            except RuntimeError:
                if time.monotonic() >= deadline:
                    raise
                print('Väntar på att funktionsvärden ska starta.', flush=True)
                time.sleep(15)
        deadline = time.monotonic() + 600
        while True:
            functions = az('functionapp', 'function', 'list', '-g', options.resource_group,
                           '-n', values['functionName']['value'])
            if any(item['name'].split('/')[-1] == 'NotifyOnTicket' for item in functions):
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('NotifyOnTicket hittades inte. Kontrollera värdens startlogg innan Event Grid kopplas in.')
            print('Väntar på att Azure ska hitta NotifyOnTicket.', flush=True)
            time.sleep(15)
        print('NotifyOnTicket publicerad och hittad i Azure. Kör --events-only.', flush=True)
    else:
        az('storage', 'account', 'update', '-g', options.resource_group,
           '-n', values['sourceStorageName']['value'], '--bypass', 'AzureServices')
        event_values = {key:values[key] for key in ['functionName', 'sourceStorageName']}
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'events.parameters.json'
            file.write_text(json.dumps({'parameters':event_values}), encoding='utf-8')
            az('deployment', 'group', 'create', '-g', options.resource_group, '-n', 'novatrix-6b-events',
               '--template-file', str(ROOT / 'infra/events.json'), '--parameters', '@' + str(file))
        print('Event Grid-kopplingen driftsatt som ARM.', flush=True)
