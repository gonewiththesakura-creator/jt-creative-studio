from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
HTML=(ROOT/"static"/"promptgen.html").read_text(encoding="utf8")
SERVER=(ROOT/"server.py").read_text(encoding="utf8")
CONFIG=(ROOT/"config.json").read_text(encoding="utf8")
checks={
 "prompt mode selector": 'id="promptMode"' in HTML and '选项组合' in HTML and '手动提示词' in HTML,
 "manual positive input": 'id="manualPositive"' in HTML,
 "manual negative input": 'id="manualNegative"' in HTML,
 "manual panel toggles": 'updatePromptModeUI' in HTML,
 "manual prompt drives generation": "promptMode.value==='manual'?manualPositive.value.trim():buildCorePrompt()" in HTML,
 "negative drives generation": "promptMode.value==='manual'?manualNegative.value.trim():cfg().negative" in HTML,
 "request sends prompt fields": all(x in HTML for x in ['negative_prompt:negative','prompt_mode:promptMode.value']),
 "seed mode visible": 'id="seedMode"' in HTML and 'id="genSeed"' in HTML,
 "random and fixed seed modes": '每次随机' in HTML and '>固定<' in HTML,
 "random seed materialized": 'function newRandomSeed()' in HTML and "seedMode.value==='random'" in HTML,
 "request sends seed": all(x in HTML for x in ['seed:seed','seed_mode:seedMode.value']),
 "snapshot stores prompt and seed": all(x in HTML for x in ['prompt_mode:promptMode.value','manual_positive:manualPositive.value','manual_negative:manualNegative.value','seed:+genSeed.value','seed_mode:seedMode.value']),
 "snapshot restores prompt and seed": all(x in HTML for x in ['promptMode.value=snapshot.prompt_mode','manualPositive.value=snapshot.manual_positive','manualNegative.value=snapshot.manual_negative','genSeed.value=snapshot.seed','seedMode.value=snapshot.seed_mode']),
 "batch semantics ordinary": 'id="batchNote" style="display:none"' in HTML and 'genBatch.disabled=false' in HTML,
 "sequence retired": 'id="sketchProcess"' not in HTML and "const sequence_mode='off'" in HTML,
 "server sends negative node": 'set_field("negative", job.get("negative_prompt", ""))' in SERVER,
 "server materializes missing seed": 'secrets.randbelow(2**53 - 1) + 1' in SERVER,
 "server avoids duplicate trigger": 'prepend_trigger_once' in SERVER,
 "job stores prompt mode negative seed mode": all(x in SERVER for x in ['"negative_prompt": negative_prompt','"prompt_mode": prompt_mode','"seed_mode": seed_mode']),
 "job endpoint exposes fields": all(x in SERVER for x in ['"negative_prompt", "prompt_mode", "seed", "seed_mode"']),
 "favorite stores seed directly": all(x in SERVER for x in ['"seed": job.get("seed")','"seed_mode": job.get("seed_mode")','"negative_prompt": job.get("negative_prompt", "")','"prompt_mode": job.get("prompt_mode", "options")']),
 "native batch node map": '"batch_size"' in CONFIG,
 "staged mode retired": 'stage_job["batch"] = 1' not in SERVER and 'sequence_mode = "off"' in SERVER,
}
for k,v in checks.items():print(k,v)
sys.exit(0 if all(checks.values()) else 1)
