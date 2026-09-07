from pathlib import Path
import sys
ROOT=Path(r"D:/LAN-Share/lora/_work/comfy_panel")
SERVER=(ROOT/"server.py").read_text(encoding="utf8")
NAMES=("promptgen.html","original_sketch.html","original_graphic.html","video.html","realism.html")
PAGES=[(ROOT/"static"/name).read_text(encoding="utf8") for name in NAMES]
BUILDERS='\n'.join((ROOT/name).read_text(encoding="utf8") for name in ("build_unified_three_styles.py","build_original_style_pages.py","build_video_workbench.py","build_realism_workbench.py"))
ROUTES="['/','/original-sketch','/original-graphic','/realism','/video']"
checks={
 "server negotiates gzip":all(x in SERVER for x in ['Accept-Encoding','Content-Encoding','gzip.compress']),
 "static etag and 304":all(x in SERVER for x in ['ETag','If-None-Match','HTTPStatus.NOT_MODIFIED']),
 "immutable media cache preserved":'private, max-age=86400' in SERVER and 'public, max-age=86400' in SERVER,
 "html cache revalidates":'no-cache' in SERVER and 'must-revalidate' in SERVER,
 "conditional route prefetch":all(all(x in page for x in ['scheduleRoutePrefetch','navigator.connection','saveData','effectiveType','requestIdleCallback']) for page in PAGES[:4]),
 "prefetch only unified creator routes":all(ROUTES in page for page in PAGES[:4]),
 "no legacy realcomic prefetch":all('/realcomic' not in page.split('CREATOR_ROUTES',1)[-1].split(';',1)[0] for page in PAGES[:4]),
 "active job persisted by backend":all(all(x in page for x in ['sessionStorage','activeJobKey','generation_backend']) for page in PAGES[:3]),
 "resume polls without resubmit":all('resumeActiveJobs' in page and "'/api/job/'" in page and 'submitGenerateResilient' in page for page in PAGES[:3]),
 "cloud local resume concurrently":all("Promise.all(['cloud','local'].map(resumeActiveJob))" in page for page in PAGES[:3]),
 "completed recovery restores result":all('resumeActiveJobs' in page and ('addResult(j' in page or 'cloudAddResult(j' in page) for page in PAGES[:3]),
 "builders own performance helpers":all(x in BUILDERS for x in ['scheduleRoutePrefetch','sessionStorage','/api/job/']),
 "result images lazy decode":all('loading="lazy"' in page and 'decoding="async"' in page for page in PAGES[:3]),
 "hidden legacy grid is released":all('legacyGrid.replaceChildren()' in page and 'legacyOriginalRender()' not in page for page in PAGES[1:3]),
 "initial legacy grid is released":all("setResultTab('cloud');render();scheduleRoutePrefetch()" in page for page in PAGES[1:3]),
}
for name,value in checks.items():print(name,value)
sys.exit(0 if all(checks.values()) else 1)
