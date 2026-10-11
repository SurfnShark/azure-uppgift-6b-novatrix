"""Ta bort endast modulens resurser. Befintlig VM och ärendelagring bevaras."""
import argparse
import json
import time
from pathlib import Path
from deploy import az


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--resource-group', default='rg-novatrix')
    parser.add_argument('--parameters', required=True)
    parser.add_argument('--restore-source-bypass', choices=['None', 'AzureServices', 'Logging', 'Metrics'])
    options = parser.parse_args()
    group = options.resource_group
    values = json.loads(Path(options.parameters).read_text(encoding='utf-8-sig'))['parameters']
    app = values['functionName']['value']
    host = values['hostStorageName']['value']
    source = values['sourceStorageName']['value']
    if host == source:
        raise SystemExit('Värdlagring och befintlig ärendelagring måste vara olika.')
    az('vm', 'deallocate', '-g', group, '-n', 'vm-novatrix-web')
    print('Webb-VM frigjord. Tar bort händelsekoppling och funktionsapp.', flush=True)
    resources = az('resource', 'list', '-g', group)
    def exists(name, kind):
        return any(item['name'] == name and item['type'].casefold() == kind.casefold() for item in resources)
    if exists('topic-novatrix-6b', 'Microsoft.EventGrid/systemTopics'):
        az('eventgrid', 'system-topic', 'delete', '-g', group, '-n', 'topic-novatrix-6b', '--yes')
    if options.restore_source_bypass:
        az('storage', 'account', 'update', '-g', group, '-n', source, '--bypass', options.restore_source_bypass)
    rules = az('network', 'nsg', 'rule', 'list', '-g', group, '--nsg-name', 'nsg-novatrix-private')
    if any(rule['name'] == 'Allow-6B-Function-Storage-TLS' for rule in rules):
        az('network', 'nsg', 'rule', 'delete', '-g', group, '--nsg-name', 'nsg-novatrix-private', '-n', 'Allow-6B-Function-Storage-TLS')
    if exists(app, 'Microsoft.Web/sites'):
        if az('functionapp', 'vnet-integration', 'list', '-g', group, '-n', app):
            az('functionapp', 'vnet-integration', 'remove', '-g', group, '-n', app)
        az('functionapp', 'delete', '-g', group, '-n', app, '--keep-empty-plan')
    if exists('plan-novatrix-6b', 'Microsoft.Web/serverfarms'):
        az('appservice', 'plan', 'delete', '-g', group, '-n', 'plan-novatrix-6b', '--yes')
    for service in ['blob', 'queue']:
        print('Tar bort privat anslutning och DNS för ' + service + '.', flush=True)
        endpoint = 'pe-novatrix-6b-' + service
        zone = 'privatelink.' + service + '.core.windows.net'
        if exists(endpoint, 'Microsoft.Network/privateEndpoints'):
            az('network', 'private-endpoint', 'delete', '-g', group, '-n', endpoint)
        if exists(zone, 'Microsoft.Network/privateDnsZones'):
            links = az('network', 'private-dns', 'link', 'vnet', 'list', '-g', group, '-z', zone)
            for link in links:
                if link['name'] == 'novatrix-link':
                    az('network', 'private-dns', 'link', 'vnet', 'delete', '-g', group, '-z', zone, '-n', link['name'], '--yes')
            if az('network', 'private-dns', 'link', 'vnet', 'list', '-g', group, '-z', zone):
                raise RuntimeError('DNS-zonen används av andra länkar; lämnas kvar.')
            deadline = time.monotonic() + 300
            while True:
                try:
                    az('network', 'private-dns', 'zone', 'delete', '-g', group, '-n', zone, '--yes')
                    break
                except RuntimeError as error:
                    if time.monotonic() >= deadline or not any(code in str(error) for code in ['Conflict', 'Delete', 'deletion', 'operation']):
                        raise
                    time.sleep(10)
    if exists('id-novatrix-6b', 'Microsoft.ManagedIdentity/userAssignedIdentities'):
        print('Tar bort modulens identitet och roller.', flush=True)
        identity = az('identity', 'show', '-g', group, '-n', 'id-novatrix-6b')
        assignments = az('role', 'assignment', 'list', '--assignee-object-id', identity['principalId'], '--all')
        for assignment in assignments:
            az('role', 'assignment', 'delete', '--ids', assignment['id'])
        az('identity', 'delete', '-g', group, '-n', 'id-novatrix-6b')
    for name, kind in [('acs-novatrix-6b', 'Microsoft.Communication/communicationServices'),
                       ('email-novatrix-6b', 'Microsoft.Communication/emailServices')]:
        if exists(name, kind):
            target = next(item['id'] for item in resources if item['name'] == name and item['type'].casefold() == kind.casefold())
            if kind == 'Microsoft.Communication/emailServices':
                domains = az('rest', '--method', 'get', '--url', target + '/domains?api-version=2023-03-31')['value']
                for domain in domains:
                    az('resource', 'delete', '--ids', domain['id'], '--api-version', '2023-03-31')
            az('resource', 'delete', '--ids', target)
    if exists(host, 'Microsoft.Storage/storageAccounts'):
        account = az('storage', 'account', 'show', '-g', group, '-n', host)
        deployer = az('ad', 'signed-in-user', 'show')['id']
        for assignment in az('role', 'assignment', 'list', '--all'):
            if (assignment['principalId'] == deployer
                    and assignment['scope'].casefold().startswith(account['id'].casefold() + '/')
                    and assignment['roleDefinitionId'].split('/')[-1] in [
                        '19e7f393-937e-4f77-808e-94535e297925',
                        '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1',
                        'ba92f5b4-2d11-453d-a403-e96b0029c9fe']):
                az('role', 'assignment', 'delete', '--ids', assignment['id'])
        az('storage', 'account', 'delete', '-g', group, '-n', host, '--yes')
    source_id = az('storage', 'account', 'show', '-g', group, '-n', source)['id']
    queues = az('rest', '--method', 'get', '--url', source_id + '/queueServices/default/queues?api-version=2023-05-01')['value']
    for queue in queues:
        if queue['name'] == 'webjobs-blobtrigger-poison' and queue.get('properties', {}).get('metadata', {}).get('novatrix6b') == 'true':
            az('rest', '--method', 'delete', '--url', queue['id'] + '?api-version=2023-05-01')
    vnet = values.get('vnetName', {'value':'vnet-novatrix'})['value']
    subnets = az('network', 'vnet', 'subnet', 'list', '-g', group, '--vnet-name', vnet)
    for subnet in ['snet-novatrix-functions-clean', 'snet-novatrix-functions-b1']:
        if any(item['name'] == subnet for item in subnets):
            az('network', 'vnet', 'subnet', 'delete', '-g', group, '--vnet-name', vnet, '-n', subnet)
    az('vm', 'deallocate', '-g', group, '-n', 'vm-novatrix-web')
    print('Modulens resurser borttagna och webb-VM frigjord.')
