from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
SERVER=(ROOT/"server.py").read_text(encoding="utf8")
NAMES=("promptgen.html","video.html","realism.html")
PAGES=[(ROOT/"static"/name).read_text(encoding="utf8") for name in NAMES]
BUILDERS='\n'.join((ROOT/name).read_text(encoding="utf8") for name in ("build_unified_three_styles.py","build_original_style_pages.py","build_video_workbench.py","build_realism_workbench.py"))
ROUTES="['/','/realism','/video']"
checks={
 "server negotiates gzip":all(x in SERVER for x in ['Accept-Encoding','Content-Encoding','gzip.compress']),
 "static etag and 304":all(x in SERVER for x in ['ETag','If-None-Match','HTTPStatus.NOT_MODIFIED']),
 "immutable media cache preserved":'private, max-age=86400' in SERVER and 'public, max-age=86400' in SERVER,
 "html cache revalidates":'no-cache' in SERVER and 'must-revalidate' in SERVER,
 "conditional route prefetch":all(all(x in page for x in ['scheduleRoutePrefetch','navigator.connection','saveData','effectiveType','requestIdleCallback']) for page in PAGES),
 "prefetch only unified creator routes":all(ROUTES in page for page in PAGES),
 "no legacy realcomic prefetch":all('/realcomic' not in page.split('CREATOR_ROUTES',1)[-1].split(';',1)[0] for page in PAGES),
 "active job persisted by backend":all(x in PAGES[0] for x in ['sessionStorage','activeJobKey','generation_backend']),
 "resume polls without resubmit":'resumeActiveJobs' in PAGES[0] and "'/api/job/'" in PAGES[0] and 'submitGenerateResilient' in PAGES[0],
 "cloud local api resume concurrently":"Promise.all(['cloud','local','api'].map(resumeActiveJob))" in PAGES[0],
 "completed recovery restores result":'resumeActiveJobs' in PAGES[0] and 'addResult(j' in PAGES[0],
 "creator pages show RH coin cost":all(x in PAGES[0] for x in ['RH币：','j.rh_coins']),
 "home history server scoped":"/api/jobs?scope=creator" in PAGES[0],
 "builders own performance helpers":all(x in BUILDERS for x in ['scheduleRoutePrefetch','sessionStorage','/api/job/']),
 "result images lazy decode":'loading="lazy"' in PAGES[0] and 'decoding="async"' in PAGES[0],
}
for name,value in checks.items():print(name,value)
sys.exit(0 if all(checks.values()) else 1)
