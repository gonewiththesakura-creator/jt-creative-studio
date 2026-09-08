"""Reproducibly install the two curated SCAIL2 video schemas."""
from pathlib import Path
import hashlib,json
BASE=Path(__file__).resolve().parents[1]
ATT=Path(r"C:/Users/JT/AppData/Local/hermes/attachments")
SOURCES={
 "scail2_plus":{
  "editor":"【人物替换】Scail-2+高阶工作流Plus+V4.1版【长视频+动作迁移+背景替换】.json",
  "api":"【人物替换】Scail-2+高阶工作流Plus+V4.1版【长视频+动作迁移+背景替换】_api.json",
  "editor_sha":"33f136262598be6a6ff6b6285455f69d9777fb1664bfba84317a587afc481694",
  "api_sha":"af6a7f2d76b22571ee896db3e8ca182c277eb1e14ebd171bdbaaead3f8a04828",
  "run_id":"2096841102812053505","editor_id":"2097130671957770242"},
 "scail2_multi":{
  "editor":"SCAIL2！动作迁移！角色替换！多图参考！影视二创！.json",
  "api":"SCAIL2！动作迁移！角色替换！多图参考！影视二创！_api.json",
  "editor_sha":"bbcbd044fde6a5ce8f7908a86b87c430f7a72027951b959735aa108c5b318eb3",
  "api_sha":"5c397ba441d8a2bd9edba82d5d69658d9979ac6f23da52dc9662a7327d8f2419",
  "run_id":"2096840691372924929","editor_id":"2097130786146328577"}}

def verify_sources():
 for source in SOURCES.values():
  for key in ('editor','api'):
   path=ATT/source[key]
   if hashlib.sha256(path.read_bytes()).hexdigest()!=source[key+'_sha']:raise RuntimeError('source hash mismatch: '+str(path))

def main():
 verify_sources();config_path=BASE/'config.json';config=json.loads(config_path.read_text(encoding='utf8'))
 by={w['id']:w for w in config['workflows']}
 for wid,source in SOURCES.items():
  item=by.get(wid)
  if not item:raise RuntimeError('curated schema missing: '+wid)
  if item['rh_workflow_id']!=source['run_id'] or item['source_editor_workflow_id']!=source['editor_id']:raise RuntimeError('provider id mismatch: '+wid)
  if item['source_editor_json_sha256']!=source['editor_sha'] or item['source_api_json_sha256']!=source['api_sha']:raise RuntimeError('configured source hash mismatch: '+wid)
 print(json.dumps({'verified':list(SOURCES),'schemas':{wid:{'media':len(by[wid]['rh_media']),'params':len(by[wid]['rh_params'])} for wid in SOURCES}},ensure_ascii=False))
if __name__=='__main__':main()
