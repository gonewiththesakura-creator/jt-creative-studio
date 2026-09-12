from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
SERVER=(ROOT/"server.py").read_text(encoding="utf8")
MAIN=(ROOT/"static"/"promptgen.html").read_text(encoding="utf8")

TPL=(ROOT/"templates"/"anima02_notrans.json").read_text(encoding="utf8")
checks={
 "main has cloud local and api buttons":all(x in MAIN for x in ['id="genCloudBtn"','id="genLocalBtn"','id="genApiBtn"',"generate('cloud')","generate('local')","generate('api')"]),
 "original styles share two buttons":all(x in MAIN for x in ['data-style="original_sketch"','data-style="original_graphic"','id="genCloudBtn"','id="genLocalBtn"']),
 "button colors":'--liquid-color:#536cff' in MAIN and '--liquid-color:#3c9b82' in MAIN,
 "browser requests backend":'generation_backend:backend' in MAIN,
 "separate status and result panes":all(x in MAIN for x in ['data-result-panel="cloud"','data-result-panel="local"','云端结果','本地结果']),
 "parallel frontend state":"{cloud:false,local:false,api:false}" in MAIN and "['cloud','local','api'].map(resumeActiveJob)" in MAIN,
 "history shows backend":'generation_backend' in MAIN and 'backendUi' in MAIN,
 "server validates backend":'generation_backend not in ("cloud", "local", "api")' in SERVER and 'unknown generation_backend' in SERVER,
 "server stores backend":'"generation_backend": generation_backend' in SERVER,
 "server exposes backend":'"generation_backend"' in SERVER,
 "favorite stores backend":'"generation_backend": job.get("generation_backend", "cloud")' in SERVER,
 "separate backend occupancy":'_running_job_id(generation_backend)' in SERVER and '_submit_locks[generation_backend]' in SERVER,
 "cloud route explicit":'generation_backend == "cloud"' in SERVER,
 "local route explicit":'generation_backend == "local"' in SERVER,
 "api route explicit":'generation_backend == "api"' in SERVER and 'dreamapi_run_image' in SERVER,
 "local preset lora paths":'local_lora_name' in SERVER and 'Anima_JT\\\\' in SERVER,
 "local native batch":'local_run_image(job, jobdir, w)' in SERVER and 'batch=int(job["batch"])' in SERVER,
 "local staged route retired":'local_run_sketch_sequence' not in SERVER and 'sequence_mode = "off"' in SERVER,
 "local negative prompt":'negative_prompt=job.get("negative_prompt", "")' in SERVER,
 "notrans template accepts negative":'{{NEGATIVE}}' in TPL,
 "build api maps negative":'"{{NEGATIVE}}": negative_prompt' in SERVER,
 "local status endpoint":'"local_comfy_ok"' in SERVER,
}
for k,v in checks.items():print(k,v)
sys.exit(0 if all(checks.values()) else 1)
