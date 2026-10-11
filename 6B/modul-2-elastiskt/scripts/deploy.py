"""Driftsätt webben som scale set och verifiera autoskalningens inställningar."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'modul-1-handelsestyrt/scripts'))
from deploy import az

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--resource-group',default='rg-novatrix')
    parser.add_argument('--parameters',required=True)
    args=parser.parse_args()
    az('provider','register','-n','Microsoft.Insights','--wait')
    az('deployment','group','create','-g',args.resource_group,'-n','novatrix-6b-vmss',
       '--template-file',str(ROOT/'infra/main.json'),'--parameters','@'+args.parameters)
    print('Scale set, lastbalanserare och autoskalning driftsatta.',flush=True)
