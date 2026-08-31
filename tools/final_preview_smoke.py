import json,subprocess,time
base='http://8.210.125.65:8189'
payload={"workflow":"anima02","prompt":"1girl, solo, clearly adult woman, final preview smoke test","width":512,"height":768,"batch":1,"hd":0,"loras":{"LORA1":"05_style3_v2_step1600.safetensors","LORA2":"04_style3_step800.safetensors"},"trigger":"jt_style3_v2"}
r=json.loads(subprocess.check_output(['curl','-sS','--max-time','30','-X','POST',base+'/api/generate','-H','Content-Type: application/json','--data',json.dumps(payload)],text=True));jid=r['job_id'];print('job',jid)
for i in range(60):
 j=json.loads(subprocess.check_output(['curl','-sS','--max-time','20',base+'/api/job/'+jid],text=True));print(j['status'],j.get('provider_status'))
 if j['status']!='running':break
 time.sleep(3)
print(json.dumps(j,ensure_ascii=False)[:1800])
im=j['images'][0]
for k in ['preview_url','url']:
 rr=subprocess.run(['curl','-4','-sS','-w','%{http_code} %{time_total} %{size_download}','--max-time','60',im[k],'-o',f'C:/Users/JT/AppData/Local/Temp/{k}.img'],capture_output=True,text=True);print(k,rr.stdout)
