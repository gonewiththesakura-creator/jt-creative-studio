from pathlib import Path
import json

ROOT=Path(r"D:/LAN-Share/lora/_work/comfy_panel")
STATIC=ROOT/"static"; STATIC.mkdir(exist_ok=True)
ATT=Path(r"C:/Users/JT/AppData/Local/hermes/attachments")

CSS=r'''
.cloud-panel{margin-top:20px;padding:20px}.cloud-head{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.cloud-head h2{margin:0}.cloud-home{display:inline-block;padding:10px 14px;border-radius:13px;background:#fff;color:#765f5a;text-decoration:none;border:1px solid var(--line);font-weight:800}.cloud-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:16px}.cloud-grid label{font-size:12px;color:var(--muted);font-weight:800}.cloud-grid input,.cloud-grid select{display:block;width:100%;margin-top:6px;border:1px solid var(--line);border-radius:11px;padding:10px;background:#fff;color:var(--ink)}.cloud-note{font-size:12px;color:var(--muted);line-height:1.65;margin-top:10px}.cloud-actions{display:grid;grid-template-columns:1fr 1fr;gap:10px}.cloud-generate{width:100%;margin-top:14px;border-radius:18px;padding:16px;background:linear-gradient(135deg,var(--accent,#bf8f86),var(--accent-dark,#9f7169));color:#fff;font-weight:850}.cloud-generate.local{background:linear-gradient(135deg,#668e86,#456e68)}.backend-results{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}.backend-result{border:1px solid var(--line);border-radius:15px;padding:10px;min-height:70px;background:rgba(255,255,255,.6)}.backend-result h3{margin:0 0 4px}.cloud-status{font-size:13px;color:#6f5c58;font-weight:750;margin:8px 0}.cloud-result img,.cloud-job img{display:block;width:100%;max-height:640px;object-fit:contain;border-radius:12px;background:#f5f3f2;margin-top:8px}.cloud-job{border:1px solid var(--line);background:#fff;border-radius:15px;padding:12px;margin:10px 0}.cloud-dl{display:block;width:100%;border:0;text-align:center;margin-top:7px;padding:10px;border-radius:10px;background:var(--accent2);color:#755b56;font-weight:750;text-decoration:none;cursor:pointer}.cloud-floating{position:fixed;right:14px;z-index:60;border:1px solid var(--line);border-radius:16px;padding:10px 13px;background:#fff;box-shadow:var(--shadow);cursor:pointer}.cloud-history-open{bottom:18px}.cloud-favorites-open{bottom:66px}.cloud-overlay{display:none;position:fixed;inset:0;z-index:90;background:rgba(247,244,242,.98);overflow:auto;padding:15px}.cloud-overlay.open{display:block}.cloud-overlay-inner{max-width:680px;margin:auto}.cloud-overlay-head{display:flex;justify-content:space-between;align-items:center}.cloud-close{border:0;background:none;font-size:25px;cursor:pointer}.cloud-setting-note{display:block;margin-top:5px;font-size:11px;color:var(--muted);line-height:1.4}@media(max-width:720px){.cloud-grid,.cloud-actions,.backend-results{grid-template-columns:1fr}}
'''

