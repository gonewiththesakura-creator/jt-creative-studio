"""Read-only playback transport measurements; never log result URLs or credentials."""
import json
import prepare_dreamapi_native_canary as t
from release_membership_cutover import remote_json


def main():
    client = t._connect(t.BASE / 'tools/creds.json', t.release.DEPLOY_SSH_KEY_PATH)
    try:
        data = remote_json(client, '''import json,pathlib,time,sys,shutil
sys.path.insert(0, '/home/admin/comfy-panel')
from membership_media import open_media
root=pathlib.Path('/home/admin/comfy-panel/panel_data')
files=list(root.glob('*jobs*.json')); print_data={'ffprobe':bool(shutil.which('ffprobe'))}
jobs=[]
for path in files:
 data=json.loads(path.read_text()); rows=list(data.values()) if isinstance(data,dict) else data
 if isinstance(rows,list): jobs.extend(j for j in rows if isinstance(j,dict))
videos=[j for j in jobs if j.get('style_id')=='video' and j.get('status')=='done' and j.get('images')]
videos.sort(key=lambda j:j.get('created',0),reverse=True)
print_data['completed_videos']=len(videos); print_data['samples']=[]
for job in videos[:2]:
 item=job['images'][0];url=item.get('url','')
 if not url.startswith('https://'):continue
 row={'job':job['id'],'reads':[]}
 for attempt in range(2):
  start=time.monotonic();conn=None
  try:
   conn,response=open_media(url,'bytes=0-2097151',deadline=time.monotonic()+25)
   first=time.monotonic();body=response.read(2097152);end=time.monotonic()
   row['reads'].append({'status':response.status,'first_byte_seconds':round(first-start,3),'seconds':round(end-start,3),'bytes':len(body),'content_type':response.getheader('Content-Type'),'range_supported':bool(response.getheader('Content-Range')),'mp4_header':body[4:8]==b'ftyp'})
  except Exception as error:row['reads'].append({'error_type':type(error).__name__})
  finally:
   if conn:conn.close()
 print_data['samples'].append(row)
print(json.dumps(print_data))
''', root=True)
        print(json.dumps(data))
    finally:
        client.close()


if __name__ == '__main__':
    main()
