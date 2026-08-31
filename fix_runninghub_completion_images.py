from pathlib import Path

ROOT = Path(r"D:/LAN-Share/lora/_work/comfy_panel")
SERVER = ROOT / "server.py"
HTMLS = [ROOT / "static" / "promptgen.html", ROOT / "static" / "index.html"]

s = SERVER.read_text(encoding="utf-8")

old_submit = '''def rh_submit(workflow_id, node_info_list, instance_type="default", use_personal_queue="false"):
    """提交 RunningHub 任务，返回 taskId"""
    url = f"{RH_BASE}/run/workflow/{workflow_id}"
    body = {
        "addMetadata": False,
        "nodeInfoList": node_info_list,
        "instanceType": instance_type,
        "usePersonalQueue": use_personal_queue,
    }
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {RH_KEY}"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=RH_TIMEOUT_SUBMIT) as resp:
            r = json.loads(resp.read().decode())
    except Exception as e:
        raise RuntimeError(f"RH submit failed: {e}")
    if r.get("status") != "RUNNING":
        raise RuntimeError(f"RH submit error: {r.get('errorCode')} {r.get('errorMessage')}")
    return r["taskId"]'''
new_submit = '''def rh_submit(workflow_id, node_info_list, instance_type="default", use_personal_queue="false"):
    """Submit a RunningHub task. Retry only transient/busy responses."""
    url = f"{RH_BASE}/run/workflow/{workflow_id}"
    body = {
        "addMetadata": False,
        "nodeInfoList": node_info_list,
        "instanceType": instance_type,
        "usePersonalQueue": use_personal_queue,
    }
    last = None
    for attempt in range(3):
        req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {RH_KEY}"},
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=RH_TIMEOUT_SUBMIT) as resp:
                raw = resp.read().decode(errors="replace")
                r = json.loads(raw)
        except Exception as e:
            last = f"transport: {e}"
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            raise RuntimeError(f"RH submit failed after 3 attempts: {last}")
        if r.get("status") == "RUNNING" and r.get("taskId"):
            return r["taskId"]
        # Preserve the real response; the previous version produced a blank
        # `RH submit error:` when RunningHub returned a different schema.
        last = json.dumps(r, ensure_ascii=False)[:600]
        code = str(r.get("errorCode") or r.get("code") or "").upper()
        msg = str(r.get("errorMessage") or r.get("message") or "").lower()
        transient = any(x in (code + " " + msg) for x in ("BUSY", "QUEUE", "RATE", "TOO MANY", "TEMPORARY", "TIMEOUT"))
        if transient and attempt < 2:
            time.sleep(2 * (attempt + 1))
            continue
        raise RuntimeError(f"RH submit rejected: {last}")
    raise RuntimeError(f"RH submit failed: {last}")'''
if old_submit not in s: raise RuntimeError('rh_submit block missing')
s=s.replace(old_submit,new_submit,1)

old_loop = '''    while time.time() < deadline:
        status, results = rh_query(task_id)
        job["progress_pct"] = min(95, 10 + int((deadline - time.time()) / 1800 * 80))
        if status == "SUCCESS":
            job["progress_pct"] = 100
            for im in results:
                url = im.get("url", "")
                if not url:
                    continue
                fname = f"rh_{task_id}_{len(images)+1}.png"
                try:
                    data = http_bytes(url, timeout=120)
                    p = jobdir / fname
                    p.write_bytes(data)
                    images.append({"url": f"/api/image/{job['id']}/{fname}", "file": fname, "size": len(data)})
                except Exception as e:
                    raise RuntimeError(f"RH download failed: {e}")
            job["images"] = images
            return images
        time.sleep(8)'''
new_loop = '''    poll_count = 0
    while time.time() < deadline:
        status, results = rh_query(task_id)
        poll_count += 1
        job["provider_status"] = status or "RUNNING"
        job["progress_pct"] = 15 if poll_count < 2 else min(90, 15 + poll_count * 3)
        if status == "SUCCESS":
            if not results:
                # RunningHub can expose SUCCESS before result URLs propagate.
                job["provider_status"] = "FINALIZING"
                job["progress_pct"] = 95
                time.sleep(4)
                continue
            job["provider_status"] = "DOWNLOADING"
            job["progress_pct"] = 96
            for im in results:
                url = im.get("url", "")
                if not url:
                    continue
                fname = f"rh_{task_id}_{len(images)+1}.png"
                try:
                    data = http_bytes(url, timeout=120)
                    if len(data) < 8 or data[:8] != b"\\x89PNG\\r\\n\\x1a\\n":
                        raise RuntimeError(f"invalid PNG payload ({len(data)} bytes)")
                    p = jobdir / fname
                    p.write_bytes(data)
                    images.append({"url": f"/api/image/{job['id']}/{fname}", "file": fname, "size": len(data)})
                    job["downloaded"] = len(images)
                    job["progress_pct"] = min(99, 96 + int(len(images) / max(1, len(results)) * 3))
                except Exception as e:
                    raise RuntimeError(f"RH download failed: {e}")
            if not images:
                raise RuntimeError("RH SUCCESS but no downloadable PNG result was returned")
            job["images"] = images
            job["provider_status"] = "DONE"
            return images
        time.sleep(8)'''
