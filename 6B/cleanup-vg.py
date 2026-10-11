"""Städa VG-resurserna och frigör den befintliga VM:n."""
import argparse,sys,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'modul-1-handelsestyrt/scripts'))
from deploy import az

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--resource-group',default='rg-novatrix')
    parser.add_argument('--parameters',required=True)
    args=parser.parse_args();group=args.resource_group
    inventory=az('resource','list','-g',group)
    names={r['name']:r['id'] for r in inventory}
    # Remove controls before their target, and the scale set before its network.
    vmss=names.get('vmss-novatrix-web')
    if vmss:
        assignments=az('policy','assignment','list','--scope',vmss)
        for r in assignments:
            if r['name']=='novatrix-6b-lab-tag':az('policy','assignment','delete','--name',r['name'],'--scope',vmss)
    for name in ['autoscale-novatrix-6b','alert-novatrix-6b-cpu','ag-novatrix-6b',
                 'vmss-novatrix-web','dcr-novatrix-6b','law-novatrix-6b',
                 'lb-novatrix-6b','pip-novatrix-6b-lb']:
        if name in names:
            print('Tar bort '+name,flush=True)
            az('resource','delete','--ids',names[name])
    subnets=az('network','vnet','subnet','list','-g',group,'--vnet-name','vnet-novatrix')
    if any(r['name']=='snet-novatrix-vmss' for r in subnets):
        az('network','vnet','subnet','delete','-g',group,'--vnet-name','vnet-novatrix','-n','snet-novatrix-vmss')
    if 'nsg-novatrix-6b-vmss' in names:az('resource','delete','--ids',names['nsg-novatrix-6b-vmss'])
    rules=az('network','nsg','rule','list','-g',group,'--nsg-name','nsg-novatrix-private')
    if any(r['name']=='Allow-6B-VMSS-Storage-TLS' for r in rules):
        az('network','nsg','rule','delete','-g',group,'--nsg-name','nsg-novatrix-private','-n','Allow-6B-VMSS-Storage-TLS')
    subprocess.run([sys.executable,str(ROOT/'modul-1-handelsestyrt/scripts/cleanup.py'),
                    '--resource-group',group,'--parameters',args.parameters,'--restore-source-bypass','None'],check=True)
    print('VG-resurser borttagna och befintlig webb-VM frigjord.',flush=True)