UI_BASE=r'''
<section class="panel cloud-panel" id="cloudPanel">
  <div class="cloud-head"><div><h2>云端 / 本地生图</h2><div class="cloud-note">同一套原始选项可分别提交到RunningHub，或通过反向隧道提交到你一直运行的本机ComfyUI。</div></div><a class="cloud-home" href="/promptgen">← 返回当前总主页</a></div>
  <div class="cloud-grid">
    <label>宽<input id="cloudW" type="number" value="768" min="256" max="2048" step="16"></label>
    <label>高<input id="cloudH" type="number" value="1024" min="256" max="2048" step="16"></label>
    <label>批量<input id="cloudBatch" type="number" value="1" min="1" max="4"><span class="cloud-setting-note" id="cloudBatchNote"></span></label>
    <label>高清<select id="cloudHd"><option value="0">关闭</option><option value="1">ClearReality 2×</option><option value="2">UltraSharp 2×</option></select></label>
    <label>种子模式<select id="cloudSeedMode"><option value="random">随机（显示实际值）</option><option value="fixed">固定</option></select></label>
    <label>种子值<input id="cloudSeed" type="number" min="1" max="9007199254740991" step="1"></label>
    __SEQUENCE__
  </div>
  <div class="cloud-note">LoRA与正式触发词由后端固定：<b>__TRIGGER__</b>。本页触发词框只保留原页面显示，不会篡改后端映射。</div>
  <div class="cloud-actions"><button class="cloud-generate" id="cloudGenerateCloud">☁ 云端生图</button><button class="cloud-generate local" id="cloudGenerateLocal">🖥 本地ComfyUI生图</button></div>
  <div class="backend-results"><section class="backend-result" data-backend="cloud"><h3>云端结果</h3><div class="cloud-status" id="cloudStatusCloud"></div><div class="cloud-result" id="cloudResultCloud"></div></section><section class="backend-result" data-backend="local"><h3>本地结果</h3><div class="cloud-status" id="cloudStatusLocal"></div><div class="cloud-result" id="cloudResultLocal"></div></section></div>
</section>
'''

FLOATING=r'''
<button class="cloud-floating cloud-favorites-open" id="cloudFavOpen">♥ 收藏</button><button class="cloud-floating cloud-history-open" id="cloudHistOpen">📁 历史</button>
<div class="cloud-overlay" id="cloudHistOverlay"><div class="cloud-overlay-inner"><div class="cloud-overlay-head"><h2>历史记录</h2><button class="cloud-close">×</button></div><div id="cloudHistList"></div></div></div>
<div class="cloud-overlay" id="cloudFavOverlay"><div class="cloud-overlay-inner"><div class="cloud-overlay-head"><h2>本原始页面收藏</h2><button class="cloud-close">×</button></div><div id="cloudFavList"></div></div></div>
'''

