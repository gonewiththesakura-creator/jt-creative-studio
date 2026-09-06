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
}
for k,v in checks.items():print(k,v)
raise SystemExit(0 if all(checks.values()) else 1)
