from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
MAIN=(ROOT/"static"/"promptgen.html").read_text(encoding="utf8")
SERVER=(ROOT/"server.py").read_text(encoding="utf8")
PAGES=[MAIN]

checks={
 "liquid accepts numeric progress":all(all(x in page for x in ['setLiquidProgress','--liquid-progress:0%','--liquid-level:calc(100% - var(--liquid-progress))']) for page in PAGES),
 "loading does not force full":all('.liquid-button.is-loading{--liquid-level:5%' not in page for page in PAGES),
 "progress initialized low":all('setLiquidProgress' in page and ',3)' in page for page in PAGES),
 "poll applies backend progress":all(all(x in page for x in ['progress_pct','setLiquidProgress','Math.max(lastProgress']) for page in PAGES),
 "retryable polling helper":all(all(x in page for x in ['pollJobResilient','连续','retry']) for page in PAGES),
 "one network blip is not job failure":all('轮询连接暂时中断' in page for page in PAGES),
 "submission carries idempotency key":all('client_request_id' in page and 'submitGenerateResilient' in page for page in PAGES),
 "server deduplicates accepted submission":all(x in SERVER for x in ['client_request_id','deduplicated','existing_job','same request already accepted']),
 "cloud never fabricates percentage from poll count":'poll_count * 3' not in SERVER and 'RH_STAGE_PROGRESS' in SERVER,
 "progress label exposed":all('liquid-percent' in page for page in PAGES),
 "server exposes transfer phase":all(x in SERVER for x in ['RESULT_TRANSFERRING','RESULT_DOWNLOADING','transfer_index','transfer_total']),
 "server records local prompt id":'job["prompt_ids"].append(pid)' in SERVER and '"prompt_ids"' in SERVER,
 "local done phase is explicit":'LOCAL_DONE' in SERVER and 'progress_pct"] = 100' in SERVER,
 "local preview first":all(x in SERVER for x in ['fetch_preview_and_save','preview="webp;55"','LOCAL_PREVIEW_READY','preview_file']),
 "original archives asynchronously":all(x in SERVER for x in ['archive_local_originals','archive_status','threading.Thread(target=archive_local_originals']),
 "original can be fetched on demand":all(x in SERVER for x in ['ensure_local_original','comfy_filename','comfy_subfolder','comfy_type']),
}
for k,v in checks.items():print(k,v)
sys.exit(0 if all(checks.values()) else 1)
