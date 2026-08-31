import re, hashlib
base = r"D:\LAN-Share\lora\_work\comfy_panel\static"
for f in ["index.html", "promptgen.html"]:
    s = open(base + "\\" + f, encoding="utf-8", errors="replace").read()
    print("=" * 20, f, len(s), "bytes, md5", hashlib.md5(s.encode("utf-8")).hexdigest()[:12])
    print("  navSwitch:", "navSwitch" in s)
    print("  original-link:", "original-link" in s)
    print("  /original-sketch:", "/original-sketch" in s)
    print("  /video:", "/video" in s)
    print("  orig_sketch:", "orig_sketch" in s)
    print("  video.html:", "video.html" in s)
    print("  视频:", "视频" in s)
    # find styleSwitch section
    m = re.search(r'<section[^>]*id="styleSwitch"[^>]*>(.*?)</section>', s, re.S)
    if m:
        print("  styleSwitch:", m.group(0)[:400])
    print()
