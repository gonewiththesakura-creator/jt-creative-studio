from pathlib import Path
import sys
ROOT=Path(r"D:/LAN-Share/lora/_work/comfy_panel")
SERVER=(ROOT/"server.py").read_text(encoding="utf8")
MAIN=(ROOT/"static"/"promptgen.html").read_text(encoding="utf8")

TPL=(ROOT/"templates"/"anima02_notrans.json").read_text(encoding="utf8")
checks={
 "main has cloud and local buttons":all(x in MAIN for x in ['id="genCloudBtn"','id="genLocalBtn"','☁ 云端生图','本地生成']),
 "original styles share two buttons":all(x in MAIN for x in ['data-style="original_sketch"','data-style="original_graphic"','id="genCloudBtn"','id="genLocalBtn"']),
 "button colors":'--liquid-color:#536cff' in MAIN and '--liquid-color:#3c9b82' in MAIN,
 "browser requests backend":'generation_backend:backend' in MAIN,
 "separate status and result panes":all(x in MAIN for x in ['data-result-panel="cloud"','data-result-panel="local"','云端结果','本地结果']),
 "parallel frontend state":"{cloud:false,local:false}" in MAIN,
 "history shows backend":'generation_backend' in MAIN and "==='local'?'本地':'云端'" in MAIN,
 "server validates backend":'generation_backend not in ("cloud", "local")' in SERVER and 'unknown generation_backend' in SERVER,
 "server stores backend":'"generation_backend": generation_backend' in SERVER,
 "server exposes backend":'"generation_backend"' in SERVER,
 "favorite stores backend":'"generation_backend": job.get("generation_backend", "cloud")' in SERVER,
 "separate backend occupancy":'_running_job_id(generation_backend)' in SERVER and '_submit_locks[generation_backend]' in SERVER,
 "cloud route explicit":'generation_backend == "cloud"' in SERVER,
 "local route explicit":'generation_backend == "local"' in SERVER,
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
