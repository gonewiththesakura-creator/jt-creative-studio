import os, re
p = os.path.expandvars(r"%LOCALAPPDATA%\Temp\pub_index.html")
s = open(p, encoding="utf-8", errors="replace").read()
print("total bytes:", len(s))
for m in re.finditer(r'<section[^>]*class="panel switch"[^>]*>(.*?)</section>', s, re.S):
    frag = m.group(0)[:300]
    texts = re.findall(r">([^<>]{2,40})<", frag)
    print("--- section texts:", [t.strip() for t in texts if t.strip()][:10])
print()
print("has 视频生成面板:", "视频生成面板" in s)
print("has 原始铅绘:", "原始铅绘" in s)
print("has navSwitch:", "navSwitch" in s)
print("has original-link:", "original-link" in s)
