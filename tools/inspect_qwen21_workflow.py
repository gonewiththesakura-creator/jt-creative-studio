"""Read provider workflow graphs without submitting or uploading anything."""
import hashlib
import json
from pathlib import Path

import prepare_dreamapi_native_canary as t
from release_membership_cutover import remote_json

IDS = ('2111378115142823938', '2111383542247743489')


def main():
    client = t._connect(t.BASE / 'tools/creds.json', t.release.DEPLOY_SSH_KEY_PATH)
    try:
        result = remote_json(client, '''import json,pathlib,subprocess,urllib.request
pid=subprocess.check_output(['systemctl','show','comfy-panel','-p','MainPID','--value'],text=True).strip()
env=dict(item.split('=',1) for item in pathlib.Path('/proc/'+pid+'/environ').read_bytes().decode().split(chr(0)) if '=' in item)
key=env['RUNNINGHUB_API_KEY']; result={}
for wid in ''' + repr(IDS) + ''':
 req=urllib.request.Request('https://www.runninghub.ai/api/openapi/getJsonApiFormat',data=json.dumps({'apiKey':key,'workflowId':wid}).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
 try:
  with urllib.request.urlopen(req,timeout=35) as response: data=json.load(response)
  prompt=(data.get('data') or {}).get('prompt')
  graph=json.loads(prompt) if isinstance(prompt,str) else prompt
  result[wid]={'code':data.get('code'),'graph':graph}
 except Exception as error: result[wid]={'error_type':type(error).__name__}
print(json.dumps(result))
''', root=True)
    finally:
        client.close()
    out = t.BASE / 'audit/image-edit-workflows-20261017'
    out.mkdir(parents=True, exist_ok=True)
    for wid, value in result.items():
        graph = value.get('graph')
        if not isinstance(graph, dict):
            print(json.dumps({'workflow': wid, 'code': value.get('code'), 'error_type': value.get('error_type')}))
            continue
        raw = json.dumps(graph, ensure_ascii=False, indent=2).encode('utf-8')
        (out / (wid + '-api.json')).write_bytes(raw)
        summary = {key: {'type': node.get('class_type'), 'fields': list(node.get('inputs', {}))}
                   for key, node in graph.items()}
        print(json.dumps({'workflow': wid, 'sha256': hashlib.sha256(raw).hexdigest(), 'nodes': summary}, ensure_ascii=True))


if __name__ == '__main__':
    main()
