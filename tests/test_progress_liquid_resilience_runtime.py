import importlib.util
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("progress_server_test",ROOT/"server.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

# Idempotency: bind retries to both caller session and effective payload.
request_hash=m.effective_request_sha256({"workflow":"anima02","prompt":"portrait"})
session_hash=m._session_hash("session-a-1234567890")
m._jobs={
 "accepted":{"id":"accepted","status":"running","generation_backend":"local","client_request_id":"req-123","request_session_hash":session_hash,"effective_request_sha256":request_hash},
}
assert m.idempotency_decision("req-123","session-a-1234567890",request_hash)[:2]==("duplicate",m._jobs["accepted"])
other_hash=m.effective_request_sha256({"workflow":"anima02","prompt":"other"})
assert m.idempotency_decision("req-123","session-a-1234567890",other_hash)[0]=="conflict"
assert m.idempotency_decision("req-123","session-b-1234567890",request_hash)[0]=="new"

# Local transfer stage: four results advance from sample completion into a
# separately observable transfer phase instead of remaining at LOCAL_RUNNING.
job={"id":"progress-test","workflow":"anima02","prompt":"portrait","negative_prompt":"bad", "trigger":"jt_style1_v1","width":512,"height":768,"batch":4,"hd":0,"seed":123,"loras":{},"prompt_ids":[],"progress_pct":0}
records=[]
m.build_api=lambda *a,**k:{"1":{"class_type":"Test","inputs":{}}}
m.submit_job=lambda payload:"pid-progress"
def wait(job,pid,index,total):
 job["progress_pct"]=90
 records.append(("sample_done",job["progress_pct"],job.get("provider_status")))
 return [{"filename":f"image_{i}.png","subfolder":"","type":"output"} for i in range(1,5)]
m._wait_progress=wait
def fetch(im,dest):
 records.append(("fetch",job["progress_pct"],job.get("provider_status"),job.get("transfer_index"),job.get("transfer_total")))
 p=Path(dest);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b"WEBP");return p
m.fetch_preview_and_save=fetch
root=Path(tempfile.mkdtemp())
images=m.local_run_image(job,root,{})
assert len(images)==4 and job["comfy_prompt_id"]=="pid-progress"
assert job["provider_status"]=="LOCAL_PREVIEW_READY" and job["progress_pct"]==99
assert all(x["preview_url"].startswith('/api/local-preview/') and x["archive_status"]=='pending' for x in images)
assert job["transfer_index"]==4 and job["transfer_total"]==4
fetch_records=[r for r in records if r[0]=="fetch"]
assert [r[3] for r in fetch_records]==[1,2,3,4]
assert all(r[2]=="RESULT_DOWNLOADING" for r in fetch_records)
assert all(a[1]<=b[1] for a,b in zip(fetch_records,fetch_records[1:]))
assert job["transfer_started"]<=job["transfer_finished"]
print("PROGRESS_RUNTIME_OK",records,job["progress_pct"],job["provider_status"])
