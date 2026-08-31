from pathlib import Path
import sys
ROOT=Path(r"D:/LAN-Share/lora/_work/comfy_panel")
SERVER=(ROOT/"server.py").read_text(encoding="utf8")
HTML=(ROOT/"static"/"promptgen.html").read_text(encoding="utf8")
checks={
 "restore endpoint": 'path == "/api/restore-prompt"' in SERVER,
 "bounded upload": 'MAX_RESTORE_BYTES' in SERVER and 'restore image too large' in SERVER,
 "PNG signature validation": 'PNG_SIGNATURE' in SERVER,
 "PNG text parser": 'parse_png_text_chunks' in SERVER,
 "prompt metadata extractor": 'extract_comfy_prompt_metadata' in SERVER,
 "history filename lookup": 'find_history_job_for_image' in SERVER,
 "parameter extraction": all(x in SERVER for x in ['"positive_prompt"','"negative_prompt"','"seed"','"steps"','"cfg"','"sampler_name"','"scheduler"','"models"','"loras"']),
 "restore source confidence": all(x in SERVER for x in ['"source"','"exact"','"metadata_missing"']),
 "no vision guessing": '不根据画面猜测' in SERVER,
 "upload control": 'id="restoreFile"' in HTML and 'accept="image/png,image/jpeg,image/webp"' in HTML,
 "restore button": 'id="restoreBtn"' in HTML and '从旧图恢复提示词' in HTML,
 "restore status": 'id="restoreStatus"' in HTML,
 "restore raw prompt": 'id="restoreRawPrompt"' in HTML,
 "restore parameters": 'id="restoreParams"' in HTML,
 "restore mapped selections": 'applyRecoveredPrompt' in HTML and 'mapped_selections' in HTML,
 "restore uses raw upload": "'/api/restore-prompt'" in HTML and 'application/octet-stream' in HTML,
 "unmatched terms retained": 'unmatched_fragments' in HTML,
}
for k,v in checks.items():print(k,v)
sys.exit(0 if all(checks.values()) else 1)