if old_loop not in s: raise RuntimeError('rh loop missing')
s=s.replace(old_loop,new_loop,1)

old_img = '''            try:
                rest = path.split("/api/image/", 1)[1]
                jobid, fname = rest.split("/", 1)
                p = (JOBS_DIR / jobid / fname).resolve()
                if not str(p).startswith(str((JOBS_DIR / jobid).resolve())):
                    return self._send(403, b'{"error":"bad path"}')
                data = p.read_bytes()
                self._send(200, data, "image/png", {"Content-Disposition": f'attachment; filename="{fname}"'})
            except Exception:
                self._send(404, b'{"error":"not found"}')'''
new_img = '''            try:
                rest = path.split("/api/image/", 1)[1]
                jobid, fname = rest.split("/", 1)
                p = (JOBS_DIR / jobid / fname).resolve()
                if not str(p).startswith(str((JOBS_DIR / jobid).resolve())):
                    return self._send(403, b'{"error":"bad path"}')
                data = p.read_bytes()
                self._send(200, data, "image/png", {"Content-Disposition": f'inline; filename="{fname}"',
                                                      "Cache-Control": "private, max-age=3600"})
            except (BrokenPipeError, ConnectionResetError):
                # Browser canceled an image request (navigation/refresh). The file
                # is intact; do not attempt to write a second 404 response.
                return
            except FileNotFoundError:
                self._send(404, b'{"error":"not found"}')
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)[:200]}).encode())'''
if old_img not in s: raise RuntimeError('image handler missing')
s=s.replace(old_img,new_img,1)
SERVER.write_text(s,encoding='utf8')

for path in HTMLS:
    h=path.read_text(encoding='utf8')
    h=h.replace("st.textContent = '生成中… '+p+'%';", "const phase = j.provider_status==='FINALIZING'?'云端完成，等待结果…':(j.provider_status==='DOWNLOADING'?'正在下载图片…':'云端生成中…'); st.textContent = phase+' '+p+'%';",1)
    old='''      if(j.status==='done'){
        st.textContent = '✓ 完成（'+j.elapsed+'秒）';
        for(const im of j.images){
          const b = await blobImage(im.url);
          const url = URL.createObjectURL(b);
          const wrap = document.createElement('div');
          wrap.style.marginTop='10px';
          const img = document.createElement('img');
          img.src = url;
          const dl = document.createElement('a');
          dl.className = 'dl';
          dl.href = url; dl.download = im.file;
          dl.textContent = '⬇ 下载原图';
          wrap.appendChild(img);
          wrap.appendChild(dl);
          res.appendChild(wrap);
        }
        break;
      }'''
    new='''      if(j.status==='done'){
        st.textContent = '✓ 完成（'+j.elapsed+'秒）';
        for(const im of (j.images||[])){
          const wrap = document.createElement('div');
          wrap.style.marginTop='10px';
          try{
            const b = await blobImage(im.url);
            const url = URL.createObjectURL(b);
            const img = document.createElement('img'); img.src = url;
            const dl = document.createElement('a'); dl.className='dl'; dl.href=url; dl.download=im.file; dl.textContent='⬇ 下载原图';
            wrap.appendChild(img); wrap.appendChild(dl);
          }catch(e){
            wrap.innerHTML = '<div style="color:#c14b4b;font-size:12px">图片加载失败，可点击重试</div>';
            const retry=document.createElement('a'); retry.className='dl'; retry.href=im.url; retry.target='_blank'; retry.textContent='↻ 打开/重试图片'; wrap.appendChild(retry);
          }
          res.appendChild(wrap);
        }
        if(!(j.images||[]).length) st.textContent='✗ 云端完成但没有返回可下载图片';
        break;
      }'''
    if old not in h: raise RuntimeError(f'done UI missing {path}')
    h=h.replace(old,new,1)
    h=h.replace('''        }).catch(()=>{});''','''        }).catch(e=>{
          const msg=document.createElement('div'); msg.style.cssText='color:#c14b4b;font-size:12px;margin-top:8px'; msg.textContent='图片加载失败：'+e.message;
          const retry=document.createElement('a'); retry.className='dl'; retry.href=im.url; retry.target='_blank'; retry.textContent='↻ 打开/重试图片';
          d.appendChild(msg); d.appendChild(retry);
        });''',1)
    path.write_text(h,encoding='utf8')
    print('updated',path.name)
