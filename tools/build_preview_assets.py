"""Build optimized workflow/style previews from user-provided source images."""
from pathlib import Path
from PIL import Image, ImageOps
import hashlib, json

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(r"C:/Users/JT/Desktop/22")
OUT = ROOT / "static" / "previews"
OUT.mkdir(parents=True, exist_ok=True)

MAPPING = {
    "快速真人化--01：21.png": "realism-realcomic.webp",
    "Krea2_动漫转真人--03：21.png": "realism-krea2.webp",
    "动漫转写实真人2511--1：30.png": "realism-2511.webp",
    "动漫转真人·多采超清天花板--03：54.png": "realism-multisample.webp",
    "Qwen+ZI动漫转真人写实感洗图--3：46.png": "realism-qwen-zi.webp",
    "动漫转真人ZI洗图改2：02.png": "realism-zi-flowmatch.webp",
    "冷脸萌20s.png": "style-cold.webp",
    "铅绘20s.png": "style-sketch.webp",
    "原始铅绘20s.png": "style-original-sketch.webp",
    "古风--20s.png": "style-graphic.webp",
    "原始古风20s.png": "style-original-graphic.webp",
    "古漫20s.png": "style-hanmanga.webp",
    "NFF--20s.png": "style-nff.webp",
}

rows = []
for source_name, output_name in MAPPING.items():
    src = SOURCE / source_name
    if not src.is_file():
        raise FileNotFoundError(src)
    with Image.open(src) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        original_size = image.size
        image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        dest = OUT / output_name
        image.save(dest, "WEBP", quality=86, method=6)
    rows.append({
        "source": source_name,
        "source_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
        "output": output_name,
        "original_size": original_size,
        "preview_size": image.size,
        "bytes": dest.stat().st_size,
        "sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
    })
(OUT / "manifest.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"count": len(rows), "total_bytes": sum(row["bytes"] for row in rows), "rows": rows}, ensure_ascii=False, indent=2))
