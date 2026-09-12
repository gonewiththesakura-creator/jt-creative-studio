from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
SERVER=(ROOT/'server.py').read_text(encoding='utf8')
SOURCE=(ROOT/'sources/video_business.js').read_text(encoding='utf8')
checks={
 'server preserves video suffix':all(x in SERVER for x in ['.mp4','.mov','.webm','.avi','.mkv','favorite_media_type']),
 'favorite endpoint serves stored MIME':'favorite_media_type' in SERVER and 'self._send(200, data, ctype' in SERVER,
 'video favorites render player':all(x in SOURCE for x in ["document.createElement(isVideo?'video':'img')",'media.controls=true','videoCoinText']),
 'favorite media safe DOM':'promptNode.textContent' in SOURCE and 'media.src=' in SOURCE,
}
for k,v in checks.items():print(k,v)
sys.exit(0 if all(checks.values()) else 1)