JS=r'''
<script>
const CLOUD_STYLE_ID='__STYLE__';
const CLOUD_TRIGGER='__TRIGGER__';
const CLOUD_PAGE_ID='__PAGE__';
const CLOUD_HAS_SEQUENCE=__HAS_SEQUENCE__;
let cloudRunning={cloud:false,local:false};
const cloudApi=async(path,opt={})=>{const r=await fetch(path,opt);let d={};try{d=await r.json()}catch{}if(!r.ok)throw new Error(d.error||('HTTP '+r.status));return d};
function cloudNewSeed(){return Math.floor(Math.random()*9007199254740990)+1}
function cloudStripStyleTokens(text){return String(text||'').replace(/(?<![A-Za-z0-9_])jt_style\d+_v\d+(?![A-Za-z0-9_])/gi,'').replace(/(?:\s*,\s*){2,}/g,', ').replace(/^\s*,|,\s*$/g,'').trim()}
function cloudSequenceMode(){if(!CLOUD_HAS_SEQUENCE)return'off';return cloudSequence.value==='3'?'sketch3':(cloudSequence.value==='4'?'sketch4':'off')}
function cloudUpdateBatch(){const staged=CLOUD_HAS_SEQUENCE&&cloudSequence.value!=='off';cloudBatch.disabled=staged;if(staged){cloudBatch.value=1;cloudBatchNote.textContent='分步模式：每阶段1张，共提交3/4个云任务'}else cloudBatchNote.textContent='普通出图：1个云任务，批量节点一次出N张'}
function cloudSnapshot(backend){return{source_page:CLOUD_PAGE_ID,style:CLOUD_STYLE_ID,mode:currentMode,state:JSON.parse(JSON.stringify(state)),locked:JSON.parse(JSON.stringify(locked)),trigger_input:document.getElementById('triggerInput')?.value||'',prefix_input:document.getElementById('prefixInput')?.value||'',width:+cloudW.value,height:+cloudH.value,batch:+cloudBatch.value,hd:+cloudHd.value,sequence_mode:cloudSequenceMode(),prompt_mode:'options',manual_positive:'',manual_negative:'',seed:+cloudSeed.value,seed_mode:cloudSeedMode.value,generation_backend:backend}}
function cloudApplySnapshot(s){if(!s||s.source_page!==CLOUD_PAGE_ID||!s.state)return;state=JSON.parse(JSON.stringify(s.state));locked=JSON.parse(JSON.stringify(s.locked||{}));currentMode=s.mode||'original';if(document.getElementById('triggerInput'))triggerInput.value=s.trigger_input||'';if(document.getElementById('prefixInput'))prefixInput.value=s.prefix_input||'';cloudW.value=s.width||768;cloudH.value=s.height||1024;cloudBatch.value=s.batch||1;cloudHd.value=s.hd||0;cloudSeed.value=s.seed||cloudNewSeed();cloudSeedMode.value=s.seed_mode||'fixed';if(CLOUD_HAS_SEQUENCE)cloudSequence.value=s.sequence_mode==='sketch3'?'3':(s.sequence_mode==='sketch4'?'4':'off');save();render();cloudUpdateBatch();cloudFavOverlay.classList.remove('open');window.scrollTo({top:0,behavior:'smooth'})}
function cloudAddResult(j,container){container.innerHTML='';(j.images||[]).forEach((im,i)=>{const x=document.createElement('div');x.className='cloud-job';x.innerHTML=`${im.stage_label?`<b>${im.stage_label}</b>`:''}<div class="cloud-note">${j.generation_backend==='local'?'本地':'云端'} · 种子：${j.seed??j.sequence_seed??'未知'} · ${j.width}×${j.height} · 批量${j.batch}</div><img loading="lazy" decoding="async" src="${im.preview_url||im.url}"><button class="cloud-dl cloud-fav">♥ 收藏图片、提示词和种子</button><a class="cloud-dl" target="_blank" href="${im.url}">⬇ 下载原图</a>`;x.querySelector('.cloud-fav').onclick=async e=>{e.target.disabled=true;e.target.textContent='收藏中…';try{await cloudApi('/api/favorites',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:j.id,image_index:i})});e.target.textContent='✓ 已收藏'}catch(err){e.target.disabled=false;e.target.textContent='收藏失败：'+err.message}};container.appendChild(x)})}
async function cloudGenerateNow(backend){if(cloudRunning[backend])return;cloudRunning[backend]=true;const button=backend==='local'?cloudGenerateLocal:cloudGenerateCloud;const status=backend==='local'?cloudStatusLocal:cloudStatusCloud;const result=backend==='local'?cloudResultLocal:cloudResultCloud;button.disabled=true;status.textContent='正在提交…';result.innerHTML='';try{if(cloudSeedMode.value==='random')cloudSeed.value=cloudNewSeed();const positive=cloudStripStyleTokens(buildPositive());const body={workflow:'anima02',prompt:positive,negative_prompt:NEGATIVE,prompt_mode:'options',width:+cloudW.value,height:+cloudH.value,batch:+cloudBatch.value,hd:+cloudHd.value,seed:+cloudSeed.value,seed_mode:cloudSeedMode.value,style_id:CLOUD_STYLE_ID,mode:currentMode,sequence_mode:cloudSequenceMode(),generation_backend:backend,selection_snapshot:cloudSnapshot(backend)};const r=await cloudApi('/api/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});while(1){await new Promise(x=>setTimeout(x,3000));const j=await cloudApi('/api/job/'+r.job_id);const stage=(j.stage_status||[]).find(x=>x.status==='RUNNING');status.textContent=(stage?.stage_label||j.provider_status||j.status)+' '+(j.progress_pct||0)+'%';if(j.status==='done'){status.textContent='✓ 完成（'+j.elapsed+'秒，种子 '+j.seed+'）';cloudAddResult(j,result);break}if(j.status==='error')throw new Error(j.error||'生成失败')}}catch(e){status.textContent='✗ '+e.message}finally{cloudRunning[backend]=false;button.disabled=false}}
async function cloudHistory(){cloudHistList.innerHTML='加载中…';const a=await cloudApi('/api/jobs');cloudHistList.innerHTML='';a.filter(j=>j.style_id===CLOUD_STYLE_ID).slice(0,12).forEach(j=>{const d=document.createElement('div');d.className='cloud-job';d.innerHTML=`<b>${j.status} · ${j.generation_backend==='local'?'本地':'云端'} · ${j.mode==='character'?'角色':'原创'}</b><div class="cloud-note">${j.width}×${j.height} · ${j.batch}张 · 种子 ${j.seed??j.sequence_seed??'未知'} · ${j.elapsed||''}秒</div><button class="cloud-dl">查看图片</button>`;d.querySelector('button').onclick=()=>cloudAddResult(j,d);cloudHistList.appendChild(d)})}
async function cloudFavorites(){cloudFavList.innerHTML='加载中…';const a=await cloudApi('/api/favorites');cloudFavList.innerHTML='';a.filter(f=>f.selection_snapshot?.source_page===CLOUD_PAGE_ID).forEach(f=>{const d=document.createElement('div');d.className='cloud-job';d.innerHTML=`<div class="cloud-note">种子：${f.seed??f.selection_snapshot?.seed??'未知'}</div><img loading="lazy" src="${f.preview_url||f.image_url}"><button class="cloud-dl cloud-apply">↺ 套用提示词、选项和种子</button><button class="cloud-dl cloud-copy">复制完整提示词</button><a class="cloud-dl" href="${f.image_url}" target="_blank">⬇ 下载收藏原图</a>`;d.querySelector('.cloud-apply').onclick=()=>cloudApplySnapshot(f.selection_snapshot);d.querySelector('.cloud-copy').onclick=()=>navigator.clipboard.writeText((CLOUD_TRIGGER+', '+(f.prompt||'')).trim());cloudFavList.appendChild(d)})}
cloudGenerateCloud.onclick=()=>cloudGenerateNow('cloud');cloudGenerateLocal.onclick=()=>cloudGenerateNow('local');cloudSeedMode.onchange=()=>{if(cloudSeedMode.value==='random')cloudSeed.value=cloudNewSeed()};if(CLOUD_HAS_SEQUENCE)cloudSequence.onchange=cloudUpdateBatch;cloudHistOpen.onclick=()=>{cloudHistOverlay.classList.add('open');cloudHistory()};cloudFavOpen.onclick=()=>{cloudFavOverlay.classList.add('open');cloudFavorites()};document.querySelectorAll('.cloud-overlay .cloud-close').forEach(b=>b.onclick=()=>b.closest('.cloud-overlay').classList.remove('open'));cloudSeed.value=cloudNewSeed();cloudUpdateBatch();
</script>
'''

