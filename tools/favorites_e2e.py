import json,subprocess,time
base='http://8.210.125.65:8189'
snapshot={'state':{'character':['测试人物','test adult woman'],'hair':['测试发型','short silver bob hair']},'locked':{'hair':True}}
p={"workflow":"anima02","prompt":"1girl, solo, clearly adult woman, favorites end to end test","width":512,"height":768,"batch":1,"hd":0,"loras":{"LORA1":"05_style3_v2_step1600.safetensors","LORA2":"04_style3_step800.safetensors"},"trigger":"jt_style3_v2","selection_snapshot":snapshot}
r=json.loads(subprocess.check_output(['curl','-sS','--max-time','30','-X','POST',base+'/api/generate','-H','Content-Type: application/json','--data',json.dumps(p)],text=True));jid=r['job_id'];print('JOB',jid,flush=True)
for _ in range(60):
 j=json.loads(subprocess.check_output(['curl','-sS','--max-time','20',base+'/api/job/'+jid],text=True));print(j['status'],j.get('provider_status'),flush=True)
 if j['status']!='running':break
 time.sleep(3)
if j['status']!='done':raise SystemExit(json.dumps(j,ensure_ascii=False))
print('snapshot roundtrip',j.get('selection_snapshot')==snapshot,flush=True)
fav=json.loads(subprocess.check_output(['curl','-sS','--max-time','180','-X','POST',base+'/api/favorites','-H','Content-Type: application/json','--data',json.dumps({'job_id':jid,'image_index':0})],text=True));print('FAV',json.dumps(fav,ensure_ascii=False)[:1000],flush=True)
ls=json.loads(subprocess.check_output(['curl','-sS','--max-time','20',base+'/api/favorites'],text=True));print('listed',any(x['id']==fav['id'] for x in ls),'snapshot',fav['selection_snapshot']==snapshot,flush=True)
r2=subprocess.run(['curl','-sS','-w','%{http_code} %{size_download}','--max-time','60',base+fav['image_url'],'-o','C:/Users/JT/AppData/Local/Temp/favtest.png'],capture_output=True,text=True);print('IMAGE',r2.stdout,flush=True)
