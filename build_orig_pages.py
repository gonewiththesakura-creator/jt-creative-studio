"""Inject a generation panel (seed/batch/HD/favorites/history) into the two
original single-file random-prompt pages, keeping their original UI intact.
Usage: python build_orig_pages.py
"""
import pathlib

BASE = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel/static")

INJECT_TMPL = r"""
<style>
.jt-gen{margin:22px 0 10px;border:1px solid var(--line,#e8ded9);border-radius:22px;background:rgba(255,253,251,.96);padding:18px 20px;box-shadow:0 8px 24px rgba(78,60,55,.05)}
.jt-gen-head{font-size:13px;font-weight:850;color:#a4928d;letter-spacing:.06em;margin-bottom:12px}
.jt-row{display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;margin-bottom:10px}
.jt-field{display:flex;flex-direction:column;gap:5px}
.jt-field label{font-size:11px;font-weight:800;color:#a4928d}
.jt-field input,.jt-field select{border:1px solid var(--line,#e8ded9);border-radius:11px;padding:9px 10px;background:#fff;color:#5a504d;font:13px ui-monospace,Menlo,Consolas,monospace;outline:none}
.jt-gen-btn{width:100%;border:0;border-radius:18px;padding:16px;background:linear-gradient(135deg,#bf8f86,#9f7169);color:#fff;font-size:17px;font-weight:870;cursor:pointer;letter-spacing:.02em;margin-top:4px}
.jt-gen-btn:disabled{opacity:.55;cursor:wait}
.jt-status{font-size:13px;font-weight:750;color:#8d625b;margin:10px 2px;min-height:18px}
.jt-result .jt-job{border:1px solid var(--line,#e8ded9);background:#fff;border-radius:16px;padding:12px;margin:10px 0}
.jt-result img{width:100%;max-height:720px;object-fit:contain;border-radius:12px;background:#f4f4f4}
.jt-result .jt-note{font-size:12px;color:#aa9d98;margin:7px 0;line-height:1.6}
.jt-dl{display:block;width:100%;border:0;text-align:center;margin-top:7px;padding:10px;border-radius:11px;background:#f6e9e5;color:#8d625b;font-weight:750;text-decoration:none;cursor:pointer}
.jt-float{position:fixed;right:14px;z-index:60;border:1px solid var(--line,#e8ded9);border-radius:15px;padding:10px 13px;background:#fff;box-shadow:0 10px 26px rgba(78,60,55,.12);cursor:pointer;font-weight:800;color:#7d6964}
.jt-hist{bottom:18px}.jt-fav{bottom:66px}
.jt-overlay{display:none;position:fixed;inset:0;z-index:80;background:rgba(247,244,242,.98);overflow:auto;padding:15px}
.jt-overlay.open{display:block}
.jt-overlay-inner{max-width:680px;margin:auto}
.jt-overlay-head{display:flex;justify-content:space-between;align-items:center}
.jt-overlay-head h2{margin:0;font-size:20px}
.jt-close{border:0;background:none;font-size:26px;cursor:pointer;color:#8d817d}
.jt-back{display:inline-block;margin-bottom:14px;text-decoration:none;color:#8d625b;font-weight:800;font-size:13px}
</style>
<section class="jt-gen">
  <div class="jt-gen-head">🎨 直接出图（RunningHub 云端 · {STYLE_NAME}）</div>
  <div class="jt-row">
    <div class="jt-field"><label>种子模式</label><select id="jtSeedMode"><option value="random">随机</option><option value="fixed">固定</option></select></div>
    <div class="jt-field"><label>种子值</label><input id="jtSeed" type="number" min="1" max="9007199254740991" step="1"></div>
    <div class="jt-field"><label>批量</label><input id="jtBatch" type="number" min="1" max="4" value="1"></div>
    <div class="jt-field"><label>高清</label><select id="jtHd"><option value="0">否（原图）</option><option value="1">ClearReality 2×</option><option value="2">UltraSharp 2×</option></select></div>
  </div>
  <div class="jt-row">
    <div class="jt-field"><label>宽</label><input id="jtW" type="number" min="256" max="2048" step="16" value="768"></div>
    <div class="jt-field"><label>高</label><input id="jtH" type="number" min="256" max="2048" step="16" value="1024"></div>
    <div class="jt-field" style="flex:1;justify-content:flex-end"><div style="font-size:11px;color:#aa9d98;line-height:1.6">正向词取当前随机结果，触发词按 {TRIGGER} 由后端补一次；随机出的角色、姿势、背景和当前锁定项一致。</div></div>
  </div>
  <button class="jt-gen-btn" id="jtGenBtn">🎨 一键生图</button>
  <div class="jt-status" id="jtStatus"></div>
  <div class="jt-result" id="jtResult"></div>
</section>
<a class="jt-back" href="/">← 返回三画风主页</a>
<button class="jt-float jt-fav" id="jtFavOpen">♥ 收藏</button>
<button class="jt-float jt-hist" id="jtHistOpen">📁 历史</button>
<div class="jt-overlay" id="jtHistOverlay"><div class="jt-overlay-inner"><div class="jt-overlay-head"><h2>历史记录</h2><button class="jt-close">×</button></div><div id="jtHistList"></div></div></div>
<div class="jt-overlay" id="jtFavOverlay"><div class="jt-overlay-inner"><div class="jt-overlay-head"><h2>我的收藏</h2><button class="jt-close">×</button></div><div id="jtFavList"></div></div></div>
<script>
const JT_STYLE={STYLE_JSON};
const JT_TRIGGER={TRIGGER_JSON};
const jtApi=async(path,opt={})=>{const r=await fetch(path,opt);let d={};try{d=await r.json()}catch{}if(!r.ok)throw new Error(d.error||('HTTP '+r.status));return d};
const jtNewSeed=()=>Math.floor(Math.random()*9007199254740990)+1;
function jtSeed(){const m=document.getElementById('jtSeedMode').value;if(m==='random')document.getElementById('jtSeed').value=jtNewSeed();return +document.getElementById('jtSeed').value}
function jtCleanPrompt(s){return (s||'').trim()}
function jtPositive(){const b=buildPositive?buildPositive():'';const t=jtCleanPrompt(b);return t}
function jtAddResult(j,container){container.innerHTML='';(j.images||[]).forEach((im,i)=>{const w=document.createElement('div');w.className='jt-job';w.innerHTML=`${im.stage_label?'<b>'+im.stage_label+'</b>':''}<div class="jt-note">种子：${j.seed??j.sequence_seed??'未知'} · ${j.prompt_mode==='manual'?'手动Prompt':'选项组合'}</div><img src="${im.preview_url||im.url}"><button class="jt-dl jt-favbtn">♥ 收藏图片、提示词和种子</button><a class="jt-dl" target="_blank" href="${im.url}">⬇ 下载原图</a>`;w.querySelector('.jt-favbtn').onclick=async e=>{e.target.disabled=true;e.target.textContent='收藏中…';try{await jtApi('/api/favorites',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:j.id,image_index:i})});e.target.textContent='✓ 已收藏'}catch(x){e.target.disabled=false;e.target.textContent='收藏失败：'+x.message}};container.appendChild(w)})}
async function jtGenerate(){const btn=document.getElementById('jtGenBtn');if(btn.disabled)return;btn.disabled=true;const st=document.getElementById('jtStatus');st.textContent='正在提交…';document.getElementById('jtResult').innerHTML='';try{const seed=jtSeed();const positive=jtPositive();const negative=window.NEGATIVE||'';if(!positive)throw new Error('正向提示词为空，请先随机一次');const body={workflow:'anima02',prompt:positive,negative_prompt:negative,prompt_mode:'manual',width:+document.getElementById('jtW').value,height:+document.getElementById('jtH').value,batch:+document.getElementById('jtBatch').value,hd:+document.getElementById('jtHd').value,seed:seed,seed_mode:document.getElementById('jtSeedMode').value,style_id:JT_STYLE,mode:'original',sequence_mode:'off',selection_snapshot:{style:JT_STYLE,mode:'original',prompt_mode:'manual',manual_positive:positive,manual_negative:negative,seed:seed,seed_mode:document.getElementById('jtSeedMode').value,width:+document.getElementById('jtW').value,height:+document.getElementById('jtH').value,batch:+document.getElementById('jtBatch').value,hd:+document.getElementById('jtHd').value}};const r=await jtApi('/api/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});while(1){await new Promise(x=>setTimeout(x,3000));const j=await jtApi('/api/job/'+r.job_id);st.textContent=(j.provider_status||j.status)+' '+(j.progress_pct||0)+'%';if(j.status==='done'){st.textContent='✓ 完成（'+j.elapsed+'秒，种子 '+j.seed+'）';jtAddResult(j,document.getElementById('jtResult'));break}if(j.status==='error')throw new Error(j.error||'生成失败')}}catch(e){st.textContent='✗ '+e.message}finally{btn.disabled=false}}
async function jtHistory(){const l=document.getElementById('jtHistList');l.innerHTML='加载中…';const a=await jtApi('/api/jobs');l.innerHTML='';a.slice(0,10).forEach(j=>{const d=document.createElement('div');d.className='jt-job';d.innerHTML=`<b>${j.style_id==='sketch'?'铅绘':j.style_id==='graphic'?'古风':'3号'} · ${j.mode==='character'?'角色':'原创'}</b><div class="jt-note">${j.status} · ${j.width}×${j.height} · ${j.batch}张 · 种子 ${j.seed??j.sequence_seed??'未知'} · ${j.elapsed||''}秒</div><button class="jt-dl">查看图片</button>`;d.querySelector('button').onclick=()=>jtAddResult(j,d);l.appendChild(d)})}
async function jtFavorites(){const l=document.getElementById('jtFavList');l.innerHTML='加载中…';const a=await jtApi('/api/favorites');l.innerHTML='';a.forEach(f=>{const d=document.createElement('div');d.className='jt-job';d.innerHTML=`<div class="jt-note">种子：${f.seed??f.selection_snapshot?.seed??'未知'} · ${f.prompt_mode==='manual'?'手动Prompt':'选项组合'}</div><img src="${f.preview_url||f.image_url}"><button class="jt-dl jt-copy">复制完整提示词</button><a class="jt-dl" href="${f.image_url}" target="_blank">⬇ 下载收藏原图</a>`;d.querySelector('.jt-copy').onclick=()=>navigator.clipboard.writeText(f.prompt||'');l.appendChild(d)})}
document.getElementById('jtGenBtn').onclick=jtGenerate;
document.getElementById('jtSeedMode').onchange=()=>{if(document.getElementById('jtSeedMode').value==='random')document.getElementById('jtSeed').value=jtNewSeed()};
document.getElementById('jtHistOpen').onclick=()=>{document.getElementById('jtHistOverlay').classList.add('open');jtHistory()};
document.getElementById('jtFavOpen').onclick=()=>{document.getElementById('jtFavOverlay').classList.add('open');jtFavorites()};
document.querySelectorAll('.jt-close').forEach(b=>b.onclick=()=>b.closest('.jt-overlay').classList.remove('open'));
document.getElementById('jtSeed').value=jtNewSeed();
</script>
"""

def build(fname, style_id, style_name, trigger):
    p = BASE / fname
    html = p.read_text(encoding="utf-8")
    inject = (INJECT_TMPL
              .replace("{STYLE_NAME}", style_name)
              .replace("{STYLE_JSON}", f'"{style_id}"')
              .replace("{TRIGGER_JSON}", f'"{trigger}"')
              .replace("{TRIGGER}", trigger))
    # Idempotent: strip any previously injected block first, then inject once.
    marker_start = "<style>\n.jt-gen{"
    marker_end = "document.getElementById('jtSeed').value=jtNewSeed();\n</script>"
    while marker_start in html and marker_end in html:
        a = html.index(marker_start)
        b = html.index(marker_end) + len(marker_end)
        html = html[:a] + html[b:]
    if "</body>" in html:
        html = html.replace("</body>", inject + "\n</body>", 1)
    else:
        html += inject
    p.write_text(html, encoding="utf-8")
    print("injected ->", p, len(html), "bytes")

build("orig_sketch.html", "sketch", "原始铅绘", "jt_style1_v1")
build("orig_graphic.html", "graphic", "原始古风", "jt_style2_v1")
print("done")
