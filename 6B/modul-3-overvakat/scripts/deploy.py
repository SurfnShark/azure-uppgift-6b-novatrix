"""Driftsätt larm, logginsamling och Azure Policy via ARM."""
import argparse,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'modul-1-handelsestyrt/scripts'))
from deploy import az

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--resource-group',default='rg-novatrix')
    parser.add_argument('--parameters',required=True)
    args=parser.parse_args()
    az('provider','register','-n','Microsoft.OperationalInsights','--wait')
    az('provider','register','-n','Microsoft.Insights','--wait')
    az('deployment','group','create','-g',args.resource_group,'-n','novatrix-6b-monitor',
       '--template-file',str(ROOT/'infra/main.json'),'--parameters','@'+args.parameters)
    az('vmss','update-instances','-g',args.resource_group,'-n','vmss-novatrix-web','--instance-ids','*')
    print('Monitor och policy driftsatta. Övervakningsagenten tillämpad på befintliga instanser.',flush=True)
