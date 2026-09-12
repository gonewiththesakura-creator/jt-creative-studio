from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SERVER=(ROOT/'server.py').read_text(encoding='utf-8')
SOURCE=(ROOT/'sources'/'video_business.js').read_text(encoding='utf-8')
checks={
 'dedicated video submit lock':'"video": threading.Lock()' in SERVER,
 'video requires id':'normalize_client_request_id(body.get("client_request_id"))' in SERVER and 'client_request_id' in SOURCE,
 'video durable pending id':all(x in SOURCE for x in ['pendingVideoSubmitKey','localStorage.getItem(pendingVideoSubmitKey','localStorage.setItem(pendingVideoSubmitKey','localStorage.removeItem(pendingVideoSubmitKey']),
 'video atomic admission':all(x in SERVER for x in ['with _idempotency_lock, _submit_locks["video"]:','idempotency_decision(','effective_request_sha256(']),
 'video job persists request id':'"client_request_id": client_request_id' in SERVER,
 'video favorite prompt uses safe dom':"promptNode.textContent" in SOURCE and "(f.prompt||'').slice(0,120)+'</div>" not in SOURCE,
 'favorite operation is serialized end to end':'with _favorite_operation_lock:' in SERVER and SERVER.index('with _favorite_operation_lock:') < SERVER.index('download_file_resilient(im["url"], dest') < SERVER.index('_favorites[fid] = fav'),
 'video shows RH coin cost':all(x in SOURCE for x in ['videoCoinText','RH币：','j.rh_coins']),
 'video history server scoped':"/api/jobs?scope=video" in SOURCE,
}
for k,v in checks.items():print(k,v)
raise SystemExit(0 if all(checks.values()) else 1)
