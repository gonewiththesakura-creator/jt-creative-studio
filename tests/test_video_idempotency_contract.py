from pathlib import Path
ROOT=Path(r"D:/LAN-Share/lora/_work/comfy_panel")
SERVER=(ROOT/'server.py').read_text(encoding='utf-8')
SOURCE=(ROOT/'sources'/'video_business.js').read_text(encoding='utf-8')
checks={
 'dedicated video submit lock':'"video": threading.Lock()' in SERVER,
 'video requires id':'client_request_id is required' in SERVER and 'client_request_id' in SOURCE,
 'video durable pending id':all(x in SOURCE for x in ['pendingVideoSubmitKey','localStorage.getItem(pendingVideoSubmitKey','localStorage.setItem(pendingVideoSubmitKey','localStorage.removeItem(pendingVideoSubmitKey']),
 'video atomic admission':'with _submit_locks["video"]:' in SERVER and 'existing_job_for_request(client_request_id, "cloud")' in SERVER,
 'video job persists request id':'"client_request_id": client_request_id' in SERVER,
 'video favorite prompt uses safe dom':"promptNode.textContent" in SOURCE and "(f.prompt||'').slice(0,120)+'</div>" not in SOURCE,
 'favorite operation is serialized end to end':'with _favorite_operation_lock:' in SERVER and SERVER.index('with _favorite_operation_lock:') < SERVER.index('download_file_resilient(im["url"], dest') < SERVER.index('_favorites[fid] = fav'),
 'video shows RH coin cost':all(x in SOURCE for x in ['videoCoinText','RH币：','j.rh_coins']),
 'video history server scoped':"/api/jobs?scope=video" in SOURCE,
}
for k,v in checks.items():print(k,v)
raise SystemExit(0 if all(checks.values()) else 1)
