from pathlib import Path
import gzip
import json
import sys
ROOT = Path(__file__).resolve().parents[1]
SERVER=(ROOT/"server.py").read_text(encoding="utf8")
NAMES=("promptgen.html","video.html","realism.html")
PAGES=[(ROOT/"static"/name).read_text(encoding="utf8") for name in NAMES]
BUILDERS='\n'.join((ROOT/name).read_text(encoding="utf8") for name in ("build_unified_three_styles.py","build_original_style_pages.py","build_video_workbench.py","build_realism_workbench.py"))
ROUTES="['/','/realism','/video']"
# Owner decision 2026-10-20: the standalone /promptgen page may grow to 452,000 LF bytes (was 450,000).
# About 80% of it is embedded base64 preview thumbnails; at 450,798 bytes it carries the same-account
# re-login fix and the 图片编辑 nav label. Users reach "/" through the App Shell, budgeted separately below.
CREATOR_BUDGET=452_000
# What "/" actually downloads for the creator route (module, markup, css), gzip as served. 29,728 on 2026-10-20.
# 2026-10-22: the accretion command dock (frontend/styles/accretion.css) replaces the two-column layout in shell
# pages; with legacy-only theme rules dropped and comments stripped the route measures 33,532. Budget 32,000 -> 34,000.
SHELL_CREATOR_GZIP_BUDGET=34_000
MANIFEST=json.loads((ROOT/"static"/"app-manifest.json").read_text(encoding="utf8"))
SHELL_CREATOR_GZIP=sum(len(gzip.compress((ROOT/path.lstrip('/')).read_bytes().replace(b'\r\n',b'\n'),6,mtime=0))
                       for path in MANIFEST['pages']['/'].values() if path.startswith('/static/'))
ROUTER=(ROOT/"frontend"/"router.js").read_text(encoding="utf8")
# realism.html was rebuilt as the image-edit page in 4aa41f6; since db36eeb the app shell router owns nav preloading.
PREFETCH_PAGES=[page for page in PAGES if 'scheduleRoutePrefetch' in page]
checks={
 "server negotiates gzip":all(x in SERVER for x in ['Accept-Encoding','Content-Encoding','gzip.compress']),
 "static etag and 304":all(x in SERVER for x in ['ETag','If-None-Match','HTTPStatus.NOT_MODIFIED']),
 "private media never publicly cached":'public, max-age=86400' not in SERVER and "'Cache-Control': 'private, no-store', 'Vary': 'Cookie'" in SERVER and "'private, max-age=3600' if ctype.startswith('video/') else 'private, no-store'" in SERVER,
 "html cache revalidates":'no-cache' in SERVER and 'must-revalidate' in SERVER,
 "conditional route prefetch":len(PREFETCH_PAGES)>=2 and all(all(x in page for x in ['scheduleRoutePrefetch','navigator.connection','saveData','effectiveType','requestIdleCallback']) for page in PREFETCH_PAGES),
 "app shell preloads nav routes":"a.addEventListener('pointerenter',()=>preload(a.pathname)" in ROUTER,
 "prefetch only unified creator routes":all(ROUTES in page for page in PREFETCH_PAGES),
 "no legacy realcomic prefetch":all('/realcomic' not in page.split('CREATOR_ROUTES',1)[-1].split(';',1)[0] for page in PAGES),
 "active job persisted by backend":all(x in PAGES[0] for x in ['sessionStorage','activeJobKey','generation_backend']),
 "resume polls without resubmit":'resumeActiveJobs' in PAGES[0] and "'/api/job/'" in PAGES[0] and 'submitGenerateResilient' in PAGES[0],
 "cloud local api resume concurrently":"Promise.all(['cloud','local','api'].map(resumeActiveJob))" in PAGES[0],
 "completed recovery restores result":'resumeActiveJobs' in PAGES[0] and 'addResult(j' in PAGES[0],
 "creator pages show RH coin cost":all(x in PAGES[0] for x in ['RH币：','j.rh_coins']),
 "home history server scoped":"/api/jobs?scope=creator" in PAGES[0],
 "builders own performance helpers":all(x in BUILDERS for x in ['scheduleRoutePrefetch','sessionStorage','/api/job/']),
 "result images async decode":all(x in PAGES[0] for x in ["img.decoding='async'","thumb.decoding='async'"]),
 "creator html fast boot budget":len(PAGES[0].encode('utf8'))<CREATOR_BUDGET,
 "app shell creator route gzip budget":SHELL_CREATOR_GZIP<=SHELL_CREATOR_GZIP_BUDGET,
 "creator style data hydrates after shell":all(x in PAGES[0] for x in ['STYLE_CONFIG_URL','renderBootPreview()','loadStyleConfigs().then']),
}
for name,value in checks.items():print(name,value)
print("creator html bytes",len(PAGES[0].encode('utf8')),"app shell creator route gzip",SHELL_CREATOR_GZIP)
sys.exit(0 if all(checks.values()) else 1)
