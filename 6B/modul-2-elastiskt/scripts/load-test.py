"""Kort CPU-belastning med tidsgräns. Följ kapaciteten 1 -> 2 -> 1."""
import argparse,json,sys,time,urllib.request,urllib.error
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'modul-1-handelsestyrt/scripts'))
from deploy import az

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--resource-group',default='rg-novatrix')
    parser.add_argument('--output',required=True)
    args=parser.parse_args();group=args.resource_group
    name='vmss-novatrix-web';started=time.monotonic();samples=[];responses=[]
    ip=az('network','public-ip','show','-g',group,'-n','pip-novatrix-6b-lb')['ipAddress']
    script="""set -eu
cat >/tmp/novatrix-load.py <<'PY'
import multiprocessing,time
def busy():
    end=time.monotonic()+900
    while time.monotonic()<end: sum(i*i for i in range(10000))
if __name__=='__main__':
    workers=[multiprocessing.Process(target=busy) for _ in range(multiprocessing.cpu_count())]
    [p.start() for p in workers]
    [p.join() for p in workers]
PY
systemd-run --unit=novatrix-load --collect --property=RuntimeMaxSec=900 --property=KillMode=control-group /usr/bin/python3 /tmp/novatrix-load.py
echo NOVATRIX_LOAD_STARTED
"""
    az('vmss','run-command','invoke','-g',group,'-n',name,'--instance-id','0','--command-id','RunShellScript','--scripts',script)
    seen_two=False;stopped=False;complete=False
    try:
        deadline=time.monotonic()+1500
        while time.monotonic()<deadline:
            model=az('vmss','show','-g',group,'-n',name)
            instances=az('vmss','list-instances','-g',group,'-n',name)
            count=int(model['sku']['capacity']);ready=sum(r['provisioningState']=='Succeeded' for r in instances)
            samples.append({'time':datetime.now(timezone.utc).isoformat(),'elapsedSeconds':round(time.monotonic()-started),'capacity':count,'readyInstances':ready})
            print(f"Kapacitet {count}, färdiga instanser {ready}.",flush=True)
            if count==2 and ready==2 and not stopped:
                seen_two=True
                # ARM kan vara färdig innan webbappen på den nya instansen svarar.
                probe_deadline=min(deadline,time.monotonic()+300)
                while time.monotonic()<probe_deadline:
                    try:
                        with urllib.request.urlopen('http://'+ip+'/api/health',timeout=15) as r:
                            responses.append({'status':r.status,'instance':r.headers.get('X-Novatrix-Instance')})
                    except (urllib.error.URLError,TimeoutError):
                        time.sleep(5)
                    if len(responses)>=30 and len({r['instance'] for r in responses if r['instance']})>=2:
                        break
                    time.sleep(0.2)
                if len({r['instance'] for r in responses if r['instance']})<2:
                    raise RuntimeError('Båda instanserna svarade inte genom lastbalanseraren.')
                az('vmss','run-command','invoke','-g',group,'-n',name,'--instance-id','0','--command-id','RunShellScript',
                   '--scripts',"systemctl stop novatrix-load || true; echo NOVATRIX_LOAD_STOPPED")
                stopped=True
                print('Två instanser verifierade. CPU-belastningen stoppad.',flush=True)
            if seen_two and stopped and count==1 and ready==1:
                complete=True;break
            time.sleep(30)
    finally:
        result={'scaledOut':seen_two,'scaledIn':complete,'samples':samples,'loadBalancerResponses':responses}
        Path(args.output).write_text(json.dumps(result,indent=2),encoding='utf-8')
        if not stopped:
            az('vmss','run-command','invoke','-g',group,'-n',name,'--instance-id','0','--command-id','RunShellScript',
               '--scripts',"systemctl stop novatrix-load || true")
    if not complete: raise SystemExit('Automatisk skalning 1 -> 2 -> 1 kunde inte verifieras inom tidsgränsen.')
    if len({r['instance'] for r in responses if r['instance']})<2:
        raise SystemExit('Två instanser visades inte i lastbalanserarens svar.')
    print('Automatisk skalning 1 -> 2 -> 1 och svar från båda instanserna verifierade.',flush=True)