def build(source_name,out_name,style,trigger,page_id,has_sequence):
    src=(ATT/source_name).read_text(encoding="utf8")
    seq='<label>铅绘分步<select id="cloudSequence"><option value="off">关闭·普通出图</option><option value="3">3步：轮廓→黑白→淡彩</option><option value="4">4步：轮廓→成型→黑白→淡彩</option></select></label>' if has_sequence else '<select id="cloudSequence" style="display:none"><option value="off">关闭</option></select>'
    ui=UI_BASE.replace('__TRIGGER__',trigger).replace('__SEQUENCE__',seq)
    script=JS.replace('__STYLE__',style).replace('__TRIGGER__',trigger).replace('__PAGE__',page_id).replace('__HAS_SEQUENCE__','true' if has_sequence else 'false')
    out=src.replace('</style>',CSS+'\n</style>',1).replace('</main>',ui+'\n</main>',1).replace('</body>',FLOATING+'\n'+script+'\n</body>',1)
    (STATIC/out_name).write_text(out,encoding="utf8")
    print(out_name,len(out))

build('sketch_anime_dual_mode_generator (1).html','original_sketch.html','sketch','jt_style1_v1','original_sketch',True)
build('graphic_anime_style2_dual_mode_generator (1).html','original_graphic.html','graphic','jt_style2_v1','original_graphic',False)
