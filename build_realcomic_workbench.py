from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "static" / "realcomic.html"
HTML = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="0;url=/realism?workflow=realcomic"><title>真人化</title><style>body{margin:0;padding:24px;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;color:#20222a;background:#f6f7fb}a{color:#4057e8}</style></head><body><p>漫画转真人已合并到<a href="/realism?workflow=realcomic">真人化</a>。</p><script>location.replace('/realism?workflow=realcomic')</script></body></html>'''
OUT.write_text(HTML, encoding="utf-8")
print(OUT, OUT.stat().st_size)
