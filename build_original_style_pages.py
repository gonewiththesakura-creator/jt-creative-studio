from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
STATIC.mkdir(exist_ok=True)

PAGES = {
    "original_sketch.html": ("原始铅绘", "/?style=original_sketch"),
    "original_graphic.html": ("原始古风", "/?style=original_graphic"),
}

for filename, (label, target) in PAGES.items():
    html = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="0;url={target}"><title>{label}</title><style>body{{margin:0;padding:24px;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;color:#20222a;background:#f6f7fb}}a{{color:#4057e8}}</style></head><body><p>{label}已合并到<a href="{target}">创作台画风</a>。</p><script>location.replace({target!r})</script></body></html>'''
    output = STATIC / filename
    output.write_text(html, encoding="utf-8")
    print(output.name, output.stat().st_size)
