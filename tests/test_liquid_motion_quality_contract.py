from pathlib import Path
import sys

ROOT=Path(r"D:/LAN-Share/lora/_work/comfy_panel")
PAGES=[(ROOT/"static"/name).read_text(encoding="utf8") for name in ("promptgen.html","original_sketch.html","original_graphic.html")]
BUILDERS=[(ROOT/name).read_text(encoding="utf8") for name in ("build_unified_three_styles.py","build_original_style_pages.py")]
checks={
 "raf liquid controller":all("requestAnimationFrame" in page and "liquidMotionState" in page and "renderLiquidFrame" in page for page in PAGES),
 "visual progress never exceeds backend target":all("Math.min(state.target" in page and "dataset.progressTarget" in page for page in PAGES),
 "large jumps get visible bounded interpolation":all("LIQUID_MAX_DURATION" in page and "LIQUID_MIN_DURATION" in page and "Math.abs(target-state.display)" in page for page in PAGES),
 "adaptive polling samples progress frequently":all("LIQUID_POLL_INTERVAL" in page and "setTimeout(x,LIQUID_POLL_INTERVAL)" in page for page in PAGES),
 "premium dual contrast labels":all(page.count('class="liquid-label liquid-label-base"')>=2 and page.count('class="liquid-label liquid-label-fill"')>=2 and 'aria-hidden="true"' in page for page in PAGES),
 "isolated gpu friendly fluid":all("contain:paint" in page and "will-change:transform" in page and "translate3d" in page for page in PAGES),
 "purposeful restrained surface":all("liquid-meniscus" in page and "liquid-specular" in page and "bounce" not in page.lower() for page in PAGES),
 "idle canvas beats legacy primary background":'.primary.generate.liquid-button{background:#fff' in PAGES[0],
 "thin exact meniscus":all('.liquid-meniscus{position:absolute;left:-2%;right:-2%;top:-1px;height:2px' in page for page in PAGES),
 "subtle linear specular":all('linear-gradient(105deg,transparent,rgba(255,255,255,.2),transparent)' in page and 'border-radius:50%' not in page.split('.liquid-specular{',1)[1].split('}',1)[0] for page in PAGES),
 "progress labels stay legible":all('.liquid-percent{min-width:34px' in page and 'font-weight:800' in page for page in PAGES),
 "quiet solid material":all('background:color-mix(in srgb,var(--liquid-color) 78%,#667085)' in page and '0 8px 22px' not in page for page in PAGES),
 "no liquid glow":all('.liquid-meniscus' in page and 'box-shadow:none' in page.split('.liquid-meniscus{',1)[1].split('}',1)[0] for page in PAGES),
 "reduced motion keeps exact value":all("prefers-reduced-motion:reduce" in page and "LIQUID_REDUCED_MOTION" in page for page in PAGES),
 "durable builders own implementation":all("liquidMotionState" in builder and "liquid-label-fill" in builder for builder in BUILDERS),
 "no heavy motion dependency":all(token not in "\n".join(PAGES) for token in ("three.js","@react-three","gsap","ogl")),
}
for name,value in checks.items():print(name,value)
sys.exit(0 if all(checks.values()) else 1)
