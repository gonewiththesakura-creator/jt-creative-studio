"""Build optimized workflow/style previews from user-provided source images."""
from pathlib import Path
from PIL import Image, ImageOps, ImageChops, ImageStat
import argparse, hashlib, json, math

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description="Build preview assets from reviewed source images")
parser.add_argument("--source-dir", type=Path, required=True,
                    help="directory containing the named workflow/style source images")
parser.add_argument("--retro-source", type=Path, required=True,
                    help="reviewed retro manga preview PNG")
args = parser.parse_args()
SOURCE = args.source_dir.resolve()
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
EXTRA_MAPPING = {
    args.retro_source.resolve(): "style-retro-manga-luxury.webp",
}

rows = []
sources = [(SOURCE / source_name, output_name) for source_name, output_name in MAPPING.items()]
sources.extend(EXTRA_MAPPING.items())
for src, output_name in sources:
    if not src.is_file():
        raise FileNotFoundError(src)
    with Image.open(src) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        original_size = image.size
        image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        dest = OUT / output_name
        lossless_full = output_name == "style-retro-manga-luxury.webp"
        if lossless_full:
            image.save(dest, "WEBP", lossless=True, method=6)
        else:
            image.save(dest, "WEBP", quality=86, method=6)
        thumb = image.copy()
        thumb_bound = (420, 420) if lossless_full else (640, 640)
        thumb.thumbnail(thumb_bound, Image.Resampling.LANCZOS)
        thumb_dest = OUT / output_name.replace(".webp", ".thumb.webp")
        thumb_quality = 90 if lossless_full else 84
        thumb.save(thumb_dest, "WEBP", quality=thumb_quality, method=6)
        with Image.open(thumb_dest) as decoded:
            decoded = decoded.convert("RGB")
            reference = image.copy()
            reference.thumbnail(thumb_bound, Image.Resampling.LANCZOS)
            rms = ImageStat.Stat(ImageChops.difference(reference, decoded)).rms
            mse = sum(value * value for value in rms) / len(rms)
            psnr = 99.0 if mse == 0 else 10*math.log10((255**2)/mse)
    rows.append({
        "output": output_name,
        "original_size": original_size,
        "preview_size": image.size,
        "bytes": dest.stat().st_size,
        "sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
        "thumb_output": thumb_dest.name,
        "thumb_size": thumb.size,
        "thumb_bytes": thumb_dest.stat().st_size,
        "thumb_sha256": hashlib.sha256(thumb_dest.read_bytes()).hexdigest(),
        "thumb_psnr_db": round(psnr, 2),
        "full_lossless": lossless_full,
        "thumb_quality": thumb_quality,
    })
(OUT / "manifest.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"count": len(rows), "total_bytes": sum(row["bytes"] for row in rows), "rows": rows}, ensure_ascii=False, indent=2))
