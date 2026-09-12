from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PAGES = {
    name: (ROOT / "static" / name).read_text(encoding="utf8")
    for name in [
        "index.html",
        "promptgen.html",
        "original_sketch.html",
        "original_graphic.html",
        "video.html",
    ]
}
MAIN = PAGES["promptgen.html"]

checks = {
    "root and legacy page remain byte-identical": (ROOT / "static" / "index.html").read_bytes()
    == (ROOT / "static" / "promptgen.html").read_bytes(),
    "main declares canonical root": '<link rel="canonical" href="/">' in MAIN,
    "legacy route normalizes without reload": all(
        token in MAIN
        for token in [
            "location.pathname==='/promptgen'",
            "history.replaceState",
            "'/'+location.search+location.hash",
        ]
    ),
    "active creator pages home links use root": all(
        'href="/">' in html and 'href="/promptgen"' not in html
        for name,html in PAGES.items() if name not in ('original_sketch.html','original_graphic.html')
    ),
    "main builder owns normalization": all(
        token in (ROOT / "build_unified_three_styles.py").read_text(encoding="utf8")
        for token in ['rel="canonical" href="/"', "location.pathname==='/promptgen'", 'href="/"']
    ),
    "original builder links home to root": 'href="/promptgen"' not in (
        ROOT / "build_original_style_pages.py"
    ).read_text(encoding="utf8"),
    "video builder links home to root": 'href="/promptgen"' not in (
        ROOT / "build_video_workbench.py"
    ).read_text(encoding="utf8"),
}

for name, passed in checks.items():
    print(name, passed)
sys.exit(0 if all(checks.values()) else 1)
