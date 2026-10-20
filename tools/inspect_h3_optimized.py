"""Snapshot the supplied workflows read-only; never submit or upload a task."""
import hashlib
import json
import prepare_dreamapi_native_canary as t
from release_membership_cutover import remote_json

IDS=('2111727257252290561','2112090338620891138')
OUTPUT=t.BASE/'audit/h3-optimized-20261020'


def main():
    client=t._connect(t.BASE/'tools/creds.json',t.release.DEPLOY_SSH_KEY_PATH)
    try:
        results=remote_json(client,'''import json,pathlib,subprocess,urllib.request
pid=subprocess.check_output(['systemctl','show','comfy-panel','-p','MainPID','--value'],text=True).strip()
env=dict(v.split('=',1) for v in pathlib.Path('/proc/'+pid+'/environ').read_bytes().decode().split(chr(0)) if '=' in v)
key=env['RUNNINGHUB_API_KEY'];results={}
for wid in '''+repr(IDS)+''':
 req=urllib.request.Request('https://www.runninghub.ai/api/openapi/getJsonApiFormat',data=json.dumps({'apiKey':key,'workflowId':wid}).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
 try:
  with urllib.request.urlopen(req,timeout=35) as response:data=json.load(response)
  prompt=(data.get('data') or {}).get('prompt')
  results[wid]={'code':data.get('code'),'graph':json.loads(prompt) if isinstance(prompt,str) else prompt}
 except Exception as error:results[wid]={'error_type':type(error).__name__}
print(json.dumps(results))
''',root=True)
    finally:client.close()
    OUTPUT.mkdir(parents=True,exist_ok=True)
    for wid,result in results.items():
        graph=result.get('graph')
        if not isinstance(graph,dict):
            print(json.dumps({'workflow':wid,'code':result.get('code'),'error':result.get('error_type')}));continue
        raw=json.dumps(graph,ensure_ascii=False,indent=2).encode()
        path=OUTPUT/(wid+'-api.json')
        if path.exists() and path.read_bytes()!=raw:raise RuntimeError('Existing source snapshot differs')
        path.write_bytes(raw)
        print(json.dumps({'workflow':wid,'sha256':hashlib.sha256(raw).hexdigest(),
            'nodes':{key:{'type':node['class_type'],'fields':list(node['inputs'])} for key,node in graph.items()}},ensure_ascii=False))


if __name__=='__main__':main()
