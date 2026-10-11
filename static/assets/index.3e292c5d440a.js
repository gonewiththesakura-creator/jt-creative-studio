export function mount({document,window,fetch,location,localStorage,sessionStorage}){
const stylePreview=document.getElementById("stylePreview");
const stylePreviewCaption=document.getElementById("stylePreviewCaption");
const previewEmpty=document.getElementById("previewEmpty");
const genCloudStatus=document.getElementById("genCloudStatus");
const apiModel=document.getElementById("apiModel");
const apiFit=document.getElementById("apiFit");
const apiQuality=document.getElementById("apiQuality");
const genLocalBtn=document.getElementById("genLocalBtn");
const genLocalStatus=document.getElementById("genLocalStatus");
const genLocalResult=document.getElementById("genLocalResult");
const genApiBtn=document.getElementById("genApiBtn");
const genApiStatus=document.getElementById("genApiStatus");
const genApiResult=document.getElementById("genApiResult");
const genCloudBtn=document.getElementById("genCloudBtn");
const genCloudResult=document.getElementById("genCloudResult");
const coldVariantSwitch=document.getElementById("coldVariantSwitch");
const coldVariantNote=document.getElementById("coldVariantNote");
const manualPositive=document.getElementById("manualPositive");
const manualNegative=document.getElementById("manualNegative");
const promptMode=document.getElementById("promptMode");
const genW=document.getElementById("genW");
const genH=document.getElementById("genH");
const genBatch=document.getElementById("genBatch");
const genHd=document.getElementById("genHd");
const genSeed=document.getElementById("genSeed");
const seedMode=document.getElementById("seedMode");
const manualPromptPanel=document.getElementById("manualPromptPanel");
const batchNote=document.getElementById("batchNote");
const histList=document.getElementById("histList");
const favList=document.getElementById("favList");
const favOverlay=document.getElementById("favOverlay");
const importGeneratedPrompt=document.getElementById("importGeneratedPrompt");
const promptPanel=document.getElementById("promptPanel");
const histOverlay=document.getElementById("histOverlay");
const apiDrawerOpen=document.getElementById("apiDrawerOpen");
const apiDrawer=document.getElementById("apiDrawer");
const apiDrawerClose=document.getElementById("apiDrawerClose");
const STYLE_ASSETS={"cold": "/static/assets/style-cold.7d8cd6a17976.json", "sketch": "/static/assets/style-sketch.8ef5d756738a.json", "original_sketch": "/static/assets/style-original_sketch.ddcefacd19f3.json", "graphic": "/static/assets/style-graphic.30d68a25bc5b.json", "original_graphic": "/static/assets/style-original_graphic.7ec28cc397e8.json", "hanmanga": "/static/assets/style-hanmanga.25dc730fb97a.json", "nff": "/static/assets/style-nff.f25cb8056228.json", "retro_manga_luxury": "/static/assets/style-retro_manga_luxury.e39668a6e5dc.json", "style221": "/static/assets/style-style221.aea07756929d.json", "style222": "/static/assets/style-style222.8fcb9e240076.json"};
const STYLE_CONFIGS={};const STYLE_BOOT={"cold":{"short":"冷脸萌","preview":"/static/assets/preview.88594b61ffdc.webp","preview_thumb":"/static/assets/preview.8a4bb8f1458e.webp","defaultMode":null},"sketch":{"short":"铅绘","preview":"/static/assets/preview.a44300d0bd32.webp","preview_thumb":"/static/assets/preview.44210fb33e25.webp","defaultMode":"character"},"original_sketch":{"short":"原始铅绘","preview":"/static/assets/preview.10bbd493b783.webp","preview_thumb":"/static/assets/preview.49412f4352d2.webp","defaultMode":"original"},"graphic":{"short":"古风","preview":"/static/assets/preview.d36eb9cfc837.webp","preview_thumb":"/static/assets/preview.96a0ded0a4e3.webp","defaultMode":null},"original_graphic":{"short":"原始古风","preview":"/static/assets/preview.9495db62a230.webp","preview_thumb":"/static/assets/preview.f3423c1c4545.webp","defaultMode":"original"},"hanmanga":{"short":"古漫","preview":"/static/assets/preview.772696a71e6f.webp","preview_thumb":"/static/assets/preview.6e28f70ac71a.webp","defaultMode":"original"},"nff":{"short":"NFF","preview":"/static/assets/preview.9df4e3fe33cb.webp","preview_thumb":"/static/assets/preview.81ccc47c0967.webp","defaultMode":null},"retro_manga_luxury":{"short":"复古日漫","preview":"/static/assets/preview.2ebb09eea5c1.webp","preview_thumb":"/static/assets/preview.42d1afbc0d5d.webp","defaultMode":"original"},"style221":{"short":"板绘","preview":null,"preview_thumb":null,"defaultMode":"original"},"style222":{"short":"铜版","preview":null,"preview_thumb":null,"defaultMode":"original"}};const STYLE_CONFIG_URL="/static/style-configs.1701e5988310.json";const DRAWERS=[{"id":"character","title":"角色","keys":["character_inspired","hair","eyes","emotion","expression","interaction","species"]},{"id":"body","title":"身体","keys":["character","body_modifier","tattoo_color","special_prompt"]},{"id":"outfit","title":"服装","keys":["outfit","top","outerwear","bottoms","legwear","footwear","accessory","fashion_extra","special_outfit"]},{"id":"pose","title":"姿势与镜头","keys":["pose","seductive_pose","special_pose","view_direction","camera"]},{"id":"background","title":"背景与剧情","keys":["prop","holiday","story","theme","scene","background","accent"]}];
const api=async(path,opt={})=>{const r=await fetch(path,opt);let d={};try{d=await r.json()}catch{}if(!r.ok){const e=new Error(d.error||('HTTP '+r.status));e.status=r.status;e.code=d.code;e.data=d;throw e}return d};
const CREATOR_ROUTES=['/','/realism','/video'];
function scheduleRoutePrefetch(){}
const activeJobKey=backend=>'jt-active-main-'+backend;function rememberActiveJob(backend,jobId){sessionStorage.setItem(activeJobKey(backend),jobId)}function forgetActiveJob(backend){sessionStorage.removeItem(activeJobKey(backend))}
const pendingCreatorKey=backend=>'jt-pending-main-'+backend;function creatorFingerprint(candidate){const normalized=JSON.parse(JSON.stringify(candidate));if(normalized.seed_mode==='random'){normalized.seed='random';if(normalized.selection_snapshot)normalized.selection_snapshot.seed='random'}return JSON.stringify(normalized)}function pendingCreatorRequest(backend,candidate){const now=Date.now(),fingerprint=creatorFingerprint(candidate);try{const saved=JSON.parse(localStorage.getItem(pendingCreatorKey(backend))||'null');if(saved?.id&&saved?.body&&(saved.uncertain||(saved.fingerprint===fingerprint&&now-saved.created<30*60*1000)))return saved}catch{}const request={id:backend+'-'+now+'-'+Math.random().toString(36).slice(2),body:candidate,fingerprint,created:now};localStorage.setItem(pendingCreatorKey(backend),JSON.stringify(request));return request}function forgetPendingCreator(backend){localStorage.removeItem(pendingCreatorKey(backend))}
let currentStyle='sketch',currentMode='character',styleVariantByStyle={cold:'character_bound'},stateByStyle={},lockedByStyle={},openDrawers=new Set(),genRunning={cloud:false,local:false,api:false};
let styleDataReady=false,styleDataPromise=null;
function bootCfg(){return STYLE_BOOT[currentStyle]||STYLE_BOOT.sketch||Object.values(STYLE_BOOT)[0]||{}}
function renderBootPreview(){const boot=bootCfg(),url=boot.preview||'',thumb=boot.preview_thumb||url;document.querySelectorAll('[data-style]').forEach(button=>button.classList.toggle('active',button.dataset.style===currentStyle));if(!thumb){stylePreview.removeAttribute('src');stylePreview.alt='';stylePreviewCaption.textContent=(boot.short||'当前画风')+' · 暂无通过质量审核的预览';previewEmpty.classList.remove('hidden');return}stylePreview.src=thumb;stylePreview.alt=(boot.short||'当前画风')+'效果预览';stylePreviewCaption.textContent=(boot.short||'当前画风')+' · 效果预览';previewEmpty.classList.remove('hidden')}
function setStyleControlsReady(ready){document.querySelectorAll('[data-style],[data-style-variant],[data-mode],#randomAll,#clearAll,#copyPrompt,#genCloudBtn,#genLocalBtn,#genApiBtn,#importGeneratedPrompt').forEach(control=>control.disabled=!ready)}
function scheduleStylePreviewPreload(){}
const styleLoads=new Map();
let styleSwitchVersion=0;
async function ensureStyle(id){
 if(STYLE_CONFIGS[id])return STYLE_CONFIGS[id];
 if(!STYLE_ASSETS[id])throw Error('画风配置不存在');
 if(!styleLoads.has(id))styleLoads.set(id,fetch(STYLE_ASSETS[id],{cache:'force-cache'}).then(async r=>{
  if(!r.ok)throw Error('画风配置加载失败：HTTP '+r.status);
  const data=await r.json();if(!data?.pools)throw Error('画风配置格式无效');
  STYLE_CONFIGS[id]=data;return data;
 }).catch(error=>{styleLoads.delete(id);throw error}));
 return styleLoads.get(id);
}
function styleLoadError(error){
 genCloudStatus.textContent=error.message;
 const retry=document.createElement('button');retry.type='button';retry.textContent='重新加载画风';
 retry.onclick=()=>loadStyleConfigs().catch(()=>{});genCloudStatus.append(retry);
}
async function chooseStyle(id){
 const version=++styleSwitchVersion;
 try{await ensureStyle(id);if(version!==styleSwitchVersion)return;
  currentStyle=id;currentMode=cfg().defaultMode||'original';prepareStyle(id);
  openDrawers.clear();updateBatchSemantics();render();
 }catch(error){if(version===styleSwitchVersion)styleLoadError(error)}
}
async function loadStyleConfigs(){
 try{
  await ensureStyle(currentStyle);styleDataReady=true;setStyleControlsReady(true);
  currentMode=cfg().defaultMode||currentMode;prepareStyle(currentStyle);
  updatePromptModeUI();updateBatchSemantics();render();
  document.querySelectorAll('[data-style]').forEach(button=>{
   button.onclick=()=>chooseStyle(button.dataset.style);
   button.addEventListener('pointerenter',()=>ensureStyle(button.dataset.style).catch(()=>{}),{once:true});
   button.addEventListener('focus',()=>ensureStyle(button.dataset.style).catch(()=>{}),{once:true});
  });
  return STYLE_CONFIGS;
 }catch(error){styleLoadError(error);throw error}
}
async function applySnapshot(snapshot){
 if(!snapshot?.state)return;
 const version=++styleSwitchVersion;
 try{await ensureStyle(STYLE_ASSETS[snapshot.style]?snapshot.style:'cold');
  if(version===styleSwitchVersion)applyLoadedSnapshot(snapshot);
 }catch(error){styleLoadError(error)}
}

const API_QUALITIES={'gpt-image-2.5-flare':['low','medium','high','xhigh','max','auto'],'gpt-image-2.5-sunburst':['low','medium','high','xhigh','max','auto'],'gpt-image-2':['low','medium','high','auto']};
function defaultApiSettings(){const models=[...apiModel.options].map(option=>option.value),fits=[...apiFit.options].map(option=>option.value),ratios=[...document.querySelectorAll('input[name="apiRatio"]')].map(input=>input.value),api_model=apiModel.querySelector('option[selected]')?.value||models[0],api_fit=apiFit.querySelector('option[selected]')?.value||fits[0],api_ratio=document.querySelector('input[name="apiRatio"][checked]')?.value||ratios[0];return{api_model:API_QUALITIES[api_model]?api_model:(models.find(model=>API_QUALITIES[model])||''),api_quality:'low',api_fit:fits.includes(api_fit)?api_fit:(fits[0]||''),api_ratio:ratios.includes(api_ratio)?api_ratio:(ratios[0]||'')}}
function normalizeApiSettings(snapshot={}){const defaults=defaultApiSettings(),models=[...apiModel.options].map(option=>option.value),fits=[...apiFit.options].map(option=>option.value),ratios=[...document.querySelectorAll('input[name="apiRatio"]')].map(input=>input.value),api_model=models.includes(snapshot.api_model)&&API_QUALITIES[snapshot.api_model]?snapshot.api_model:defaults.api_model,qualities=API_QUALITIES[api_model]||[],api_quality=qualities.includes(snapshot.api_quality)?snapshot.api_quality:(qualities.includes(defaults.api_quality)?defaults.api_quality:qualities[0]);return{api_model,api_quality,api_fit:fits.includes(snapshot.api_fit)?snapshot.api_fit:defaults.api_fit,api_ratio:ratios.includes(snapshot.api_ratio)?snapshot.api_ratio:defaults.api_ratio}}
function selectedApiRatio(){return document.querySelector('input[name="apiRatio"]:checked')?.value||defaultApiSettings().api_ratio}
function updateApiQualityOptions(preferred=apiQuality.value||defaultApiSettings().api_quality){const allowed=API_QUALITIES[apiModel.value]||[],fallback=defaultApiSettings().api_quality;apiQuality.innerHTML=allowed.map(value=>`<option value="${value}">${value}</option>`).join('');apiQuality.value=allowed.includes(preferred)?preferred:(allowed.includes(fallback)?fallback:allowed[0])}
function backendUi(backend){return backend==='local'?{button:genLocalBtn,status:genLocalStatus,result:genLocalResult,label:'本地'}:backend==='api'?{button:genApiBtn,status:genApiStatus,result:genApiResult,label:'API'}:{button:genCloudBtn,status:genCloudStatus,result:genCloudResult,label:'云端'}}
function newRandomSeed(){return Math.floor(Math.random()*9007199254740990)+1}
const cfg=()=>STYLE_CONFIGS[currentStyle], pools=()=>cfg().pools, state=()=>stateByStyle[currentStyle], locks=()=>lockedByStyle[currentStyle];
function currentStyleVariant(){return currentStyle==='cold'?(styleVariantByStyle.cold||'character_bound'):'default'}
function setStyleVariant(value){if(currentStyle!=='cold')return;const valid=(cfg().styleVariants||[]).some(item=>item.id===value);styleVariantByStyle.cold=valid?value:(cfg().styleVariantDefault||'character_bound');updateColdVariantUI()}
function updateColdVariantUI(){const visible=currentStyle==='cold';coldVariantSwitch.style.display=visible?'block':'none';if(!visible)return;const value=currentStyleVariant(),meta=(cfg().styleVariants||[]).find(item=>item.id===value);coldVariantSwitch.querySelectorAll('[data-style-variant]').forEach(button=>button.classList.toggle('active',button.dataset.styleVariant===value));coldVariantNote.textContent=meta?.note||'低泄漏画风候选'}
const isMulti=k=>(cfg().multi||[]).includes(k);
function prepareStyle(id){if(!stateByStyle[id]){stateByStyle[id]={};lockedByStyle[id]={};const defaults=STYLE_CONFIGS[id].defaultSelections||{};Object.entries(STYLE_CONFIGS[id].pools).forEach(([k,a])=>{const z=a.find(x=>!x[1])||a[0];const label=defaults[k];const hit=label?a.find(x=>x[0]===label):null;stateByStyle[id][k]=(STYLE_CONFIGS[id].multi||[]).includes(k)?[hit||z]:(hit||z)})}}
function selectedItems(k){const v=state()[k];if(isMulti(k))return Array.isArray(v?.[0])?v:(v?[v]:[]);return v?[v]:[]}function selected(k){return selectedItems(k)[0]||["无（不添加)",""]}function enabled(k){if(cfg().characterOnly.includes(k))return currentMode==='character';if(cfg().originalOnly.includes(k))return currentMode==='original';return true}function activeKeys(){return Object.keys(pools()).filter(enabled)}
function label(k){return cfg().labels[k]||({character_inspired:'选择角色',character:'身材 / 体型',body_modifier:'身材细节',tattoo_color:'纹样颜色',special_prompt:'额外细节',emotion:'情绪',expression:'表情',interaction:'视线 / 互动',background:'背景',scene:'场景',special_outfit:'特殊服装',seductive_pose:'诱惑姿势',special_pose:'特殊姿势',view_direction:'视线方向',fashion_extra:'额外配件'}[k]||k)}
function setNone(){activeKeys().forEach(k=>{const z=pools()[k].find(x=>!x[1])||pools()[k][0];state()[k]=isMulti(k)?[z]:z});render()}
function randomAll(){const sparse=new Set(cfg().sparseRandomKeys||[]);if(sparse.size){activeKeys().forEach(k=>{if(locks()[k])return;const z=pools()[k].find(x=>!x[1])||pools()[k][0];state()[k]=isMulti(k)?[z]:z})}activeKeys().forEach(k=>{if(locks()[k]||(sparse.size&&!sparse.has(k)))return;const a=pools()[k].filter(x=>x[1]);const v=a[Math.floor(Math.random()*a.length)]||pools()[k][0];state()[k]=isMulti(k)?[v]:v});render()}
function buildCorePrompt(){const parts=[cfg().prefix,cfg().head,cfg().style];activeKeys().forEach(k=>selectedItems(k).forEach(v=>{if(v[1])parts.push(v[1])}));return parts.filter(Boolean).join(',\n\n')}
function buildPrompt(){return[cfg().trigger,buildCorePrompt()].filter(Boolean).join(',\n\n')}
function buildAll(){return buildPrompt()+'\n\nNegative prompt:\n'+cfg().negative}
function importGeneratedPromptToManual(){manualPositive.value=buildCorePrompt();manualNegative.value=cfg().negative;promptMode.value='manual';updatePromptModeUI();manualPositive.focus()}
function drawerFor(k){return DRAWERS.find(d=>d.keys.includes(k))?.id}
function setResultTab(backend){document.querySelectorAll('[data-result-tab]').forEach(x=>x.classList.toggle('active',x.dataset.resultTab===backend));document.querySelectorAll('[data-result-panel]').forEach(x=>x.classList.toggle('active',x.dataset.resultPanel===backend))}
function hasVisibleResults(){return Boolean(genCloudResult.children.length||genLocalResult.children.length||genApiResult.children.length)}
const stylePreviewCache=new Map();function preloadStyleImage(url){if(!url)return Promise.resolve('');if(stylePreviewCache.has(url))return stylePreviewCache.get(url);const promise=new Promise(resolve=>{const image=new Image();image.decoding='async';image.onload=()=>resolve(url);image.onerror=()=>resolve('');image.src=url});stylePreviewCache.set(url,promise);return promise}async function preloadStylePreviews(){if(!styleDataReady)return;await Promise.all(Object.values(STYLE_CONFIGS).map(style=>preloadStyleImage(style.preview_thumb||style.preview||'')))}async function loadFullStylePreview(id,url){const loaded=await preloadStyleImage(url);if(loaded&&currentStyle===id&&!hasVisibleResults())stylePreview.src=loaded}function updateStylePreview(){if(hasVisibleResults()){previewEmpty.classList.add('hidden');return}const id=currentStyle,url=cfg().preview||'',thumb=cfg().preview_thumb||url;if(!thumb){stylePreview.removeAttribute('src');stylePreview.alt='';stylePreviewCaption.textContent=cfg().short+' · 暂无通过质量审核的预览';previewEmpty.classList.remove('hidden');return}stylePreview.src=thumb;stylePreview.alt=cfg().short+'效果预览';stylePreviewCaption.textContent=cfg().short+' · 效果预览';previewEmpty.classList.remove('hidden');loadFullStylePreview(id,url)}
const LIQUID_POLL_INTERVAL=800,LIQUID_MIN_DURATION=260,LIQUID_MAX_DURATION=1800,LIQUID_REDUCED_MOTION=matchMedia('(prefers-reduced-motion: reduce)').matches,liquidMotionState=new WeakMap();
const API_PROGRESS_TERMINAL=new Set(['done','error','cancelled','canceled']);let apiProgressSnapshot=null,apiProgressStartedAt=0,apiProgressTimer=0,apiProgressOverride={};
function installApiProgress(){genApiBtn.setAttribute('aria-live','polite')}
function isApiCancelled(job){return ['cancelled','canceled'].includes(String(job?.status||'').toLowerCase())}
function isTerminalJob(job){return API_PROGRESS_TERMINAL.has(String(job?.status||'').toLowerCase())}
function formatApiElapsed(startedAt){const seconds=Math.max(0,Math.floor((Date.now()-startedAt)/1000));return seconds<60?seconds+'秒':Math.floor(seconds/60)+'分'+String(seconds%60).padStart(2,'0')+'秒'}
function describeApiProgress(job,override={}){const status=String(job?.status||'running').toLowerCase(),provider=String(job?.provider_status||'').toUpperCase();if(override.paused)return{tone:'paused',label:override.submission?'提交待确认 · 继续查询':'查询中断 · 继续查询',note:override.submission?'点击继续确认原请求，不会新建生成任务。':'点击继续查询原任务。'};if(status==='done'||provider==='API_DONE')return{tone:'done',label:'已完成 · 再次生成'};if(isApiCancelled(job))return{tone:'cancelled',label:'已取消 · 重新生成'};if(status==='error'||provider==='API_ERROR')return{tone:'error',label:'生成失败 · 重试',note:override.message||job?.error||'生成失败，请重试'};if(status==='recovering'||override.uncertain)return{tone:'recovering',label:'查询任务中',note:override.message||'正在查询原任务'};if(['API_PROCESSING_RESULT','API_VALIDATING_RESULT','API_FITTING_RESULT'].includes(provider))return{tone:'running',label:'整理图片'};return{tone:'running',label:provider==='API_GENERATING'?'生成中':'提交中'}}
function renderApiProgress(job=apiProgressSnapshot,override={}){if(!job)return;apiProgressSnapshot={...(apiProgressSnapshot||{}),...job};apiProgressOverride=override;const state=describeApiProgress(apiProgressSnapshot,override),startedAt=Number(apiProgressSnapshot.created)*1000||apiProgressStartedAt||Date.now(),active=state.tone==='running'||state.tone==='recovering';genApiBtn.dataset.state=state.tone;genApiBtn.textContent='API · '+state.label+(active?' · '+formatApiElapsed(startedAt):'');genApiBtn.title=state.note||'';genApiBtn.setAttribute('aria-busy',String(active));const error=document.getElementById('apiActionError');if(error){const show=state.tone==='error'||state.tone==='paused';error.textContent=show?state.note:'';error.hidden=!show}}
function startApiProgress(job,override={}){if(apiProgressTimer)clearInterval(apiProgressTimer);apiProgressSnapshot={...job};apiProgressStartedAt=Number(job?.created)*1000||Date.now();renderApiProgress(apiProgressSnapshot,override);if(!isTerminalJob(apiProgressSnapshot))apiProgressTimer=setInterval(()=>renderApiProgress(apiProgressSnapshot,apiProgressOverride),1000)}
function finishApiProgress(job,override={}){if(apiProgressTimer)clearInterval(apiProgressTimer);apiProgressTimer=0;renderApiProgress(job,override)}
function pauseApiProgress(message,submission=false){if(apiProgressTimer)clearInterval(apiProgressTimer);apiProgressTimer=0;renderApiProgress(apiProgressSnapshot||{generation_backend:'api',status:'recovering'},{uncertain:true,paused:true,submission,message})}
function creatorPhaseText(job){if(job?.generation_backend==='api')return describeApiProgress(job).label.replace(/ · 阶段 \d\/4$/,'');const stage=(job?.stage_status||[]).find(item=>item.status==='RUNNING');return job?.provider_status==='RESULT_TRANSFERRING'||job?.provider_status==='RESULT_DOWNLOADING'?'正在取回结果 '+(job.transfer_index||0)+'/'+(job.transfer_total||0):(stage?.stage_label||job?.provider_status||job?.status||'正在处理')}
function paintLiquid(button,value){const pct=Math.max(0,Math.min(100,value));button.style.setProperty('--liquid-progress',pct.toFixed(2)+'%')}
function renderLiquidFrame(button,now){const state=liquidMotionState.get(button);if(!state)return;const elapsed=Math.max(0,now-state.started),t=Math.min(1,elapsed/state.duration),smooth=t*t*(3-2*t);state.display=Math.min(state.target,state.from+(state.target-state.from)*smooth);paintLiquid(button,state.display);if(t<1&&state.display<state.target)state.raf=requestAnimationFrame(ts=>renderLiquidFrame(button,ts));else{state.display=state.target;state.raf=0;paintLiquid(button,state.display);button.dispatchEvent(new CustomEvent('liquidsettled',{detail:{progress:state.display}}))}}
function setLiquidProgress(button,progress,immediate=false){const target=Math.max(0,Math.min(100,Number(progress)||0));let state=liquidMotionState.get(button);if(!state){state={display:0,target:0,from:0,started:0,duration:LIQUID_MIN_DURATION,raf:0};liquidMotionState.set(button,state)}if(state.raf)cancelAnimationFrame(state.raf);state.target=Math.max(state.display,target);button.dataset.progressTarget=state.target.toFixed(2);state.from=state.display;const distance=Math.abs(target-state.display);state.duration=Math.min(LIQUID_MAX_DURATION,Math.max(LIQUID_MIN_DURATION,distance*28));state.started=performance.now();if(immediate||LIQUID_REDUCED_MOTION){state.display=state.target;state.raf=0;paintLiquid(button,state.display);return}state.raf=requestAnimationFrame(ts=>renderLiquidFrame(button,ts))}
function waitLiquidSettled(button,target,timeout=LIQUID_MAX_DURATION+500){const state=liquidMotionState.get(button);if(!state||state.display>=target-.05)return Promise.resolve();return new Promise(resolve=>{let done=false;const finish=()=>{if(done)return;done=true;button.removeEventListener('liquidsettled',onSettle);resolve()};const onSettle=e=>{if(e.detail.progress>=target-.05)finish()};button.addEventListener('liquidsettled',onSettle);setTimeout(finish,timeout)})}
function setLiquidLoading(button,loading){button.classList.toggle('is-loading',loading);button.setAttribute('aria-busy',loading?'true':'false');if(!loading){const state=liquidMotionState.get(button);if(state?.raf)cancelAnimationFrame(state.raf);liquidMotionState.delete(button);paintLiquid(button,0);button.dataset.progressTarget='0'}}
async function pollJobResilient(jobId,onUpdate,maxConsecutive=6){let retry=0;while(1){await new Promise(x=>setTimeout(x,LIQUID_POLL_INTERVAL));try{const j=await api('/api/job/'+jobId);retry=0;onUpdate(j,false,0);if(j.generation_backend==='api'){isTerminalJob(j)?finishApiProgress(j):renderApiProgress(j)}if(isTerminalJob(j))return j}catch(e){retry++;onUpdate(null,true,retry);if(apiProgressSnapshot?.id===jobId)renderApiProgress(apiProgressSnapshot,{uncertain:true,message:'面板连接暂时中断，正在重试（'+retry+'/'+maxConsecutive+'）。不会重复提交。'});if(retry>=maxConsecutive){const uncertain=new Error('连续'+retry+'次轮询失败：'+e.message);uncertain.jobStateUncertain=true;throw uncertain}}}}
async function submitGenerateResilient(body){let last;for(let retry=0;retry<2;retry++){try{return await api('/api/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})}catch(e){last=e;if(e.status>=400&&e.status<500)throw e;if(retry===0)await new Promise(x=>setTimeout(x,1600))}}last.creatorSubmitUncertain=true;throw last}
function render(){prepareStyle(currentStyle);document.querySelectorAll('[data-style]').forEach(b=>b.classList.toggle('active',b.dataset.style===currentStyle));document.querySelectorAll('[data-mode]').forEach(b=>b.classList.toggle('active',b.dataset.mode===currentMode));updateColdVariantUI();const root=document.getElementById('drawers');root.innerHTML='';DRAWERS.forEach(d=>{const keys=d.keys.filter(k=>pools()[k]&&enabled(k));if(!keys.length)return;const box=document.createElement('section');box.className='drawer'+(openDrawers.has(d.id)?' open':'');box.dataset.drawer=d.id;box.innerHTML=`<button class="drawer-head" type="button" aria-expanded="${openDrawers.has(d.id)}"><span>${d.title}</span><span>⌄</span></button><div class="drawer-body"></div>`;box.querySelector('.drawer-head').onclick=()=>{const opening=!openDrawers.has(d.id);openDrawers.clear();if(opening)openDrawers.add(d.id);root.querySelectorAll('.drawer').forEach(drawer=>{const open=openDrawers.has(drawer.dataset.drawer);drawer.classList.toggle('open',open);drawer.querySelector('.drawer-head').setAttribute('aria-expanded',String(open))})};const body=box.querySelector('.drawer-body');keys.forEach(k=>{const chosen=new Set(selectedItems(k).map(x=>x[1]));const card=document.createElement('article');card.className='item';card.innerHTML=`<div class="item-head"><span class="item-name">${label(k)}</span><span class="item-actions"><button class="reroll">↻</button><button class="lock">${locks()[k]?'🔒':'🔓'}</button></span></div><div class="picker-wrap"><select class="picker" aria-label="${label(k)}" ${isMulti(k)?'multiple size="4"':''}>${pools()[k].map((x,i)=>`<option value="${i}" ${chosen.has(x[1])?'selected':''}>${x[0]}</option>`).join('')}</select></div>`;card.querySelector('.reroll').onclick=()=>{const a=pools()[k].filter(x=>x[1]);const v=a[Math.floor(Math.random()*a.length)]||selected(k);state()[k]=isMulti(k)?[v]:v;render()};card.querySelector('.lock').onclick=()=>{locks()[k]=!locks()[k];render()};card.querySelector('select').onchange=e=>{if(isMulti(k)){const v=[...e.target.selectedOptions].map(o=>pools()[k][+o.value]);state()[k]=v.length?v:[pools()[k].find(x=>!x[1])||pools()[k][0]]}else state()[k]=pools()[k][+e.target.value];document.getElementById('promptText').value=buildAll();updateStylePreview()};body.appendChild(card)});root.appendChild(box)});document.getElementById('promptText').value=buildAll();updateStylePreview()}
function snapshotSelections(){const api=normalizeApiSettings({api_model:apiModel.value,api_quality:apiQuality.value,api_fit:apiFit.value,api_ratio:selectedApiRatio()});return{style:currentStyle,style_variant:currentStyleVariant(),mode:currentMode,state:JSON.parse(JSON.stringify(state())),locked:JSON.parse(JSON.stringify(locks())),width:+genW.value,height:+genH.value,batch:+genBatch.value,hd:+genHd.value,sequence_mode:'off',prompt_mode:promptMode.value,manual_positive:manualPositive.value,manual_negative:manualNegative.value,seed:+genSeed.value,seed_mode:seedMode.value,...api}}
function applyLoadedSnapshot(snapshot){if(!snapshot?.state)return;const api=normalizeApiSettings(snapshot);currentStyle=STYLE_CONFIGS[snapshot.style]?snapshot.style:'cold';currentMode=snapshot.mode||'original';setStyleVariant(snapshot.style_variant||'character_bound');prepareStyle(currentStyle);stateByStyle[currentStyle]={};Object.keys(pools()).forEach(k=>{const old=snapshot.state[k];const vals=isMulti(k)?(Array.isArray(old?.[0])?old:(old?[old]:[])):(old?[old]:[]);const hit=vals.map(v=>pools()[k].find(x=>v&&(x[1]===v[1]||x[0]===v[0]))).filter(Boolean);const z=pools()[k].find(x=>!x[1])||pools()[k][0];stateByStyle[currentStyle][k]=isMulti(k)?(hit.length?hit:[z]):(hit[0]||z)});lockedByStyle[currentStyle]=snapshot.locked||{};genW.value=snapshot.width||768;genH.value=snapshot.height||1024;genBatch.value=snapshot.batch||1;genHd.value=snapshot.hd||0;promptMode.value=snapshot.prompt_mode||'options';manualPositive.value=snapshot.manual_positive||'';manualNegative.value=snapshot.manual_negative||'';genSeed.value=snapshot.seed||newRandomSeed();seedMode.value=snapshot.seed_mode||'fixed';apiModel.value=api.api_model;updateApiQualityOptions(api.api_quality);apiFit.value=api.api_fit;document.querySelectorAll('input[name="apiRatio"]').forEach(input=>input.checked=input.value===api.api_ratio);openDrawers=new Set(Object.keys(state()).filter(k=>selectedItems(k).some(x=>x[1])).map(drawerFor).filter(Boolean));updatePromptModeUI();updateBatchSemantics();render();window.scrollTo({top:0,behavior:'smooth'})}
function updatePromptModeUI(){manualPromptPanel.style.display=promptMode.value==='manual'?'block':'none';document.querySelectorAll('input[name="promptModeRadio"]').forEach(x=>x.checked=x.value===promptMode.value)}
function updateBatchSemantics(){genBatch.disabled=false;batchNote.textContent=''}
function creatorCoinText(j){if(j.generation_backend==='local'||j.generation_backend==='api')return'RH币：不适用';if(j.rh_coins!==null&&j.rh_coins!==undefined&&j.rh_coins!=='')return'RH币：'+String(j.rh_coins);return(j.status==='done'||j.status==='error')?'RH币：未返回':'RH币：统计中'}
/* Private result images are cached only in the current document, never in
 * browser storage. Thumbnails and selected previews share a bounded queue. */
const galleryImageLoader=(()=>{
 const MAX_CONCURRENT=2,MAX_BYTES=48*1024*1024,MAX_ENTRIES=100,MAX_RETRIES=3;
 const retryStatuses=new Set([429,502,503,504]),entries=new Map(),queue=[],bindings=new Map();
 let active=0,totalBytes=0,sequence=0,epoch=0,pumpScheduled=false;
 const abortError=()=>new DOMException('图片请求已结束','AbortError');
 const normalize=raw=>{const url=new URL(raw,location.href);if(url.origin!==location.origin||!['http:','https:'].includes(url.protocol))throw Error('图片地址无效');return url.href};
 const tell=(entry,state)=>{for(const callback of entry.listeners)callback(state)};
 const evict=protectedEntry=>{
  const displayed=new Set([...bindings.values()].map(binding=>binding.url));
  const candidates=[...entries.values()].filter(entry=>entry.blobUrl&&entry!==protectedEntry&&!displayed.has(entry.url)).sort((a,b)=>a.lastUsed-b.lastUsed);
  for(const entry of candidates){
   if(totalBytes<=MAX_BYTES&&entries.size<=MAX_ENTRIES)break;
   entries.delete(entry.url);totalBytes-=entry.bytes;URL.revokeObjectURL(entry.blobUrl);
  }
 };
 const schedule=()=>{if(pumpScheduled)return;pumpScheduled=true;queueMicrotask(()=>{pumpScheduled=false;pump()})};
 const pump=()=>{
  queue.sort((a,b)=>b.priority-a.priority||a.order-b.order);
  while(active<MAX_CONCURRENT&&queue.length){
   const entry=queue.shift();if(entry.epoch!==epoch||entry.finished)continue;
   active++;entry.queued=false;attempt(entry).finally(()=>{active--;schedule()});
  }
 };
 async function attempt(entry){
  const controller=new AbortController();entry.controller=controller;const timeout=setTimeout(()=>controller.abort(),45000);
  try{
   tell(entry,entry.retries?'retrying':'loading');
   const response=await fetch(entry.url,{credentials:'same-origin',cache:'no-store',signal:controller.signal});
   if(!response.ok){const error=Object.assign(Error('图片加载暂未完成'),{status:response.status});const delay=Number(response.headers.get('Retry-After'));if(Number.isFinite(delay)&&delay>0)error.retryAfter=Math.min(delay*1000,5000);throw error}
   const blob=await response.blob();if(entry.epoch!==epoch)throw abortError();
   if(!blob.size||blob.size>32*1024*1024)throw Object.assign(Error('预览图片无法读取'),{status:413});
   entry.blobUrl=URL.createObjectURL(blob);entry.bytes=blob.size;entry.finished=true;entry.lastUsed=Date.now();totalBytes+=blob.size;evict(entry);entry.resolve(entry.blobUrl);entry.listeners.clear();
  }catch(error){
   if(entry.epoch!==epoch)return;
   const temporary=retryStatuses.has(error.status)||!error.status;
   if(temporary&&entry.retries<MAX_RETRIES){
    const delay=error.retryAfter||500*Math.pow(2,entry.retries);entry.retries++;tell(entry,'retrying');
    entry.timer=setTimeout(()=>{if(entry.epoch===epoch){entry.queued=true;queue.push(entry);schedule()}},delay);
   }else{entry.finished=true;entries.delete(entry.url);entry.reject(error);entry.listeners.clear()}
  }finally{clearTimeout(timeout);entry.controller=null}
 }
 function load(raw,{priority=0,onState}={}){
  let url;try{url=normalize(raw)}catch(error){return Promise.reject(error)}
  let entry=entries.get(url);
  if(entry){entry.priority=Math.max(entry.priority,priority);entry.lastUsed=Date.now();if(onState&&!entry.finished)entry.listeners.add(onState);schedule();return entry.promise}
  entry={url,priority,order:sequence++,epoch,retries:0,bytes:0,lastUsed:Date.now(),blobUrl:'',listeners:new Set(onState?[onState]:[]),finished:false,queued:true};
  entry.promise=new Promise((resolve,reject)=>{entry.resolve=resolve;entry.reject=reject});entries.set(url,entry);queue.push(entry);schedule();return entry.promise;
 }
 function unbind(img){const binding=bindings.get(img);if(binding){bindings.delete(img);const entry=entries.get(binding.url);entry?.listeners.delete(binding.onState);if(entry&&!entry.listeners.size)entry.priority=0}img.removeAttribute('src');delete img.dataset.mediaUrl;evict()}
 function bind(img,raw,{priority=0,onState}={}){
  for(const existing of bindings.keys())if(!existing.isConnected)unbind(existing);
  unbind(img);let url;try{url=normalize(raw)}catch(error){onState?.('error');return Promise.reject(error)}
  const binding={url,epoch,onState};bindings.set(img,binding);img.dataset.mediaUrl=url;
  const current=()=>bindings.get(img)===binding&&binding.epoch===epoch;
  const notify=state=>{if(current())onState?.(state)};binding.onState=notify;notify('loading');
  return load(url,{priority,onState:notify}).then(blobUrl=>{
   if(!current())return;img.src=blobUrl;
   return img.decode().then(()=>{if(current())notify('ready')}).catch(error=>{if(current()){
    img.removeAttribute('src');const entry=entries.get(url);if(entry?.blobUrl===blobUrl){entries.delete(url);totalBytes-=entry.bytes;URL.revokeObjectURL(blobUrl)}notify('error');throw error;
   }});
  }).catch(error=>{if(current())notify(error.name==='AbortError'?'cleared':'error');throw error});
 }
 function clear(){
  epoch++;queue.length=0;
  for(const entry of entries.values()){clearTimeout(entry.timer);entry.controller?.abort();if(entry.blobUrl)URL.revokeObjectURL(entry.blobUrl);if(!entry.finished)entry.reject(abortError());entry.listeners.clear()}
  entries.clear();totalBytes=0;for(const img of [...bindings.keys()])unbind(img);
 }
 addEventListener('jt:media-clear',clear);addEventListener('jt:auth-expired',clear);addEventListener('pagehide',clear);
 addEventListener('pageshow',event=>{if(event.persisted)location.reload()});
 return {bind,load,clear,unbind};
})();

function addResult(j,container){
 for(const img of container.querySelectorAll('img'))galleryImageLoader.unbind(img);
 container.replaceChildren();const images=j.images||[];if(!images.length)return;
 previewEmpty.classList.add('hidden');document.querySelector('.preview-stage').classList.add('has-results');setResultTab(j.generation_backend||'cloud');
 const create=(tag,className)=>{const element=document.createElement(tag);element.className=className;return element};
 const gallery=create('section','media-gallery'),main=create('div','gallery-main'),strip=create('div','gallery-strip'),thumbs=create('div','gallery-thumbs');
 const prev=create('button','gallery-prev'),next=create('button','gallery-next'),meta=create('div','gallery-meta note');
 const viewport=create('div','gallery-image-viewport'),img=create('img','gallery-result-image'),status=create('button','gallery-image-status');
 const actions=create('div','gallery-actions'),fav=create('button','dl'),download=create('a','dl');
 prev.type=next.type=status.type=fav.type='button';prev.textContent='←';next.textContent='→';prev.setAttribute('aria-label','上一张图片');next.setAttribute('aria-label','下一张图片');
 img.alt='生成结果';img.decoding='async';img.hidden=true;status.setAttribute('aria-live','polite');
 download.target='_blank';download.rel='noopener noreferrer';download.textContent='⬇ 下载原图';
 viewport.append(img,status);actions.append(fav,download);main.append(meta,viewport,actions);strip.append(prev,thumbs,next);gallery.append(main,strip);container.append(gallery);
 const ui=backendUi(j.generation_backend),seedText=j.seed_supported===false?'Seed：不适用':'种子：'+(j.seed??j.sequence_seed??'未知');
 const requested=j.generation_backend==='api'?('比例 '+(j.api_ratio||'未知')+' · 请求质量 '+(j.api_quality||'未知')):'';
 const actual=j.generation_backend==='api'?('上游实际 '+[j.api_upstream_model,j.api_upstream_quality,j.api_upstream_size].filter(Boolean).join(' · ')):'';
 let selected=0,version=0;const saved=new Set(),saving=new Set();
 const updateFavorite=()=>{fav.disabled=saving.has(selected)||saved.has(selected);fav.textContent=saved.has(selected)?'✓ 已收藏':saving.has(selected)?'正在收藏…':'♥ 收藏图片和提示词'};
 const show=index=>{
  selected=(index+images.length)%images.length;const im=images[selected],renderVersion=++version;
  meta.textContent=[im.stage_label||('结果 '+(selected+1)),ui.label,creatorCoinText(j),seedText,requested,actual].filter(Boolean).join(' · ');
  download.href=im.url;img.alt='结果 '+(selected+1);img.hidden=true;updateFavorite();
  [...thumbs.children].forEach((button,i)=>{button.classList.toggle('active',i===selected);button.setAttribute('aria-pressed',String(i===selected))});
  galleryImageLoader.bind(img,im.preview_url||im.url,{priority:100,onState:state=>{
   if(renderVersion!==version)return;
   const ready=state==='ready';img.hidden=!ready;status.hidden=ready;status.disabled=state!=='error';viewport.setAttribute('aria-busy',String(state==='loading'||state==='retrying'));
   status.textContent=state==='error'?'图片暂未加载，点击重试':state==='retrying'?'正在重试加载图片…':'正在加载图片…';
  }}).catch(()=>{});
 };
 status.onclick=()=>show(selected);
 fav.onclick=async()=>{
  const index=selected;if(saving.has(index)||saved.has(index))return;saving.add(index);updateFavorite();
  try{await api('/api/favorites',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:j.id,image_index:index})});saved.add(index)}
  catch(error){if(selected===index)fav.textContent='收藏失败：'+error.message}
  finally{saving.delete(index);if(selected===index){fav.disabled=saved.has(index);if(saved.has(index))fav.textContent='✓ 已收藏'}}
 };
 images.forEach((im,index)=>{
  const button=create('button','gallery-thumb'),thumb=create('img',''),label=create('span','gallery-thumb-status');
  button.type='button';button.setAttribute('aria-label','查看结果 '+(index+1));thumb.alt='结果 '+(index+1);thumb.decoding='async';thumb.hidden=true;label.textContent=String(index+1);
  button.append(thumb,label);button.onclick=()=>show(index);thumbs.append(button);
  const loadThumbnail=()=>galleryImageLoader.bind(thumb,im.thumb_url||im.preview_url||im.url,{priority:0,onState:state=>{
   thumb.hidden=state!=='ready';label.hidden=state==='ready';label.textContent=state==='error'?'重试':state==='retrying'?'重试中':String(index+1);button.dataset.thumbnailState=state;
  }}).catch(()=>{});
  button.addEventListener('click',()=>{if(button.dataset.thumbnailState==='error')loadThumbnail()});loadThumbnail();
 });
 prev.onclick=()=>show(selected-1);next.onclick=()=>show(selected+1);prev.disabled=next.disabled=images.length<2;show(0);
}

async function resumeActiveJob(backend){
const jobId=sessionStorage.getItem(activeJobKey(backend));if(!jobId)return;const {button,status,result}=backendUi(backend);genRunning[backend]=true;button.disabled=true;if(backend==='api'){setResultTab('api');startApiProgress({id:jobId,generation_backend:'api',status:'recovering',created:Date.now()/1000},{uncertain:true,message:'正在读取原任务状态，不会重复提交。'})}
try{let j=await api('/api/job/'+jobId);if(backend==='api')startApiProgress(j,{restored:true});if(j.status==='done'){forgetActiveJob(backend);addResult(j,result);status.textContent='✓ 已恢复完成任务（'+j.elapsed+'秒）';return}if(j.status==='error'){forgetActiveJob(backend);status.textContent='✗ '+(j.error||'任务失败');return}if(isApiCancelled(j)){forgetActiveJob(backend);status.textContent='任务已取消';return}genRunning[backend]=true;button.disabled=true;setLiquidLoading(button,true);setLiquidProgress(button,Number(j.progress_pct)||0);status.textContent='正在恢复任务';j=await pollJobResilient(jobId,(next,broken,retry)=>{if(broken){status.textContent='轮询连接暂时中断，正在重试（'+retry+'/6）';return}setLiquidProgress(button,Number(next.progress_pct)||0);status.textContent=creatorPhaseText(next)});forgetActiveJob(backend);if(j.status==='done'){setLiquidProgress(button,100);addResult(j,result);await waitLiquidSettled(button,100);status.textContent='✓ 完成（'+j.elapsed+'秒）'}else if(isApiCancelled(j))status.textContent='任务已取消';else status.textContent='✗ '+(j.error||'任务失败')}catch(e){if(backend==='api')pauseApiProgress('自动查询暂时中断；任务号已保留，刷新页面会继续恢复。');status.textContent='任务恢复暂时失败：'+e.message}finally{genRunning[backend]=false;setLiquidLoading(button,false);button.disabled=false}}
async function resumeActiveJobs(){await Promise.all(['cloud','local','api'].map(resumeActiveJob))}
function uncertainCreatorRequest(backend){try{const saved=JSON.parse(localStorage.getItem(pendingCreatorKey(backend))||'null');return saved?.uncertain&&saved?.id&&saved?.body?saved:null}catch{return null}}
function markCreatorRequestUncertain(backend){try{const saved=JSON.parse(localStorage.getItem(pendingCreatorKey(backend))||'null');if(saved?.id&&saved?.body){saved.uncertain=true;localStorage.setItem(pendingCreatorKey(backend),JSON.stringify(saved))}}catch{}}
async function generate(backend){
if(genRunning[backend])return;if(backend==='api'&&sessionStorage.getItem(activeJobKey(backend)))return resumeActiveJob(backend);genRunning[backend]=true;const {button,status,result}=backendUi(backend);let lastProgress=0,terminal=false,accepted=false;button.disabled=true;setLiquidLoading(button,true);setLiquidProgress(button,3);status.textContent='正在提交…';if(backend==='api'){setResultTab('api');startApiProgress({generation_backend:'api',status:'running',provider_status:'SUBMITTING',created:Date.now()/1000})}
try{
const sequence_mode='off';if(seedMode.value==='random')genSeed.value=newRandomSeed();const seed=+genSeed.value;const positive=promptMode.value==='manual'?manualPositive.value.trim():buildCorePrompt();const negative=promptMode.value==='manual'?manualNegative.value.trim():cfg().negative;if(!positive&&!uncertainCreatorRequest(backend))throw new Error('正向提示词不能为空');
const candidate={workflow:'anima02',prompt:positive,negative_prompt:negative,prompt_mode:promptMode.value,width:+genW.value,height:+genH.value,batch:backend==='api'?1:+genBatch.value,hd:backend==='api'?0:+genHd.value,seed:seed,seed_mode:seedMode.value,style_id:currentStyle,style_variant:currentStyleVariant(),mode:currentMode,sequence_mode,generation_backend:backend,api_model:apiModel.value,api_quality:apiQuality.value,api_fit:apiFit.value,selection_snapshot:{...snapshotSelections(),generation_backend:backend}};
if(backend==='api'){delete candidate.width;delete candidate.height;candidate.api_ratio=selectedApiRatio();candidate.selection_snapshot.api_ratio=candidate.api_ratio}
const pending=pendingCreatorRequest(backend,candidate),body={...pending.body,client_request_id:pending.id};const r=await submitGenerateResilient(body);accepted=true;forgetPendingCreator(backend);rememberActiveJob(backend,r.job_id);if(backend==='api')renderApiProgress({id:r.job_id,generation_backend:'api',status:'running',provider_status:'SUBMITTING'});
const j=await pollJobResilient(r.job_id,(next,broken,retry)=>{if(broken){status.textContent='轮询连接暂时中断，正在重试（'+retry+'/6）';return}lastProgress=Math.max(lastProgress,Number(next.progress_pct)||0);setLiquidProgress(button,lastProgress);status.textContent=creatorPhaseText(next)});terminal=true;forgetActiveJob(backend);if(isApiCancelled(j)){status.textContent='任务已取消';return}if(j.status==='error')throw new Error(j.error||'生成失败');setLiquidProgress(button,100);addResult(j,result);await waitLiquidSettled(button,100);status.textContent='✓ 完成（'+j.elapsed+'秒'+(j.api_prompt_compacted?'，已为Sub2API稳定性压缩提示词':'')+(j.seed_supported===false?'，Seed不适用':'，种子 '+j.seed)+'）';await new Promise(x=>setTimeout(x,420))
}catch(e){if(e.status>=400&&e.status<500)forgetPendingCreator(backend);if(backend==='api'&&!terminal){if(e.creatorSubmitUncertain&&!accepted){markCreatorRequestUncertain(backend);pauseApiProgress('原请求等待确认',true);status.textContent='原请求等待确认'}else if(e.jobStateUncertain&&accepted){pauseApiProgress('自动查询暂时中断；任务号已保留，刷新页面会继续恢复。');status.textContent='任务状态暂时无法确认；刷新页面将继续查询原任务'}else{finishApiProgress({...(apiProgressSnapshot||{}),generation_backend:'api',status:'error',provider_status:'API_ERROR'},{message:e.message});status.textContent='✗ '+e.message}}else status.textContent='✗ '+e.message;if(terminal)forgetActiveJob(backend)}finally{genRunning[backend]=false;setLiquidLoading(button,false);button.disabled=false}}
async function history(){histList.textContent='加载中…';try{const a=await api('/api/jobs?scope=creator');histList.replaceChildren();a.slice(0,10).forEach(j=>{const d=document.createElement('div'),title=document.createElement('b'),note=document.createElement('div'),view=document.createElement('button');d.className='job';note.className='note';view.className='dl';const variant=j.style_id==='cold'?(j.style_variant==='style_only'?'仅画风候选':'人物+画风'):'';const backend=backendUi(j.generation_backend).label;title.textContent=(STYLE_CONFIGS[j.style_id]?.short||'历史')+(variant?' · '+variant:'')+' · '+backend+' · '+(j.mode==='character'?'角色':'原创');note.textContent=j.status+' · '+creatorCoinText(j)+' · '+j.width+'×'+j.height+' · '+j.batch+'张 · 种子 '+(j.seed??j.sequence_seed??'未知')+' · '+(j.elapsed||'')+'秒';view.textContent='查看图片';view.onclick=()=>addResult(j,d);d.append(title,note,view);histList.appendChild(d)})}catch(e){const d=document.createElement('div'),title=document.createElement('b'),note=document.createElement('div');d.className='job';note.className='note';title.textContent='历史加载失败';note.textContent=e.message;d.append(title,note);histList.replaceChildren(d)}}
async function favorites(){favList.textContent='加载中…';try{const a=await api('/api/favorites');favList.replaceChildren();a.forEach(f=>{const d=document.createElement('div'),note=document.createElement('div'),img=document.createElement('img'),apply=document.createElement('button'),copy=document.createElement('button'),download=document.createElement('a');d.className='job';note.className='note';note.textContent='种子：'+(f.seed??f.selection_snapshot?.seed??'未知')+' · '+(f.prompt_mode==='manual'?'手动Prompt':'选项组合');img.src=f.preview_url||f.image_url;img.alt='收藏结果';apply.className='dl apply';apply.textContent='↺ 套用提示词、选项和种子';copy.className='dl copy';copy.textContent='复制完整提示词';download.className='dl';download.href=f.image_url;download.target='_blank';download.rel='noopener noreferrer';download.textContent='⬇ 下载收藏原图';apply.onclick=()=>{applySnapshot(f.selection_snapshot);favOverlay.classList.remove('open')};copy.onclick=()=>navigator.clipboard.writeText(f.prompt||'');d.append(note,img,apply,copy,download);favList.appendChild(d)})}catch(e){const d=document.createElement('div'),title=document.createElement('b'),note=document.createElement('div');d.className='job';note.className='note';title.textContent='收藏加载失败';note.textContent=e.message;d.append(title,note);favList.replaceChildren(d)}}
document.querySelectorAll('[data-style]').forEach(b=>b.onclick=()=>{if(!styleDataReady)return;currentStyle=b.dataset.style;currentMode=cfg().defaultMode||'original';prepareStyle(currentStyle);openDrawers.clear();updateBatchSemantics();render()});document.querySelectorAll('[data-style-variant]').forEach(b=>b.onclick=()=>{if(!styleDataReady)return;setStyleVariant(b.dataset.styleVariant);render()});document.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>{if(!styleDataReady)return;currentMode=b.dataset.mode;openDrawers.clear();render()});document.querySelectorAll('input[name="promptModeRadio"]').forEach(x=>x.onchange=()=>{promptMode.value=x.value;updatePromptModeUI()});importGeneratedPrompt.onclick=importGeneratedPromptToManual;document.querySelectorAll('[data-result-tab]').forEach(x=>x.onclick=()=>setResultTab(x.dataset.resultTab));seedMode.onchange=()=>{if(seedMode.value==='random')genSeed.value=newRandomSeed()};apiModel.onchange=()=>updateApiQualityOptions();document.getElementById('randomAll').onclick=randomAll;document.getElementById('clearAll').onclick=setNone;genCloudBtn.onclick=()=>generate('cloud');genLocalBtn.onclick=()=>generate('local');genApiBtn.onclick=()=>generate('api');document.getElementById('copyPrompt').onclick=()=>navigator.clipboard.writeText(buildAll());document.getElementById('promptToggle').onclick=()=>promptPanel.classList.toggle('open');document.getElementById('histOpen').onclick=()=>{histOverlay.querySelector('.library-scroll').scrollTop=0;histOverlay.classList.add('open');history()};document.getElementById('favOpen').onclick=()=>{favOverlay.querySelector('.library-scroll').scrollTop=0;favOverlay.classList.add('open');favorites()};document.querySelectorAll('.library-overlay .close').forEach(b=>b.onclick=()=>b.closest('.library-overlay').classList.remove('open'));document.querySelectorAll('.library-overlay').forEach(x=>x.onclick=e=>{if(e.target===x)x.classList.remove('open')});const styleParam=new URLSearchParams(location.search).get('style');if(styleParam&&STYLE_BOOT[styleParam])currentStyle=styleParam;genSeed.value=newRandomSeed();updateApiQualityOptions();setResultTab('cloud');setStyleControlsReady(false);renderBootPreview();installApiProgress();scheduleRoutePrefetch();loadStyleConfigs().then(()=>resumeActiveJobs()).catch(()=>{});
const apiPopoverAnchor=apiDrawerOpen.closest('.api-popover-anchor');apiDrawerOpen.after(apiDrawer);function refreshApiPopoverBounds(){const anchorRect=apiPopoverAnchor.getBoundingClientRect(),paneRect=document.querySelector('.creation-pane').getBoundingClientRect();const visibleTop=Math.max(8,paneRect.top+8);apiDrawer.style.setProperty('--api-popover-max-height',Math.max(0,Math.floor(anchorRect.top-visibleTop-8))+'px')}const setApiPopover=open=>{if(open){apiDrawer.hidden=false;apiDrawer.inert=false;apiDrawer.setAttribute('aria-hidden','false');apiDrawerOpen.setAttribute('aria-expanded','true');refreshApiPopoverBounds();requestAnimationFrame(()=>{apiDrawer.classList.add('open');apiModel.focus({preventScroll:true})});return}apiDrawer.classList.remove('open');apiDrawer.inert=true;apiDrawer.setAttribute('aria-hidden','true');apiDrawerOpen.setAttribute('aria-expanded','false');setTimeout(()=>{if(!apiDrawer.classList.contains('open'))apiDrawer.hidden=true},200);apiDrawerOpen.focus({preventScroll:true})};apiDrawerOpen.onclick=()=>setApiPopover(apiDrawer.hidden);apiDrawerClose.onclick=()=>setApiPopover(false);addEventListener('keydown',event=>{if(event.key==='Escape'&&!apiDrawer.hidden)setApiPopover(false)});addEventListener('resize',refreshApiPopoverBounds);addEventListener('scroll',refreshApiPopoverBounds,{passive:true});document.addEventListener('pointerdown',event=>{if(!apiDrawer.hidden&&!apiDrawer.contains(event.target)&&!apiDrawerOpen.contains(event.target))setApiPopover(false)});

return {styleBoot:STYLE_BOOT};
}