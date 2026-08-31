import re
p = r"D:\LAN-Share\lora\_work\comfy_panel\static\index.html"
s = open(p, encoding="utf-8", errors="replace").read()
print("bytes:", len(s))
# find styleSwitch section
for m in re.finditer(r'<section[^>]*id="styleSwitch"[^>]*>(.*?)</section>', s, re.S):
    frag = m.group(0)
    print("styleSwitch len:", len(frag))
    print("  text:", frag[:600])
print()
print("has navSwitch:", "navSwitch" in s)
print("has original-link:", "original-link" in s)
print("has /video:", "/video" in s)
print("has orig_sketch:", "orig_sketch" in s)
print("has 视频:", "视频" in s)
