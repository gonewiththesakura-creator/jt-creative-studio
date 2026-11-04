export function mount({document,window,fetch,location,localStorage,sessionStorage}){
const histOverlay=document.getElementById("histOverlay");
const favOverlay=document.getElementById("favOverlay");
// One visible upload slot, shared by all image-edit and video workflow forms.
function installCompactUploads(root,items,options={}){
  root._compactUploads?.destroy();
  if(!items.length)return;
  const panel=document.createElement('section'),tabs=document.createElement('div'),strip=document.createElement('div'),stage=document.createElement('div'),empty=document.createElement('p');
  panel.className='compact-uploads';panel.setAttribute('aria-label','上传素材');tabs.className='compact-media-tabs';strip.className='compact-media-strip';stage.className='compact-media-stage';
  empty.className='note';empty.textContent='当前设置无需上传素材';empty.hidden=true;
  panel.append(tabs,strip,stage,empty);options.before?options.before.before(panel):root.prepend(panel);
  let selected=null,kind=items[0].type,pendingFrame=0,destroyed=false;
  const previousFilled=new Map(items.map(item=>[item.key,!!item.filled()])),typeButtons=new Map(),slotButtons=new Map();
  const text=(el,value)=>{if(el.textContent!==value)el.textContent=value};
  const hidden=(el,value)=>{if(el.hidden!==value)el.hidden=value};
  const labels={image:'图片',video:'视频',audio:'音频'};
  for(const type of [...new Set(items.map(item=>item.type))]){
    const button=document.createElement('button'),name=document.createElement('span'),count=document.createElement('span');
    button.type='button';button.className='compact-media-tab';button.dataset.mediaType=type;count.className='compact-count';name.textContent=labels[type]||'素材';button.append(name,count);
    button.onclick=()=>{kind=type;selected=null;update()};tabs.append(button);typeButtons.set(type,{button,count});
  }
  for(const item of items){
    stage.append(item.box);
    const button=document.createElement('button');button.type='button';button.className='compact-media-slot';button.dataset.slot=item.key;
    button.onclick=()=>{kind=item.type;selected=item.key;update()};strip.append(button);slotButtons.set(item.key,button);
  }
  const observer=new MutationObserver(()=>{if(!pendingFrame)pendingFrame=requestAnimationFrame(()=>{pendingFrame=0;update()})});
  const watch=()=>observer.observe(root,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['class','hidden','disabled','src']});
  function update(){
    if(destroyed)return;observer.disconnect();
    const active=items.filter(item=>item.enabled()),types=[...new Set(active.map(item=>item.type))];
    if(!types.includes(kind))kind=types[0];
    const rows=active.filter(item=>item.type===kind),next=rows.find(item=>!item.filled());
    // Advance only when the selected upload actually succeeds, not on preview.
    const current=rows.find(item=>item.key===selected);
    if(!current||(current.filled()&&!previousFilled.get(current.key)))selected=(next||rows.at(-1))?.key;
    for(const item of items)previousFilled.set(item.key,!!item.filled());
    for(const [type,{button,count}] of typeButtons){
      const candidates=active.filter(item=>item.type===type),done=candidates.filter(item=>item.filled()).length;
      hidden(button,!candidates.length);text(count,done+' / '+candidates.length);button.setAttribute('aria-pressed',String(type===kind));
      button.title='已上传 '+done+'，最多可上传 '+candidates.length+(type==='image'?' 张':' 个');
      button.setAttribute('aria-label',(labels[type]||'素材')+'，已上传 '+done+'，最多 '+candidates.length);
    }
    for(const item of items){
      const button=slotButtons.get(item.key),available=rows.includes(item),filled=!!item.filled(),show=available&&(filled||item.hasFile?.()||item===next||item.shortcut);
      hidden(item.box,item.key!==selected||!available);hidden(button,!show);
      button.setAttribute('aria-pressed',String(item.key===selected));button.title=item.label;button.setAttribute('aria-label',(filled?'查看':'上传')+item.label);
      const preview=item.drop.querySelector('img'),src=preview?.getAttribute('src')||'',signature=src+'|'+filled+'|'+item.label;
      if(button.dataset.preview!==signature){
        button.dataset.preview=signature;button.replaceChildren();
        if(src){const img=document.createElement('img');img.src=src;img.alt='';button.append(img)}
        const label=document.createElement('span');label.textContent=(filled?'✓ ':'＋ ')+item.label;button.append(label);
      }
    }
    hidden(stage,!rows.length);hidden(strip,!rows.length);hidden(empty,!!active.length);
    watch();
  }
  const change=()=>update();root.addEventListener('change',change);
  root._compactUploads={refresh:update,destroy(){destroyed=true;observer.disconnect();cancelAnimationFrame(pendingFrame);root.removeEventListener('change',change);panel.remove()}};
  update();return root._compactUploads;
}

// Keep the existing boolean data contract while exposing actual toggle buttons.
function installWorkflowToggleButtons(root){
  for(const input of root.querySelectorAll('input[type=checkbox]')){
    if(input.dataset.buttonToggle)continue;input.dataset.buttonToggle='true';input.hidden=true;
    const container=input.closest('.remix-field,.control')||input.parentElement;
    const label=input.closest('label')||input.previousElementSibling;
    const name=input.getAttribute('aria-label')||label?.textContent.trim()||'开关';
    const button=document.createElement('button');button.type='button';button.className='workflow-toggle-button';button.dataset.toggleFor=input.id||container?.dataset.controlKey||name;
    button.setAttribute('aria-label',name);button.textContent=name;
    const refresh=()=>{button.setAttribute('aria-pressed',String(input.checked));button.disabled=input.disabled;button.title=input.checked?'已开启，点击关闭':'已关闭，点击开启'};
    button.onclick=event=>{event.preventDefault();event.stopPropagation();input.checked=!input.checked;input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));refresh()};
    input.addEventListener('change',refresh);
    const row=input.closest('.bool-row');
    if(row){row.hidden=true;row.after(button);container?.classList.add('button-toggle-control')}
    else if(label?.tagName==='LABEL'){label.hidden=true;label.after(button)}
    else input.after(button);
    refresh();
  }
}

function videoInputEnabled(workflow,mapping,params){
  if(workflow.id==='h3_remix_full'&&mapping===workflow.rh_media.face_reference&&!params.face_refine)return false;
  const rule=mapping.depends_on;
  return !rule||(params[rule.key]??workflow.rh_params?.[rule.key]?.default)===rule.value;
}
function enhanceRemixForm(form,workflow,state){
  form.onchange=null;form.classList.remove('remix-form');
  if(!['h3_remix_full','h3_reference_optimized'].includes(workflow.id))return;
  form.classList.add('remix-form');
  const groups=new Map(),fields=[];
  function group(name){
    if(groups.has(name))return groups.get(name).querySelector('.remix-fields');
    const box=document.createElement('details'),heading=document.createElement('summary'),body=document.createElement('div');
    box.className='remix-group';box.dataset.group=name;box.open=['基本设置','参考素材'].includes(name);
    heading.textContent=name;body.className='remix-fields';box.append(heading,body);groups.set(name,box);return body;
  }
  // Detach each field as one unit, so hidden dependencies never leave orphan labels.
  for(const [key,mapping] of Object.entries(workflow.rh_media||{})){
    const drop=form.querySelector('.drop[data-media-key="'+key+'"]'),label=drop.previousElementSibling,box=document.createElement('div');
    box.className='remix-field';box.dataset.mediaField=key;box.append(label,drop);group(mapping.group||'参考素材').append(box);
    drop.dataset.mediaType=mapping.type;
    if(mapping.type==='audio'){
      drop.querySelector('.upload-kind-icon').textContent='♪';
      drop.querySelector('.upload-formats').textContent='点击或拖入音频 · MP3 / WAV / FLAC / M4A / OGG';
    }
    fields.push({box,mapping,key,media:true});
  }
  for(const [key,mapping] of Object.entries(workflow.rh_params||{})){
    const input=form.querySelector('#param_'+key);if(!input)continue;
    const label=input.previousElementSibling,box=document.createElement('div');box.className='remix-field';box.dataset.control=key;
    const presets=key==='prompt'?form.querySelector('.prompt-presets'):null;
    const duration=key==='duration'?form.querySelector('#durationAutoNote'):null;
    label.htmlFor=input.id;box.append(label,input);if(presets)box.append(presets);if(duration)box.append(duration);
    if(input.type==='checkbox'){box.classList.add('remix-toggle');label.prepend(input)}
    if(mapping.description){const help=document.createElement('div');help.className='note';help.textContent=mapping.description;box.append(help)}
    group(mapping.group||'基本设置').append(box);fields.push({box,mapping,key});
  }
  for(const name of ['基本设置','参考素材','更多参考素材','一采与高级设置','二次采样设置','LoRA 设置','人脸精修设置','独立人脸参考','参考素材截取','输出设置']){
    const box=groups.get(name);if(box)form.append(box);
  }
  const update=()=>{
    const params={};for(const key of Object.keys(workflow.rh_params))params[key]=readParamValue(form.querySelector('#param_'+key));
    for(const field of fields){
      let enabled=videoInputEnabled(workflow,field.mapping,params);
      if(field.mapping.group==='二次采样设置')enabled&&=params.second_pass;
      if(field.mapping.group==='人脸精修设置')enabled&&=params.face_refine;
      if(field.key==='save_second')enabled&&=params.second_pass;
      if(field.key==='save_face')enabled&&=params.face_refine;
      field.box.hidden=!enabled;
      // Keep values when switching off; hidden branches are excluded server-side.
    }
    for(const box of groups.values())box.hidden=![...box.querySelectorAll(':scope > .remix-fields > .remix-field')].some(field=>!field.hidden);
    state.formParams={...params};
  };
  form.onchange=update;update();
}

function installVideoCompactForm(form,workflow,state){
  const items=Object.entries(workflow.rh_media||{}).map(([key,mapping])=>{
    const drop=form.querySelector('.drop[data-media-key="'+key+'"]');
    let box=drop.closest('.remix-field');
    if(!box){box=document.createElement('div');box.className='compact-upload-field';const label=drop.previousElementSibling;drop.before(box);if(label?.tagName==='LABEL')box.append(label);box.append(drop)}
    return {key,type:mapping.type,label:mapping.label||key,box,drop,
      shortcut:workflow.id==='h3_remix_full'&&key==='face_reference',
      filled:()=>!!state.tokens[key],hasFile:()=>!!state.files[key]||!!state.expired?.[key],
      enabled:()=>videoInputEnabled(workflow,mapping,Object.fromEntries(Object.entries(workflow.rh_params||{}).map(([key,p])=>[key,document.getElementById('param_'+key)?readParamValue(document.getElementById('param_'+key)):p.default])))};
  });
  installCompactUploads(form,items,{before:form.children[1]});
  for(const group of form.querySelectorAll('.remix-group'))if(!group.querySelector('.remix-field'))group.hidden=true;
  installWorkflowToggleButtons(form);
}

function renderPromptPresets(parent,input,workflowId){
  const key='jt-video-prompt-presets-v1:'+workflowId,box=document.createElement('details');
  box.className='prompt-presets';box.open=true;
  const heading=document.createElement('summary');heading.textContent='提示词预设';
  const slots=document.createElement('div');slots.className='prompt-preset-slots';
  const name=document.createElement('input');name.type='text';name.maxLength=24;name.placeholder='预设名称（可选）';name.setAttribute('aria-label','预设名称');
  const actions=document.createElement('div');actions.className='prompt-preset-actions';
  const note=document.createElement('div');note.className='note';note.setAttribute('aria-live','polite');
  let selected=0,stored=[];
  try{const value=JSON.parse(localStorage.getItem(key)||'[]');if(Array.isArray(value))stored=value}catch{}
  let presets=Array.from({length:6},(_,i)=>{const p=stored[i];return p&&typeof p.prompt==='string'?{name:String(p.name||'').slice(0,24),prompt:p.prompt}:null});
  const buttons=presets.map((_,i)=>{const b=document.createElement('button');b.type='button';b.onclick=()=>{selected=i;render();note.textContent=presets[i]?'已选择预设，点击“套用”填入提示词':'空位置，可保存当前提示词'};slots.append(b);return b});
  const apply=document.createElement('button'),save=document.createElement('button'),clear=document.createElement('button');
  for(const b of [apply,save,clear])b.type='button';
  apply.textContent='套用';save.textContent='保存当前';clear.textContent='清空';actions.append(apply,save,clear);
  const render=()=>{buttons.forEach((b,i)=>{b.textContent=presets[i]?.name||'预设 '+(i+1);b.title=presets[i]?.prompt||'空预设';b.setAttribute('aria-pressed',String(i===selected));b.classList.toggle('saved',Boolean(presets[i]))});name.value=presets[selected]?.name||'';apply.disabled=clear.disabled=!presets[selected]};
  const persist=(next,message)=>{try{localStorage.setItem(key,JSON.stringify(next));presets=next;render();note.textContent=message}catch{note.textContent='保存失败：浏览器存储不可用，请勿关闭当前提示词'}};
  save.onclick=()=>{if(!input.value.trim()){note.textContent='先填写提示词，再保存到预设';return}if(presets[selected]&&!confirm('覆盖这个位置已有的预设？'))return;const next=presets.slice();next[selected]={name:name.value.trim().slice(0,24),prompt:input.value};persist(next,'已保存至当前浏览器，刷新后仍保留')};
  apply.onclick=()=>{const p=presets[selected];if(!p)return;input.value=p.prompt;input.dispatchEvent(new Event('input',{bubbles:true}));note.textContent='已套用，可继续修改；尚未提交生成'};
  clear.onclick=()=>{if(!presets[selected]||!confirm('清空这个预设？当前提示词会保留。'))return;const next=presets.slice();next[selected]=null;persist(next,'已清空预设，当前提示词保留')};
  note.textContent='6 个位置 · 保存在当前浏览器 · 仅保存提示词';render();box.append(heading,slots,name,actions,note);input.after(box);
}

function renderLoraSettings(form, params, state) {
  const controls = params.filter(([, param]) => param.group === 'lora' && param.type === 'select');
  if (!controls.length) return;
  const details = document.createElement('details');
  details.className = 'lora-settings';
  const summary = document.createElement('summary');
  summary.textContent = 'LoRA 详细调整';
  const note = document.createElement('p');
  note.textContent = '按下列顺序依次加载。强度为 0 时不产生影响；收起面板仍会使用当前设置。';
  details.append(summary, note);
  state.loraParams ??= {};
  const resets = [];
  controls.forEach(([modelKey, modelParam]) => {
    const key = modelKey.replace(/_model$/, '_strength');
    const param = params.find(([name]) => name === key)[1];
    const row = document.createElement('div');
    row.className = 'lora-setting';
    const label = document.createElement('label');
    label.htmlFor = 'param_' + modelKey;
    label.textContent = modelParam.label;
    const select = document.createElement('select');
    select.id = 'param_' + modelKey;
    select.dataset.paramType = 'select';
    for (const option of modelParam.options) {
      const item = document.createElement('option');
      item.value = optionValue(option); item.textContent = optionLabel(option);
      select.append(item);
    }
    select.value = state.loraParams[modelKey] ?? modelParam.default;
    const inputs = document.createElement('div');
    inputs.className = 'lora-strength-inputs';
    const range = document.createElement('input');
    const number = document.createElement('input');
    range.type = 'range'; number.type = 'number';
    range.setAttribute('aria-label', param.label + '滑块');
    number.id = 'param_' + key;
    number.setAttribute('aria-label', param.label);
    number.dataset.paramType = 'float';
    number.required = true;
    for (const input of [range, number]) {
      input.min = param.min; input.max = param.max; input.step = param.step;
      input.value = state.loraParams[key] ?? param.default;
    }
    const remember = () => { state.loraParams[key] = number.value; };
    range.oninput = () => { number.value = range.value; remember(); };
    number.oninput = () => {
      if (number.value !== '' && number.validity.valid) range.value = number.value;
      remember();
    };
    const updateEnabled = () => { range.disabled = number.disabled = select.value === 'none'; };
    select.onchange = () => { state.loraParams[modelKey] = select.value; updateEnabled(); };
    updateEnabled();
    resets.push(() => { select.value = modelParam.default; select.onchange(); range.value = number.value = param.default; remember(); });
    inputs.append(range, number); row.append(label, select, inputs); details.append(row);
  });
  const reset = document.createElement('button');
  reset.type = 'button'; reset.className = 'lora-reset';
  reset.textContent = '恢复默认设置';
  reset.onclick = () => resets.forEach(apply => apply());
  details.append(reset); form.append(details);
}

// Upload credentials remain on the server. This page transfers file chunks only
// to its own authenticated API and resumes an interrupted finalization in place.
const accountMediaUploads=new WeakMap();
async function sendAccountMediaFile(url,file,onProgress){
  const query=new URL(url,location.origin).searchParams,scope=[query.get('workflow'),query.get('input_key')].join(':');
  let uploads=accountMediaUploads.get(file);if(!uploads){uploads=new Map();accountMediaUploads.set(file,uploads)}
  let upload=uploads.get(scope);
  if(!upload){
    const result=await api('/api/upload-start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({workflow:query.get('workflow'),input_key:query.get('input_key'),filename:file.name,size:file.size}),signal:AbortSignal.timeout(20000)});
    upload={id:result.upload_id,offset:0};uploads.set(scope,upload);
  }
  try{
    const chunkSize=512*1024;
    while(upload.offset<file.size){
      const end=Math.min(file.size,upload.offset+chunkSize),body=file.slice(upload.offset,end);
      const result=await api('/api/upload-chunk?'+new URLSearchParams({id:upload.id,offset:upload.offset}),{method:'POST',headers:{'Content-Type':'application/octet-stream'},body,signal:AbortSignal.timeout(130000)});
      if(!Number.isInteger(result.offset)||result.offset<=upload.offset||result.offset>file.size)throw Error('上传进度校验失败，请重新选择文件');
      upload.offset=result.offset;onProgress(Math.min(99,Math.floor(upload.offset/file.size*100)));
    }
    onProgress(100);
    const deadline=Date.now()+240000;
    while(Date.now()<deadline){
      const result=await api('/api/upload-finish',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({upload_id:upload.id}),signal:AbortSignal.timeout(20000)});
      if(result.uploadToken)return result;
      if(result.status==='error'){uploads.delete(scope);throw Error(result.error||'文件接收失败，请点击继续上传重试')}
      if(result.status!=='processing')throw Error('上传结果尚未确认，请点击继续上传核对');
      await new Promise(resolve=>setTimeout(resolve,1200));
    }
    throw Error('文件接收仍在处理中，请点击继续上传核对');
  }catch(error){if([400,404,410].includes(error.status))uploads.delete(scope);throw error}
}

function publicMessage(value){return String(value||'').replace(/https?:\/\/[^\s]+/gi,'云端服务')}
const api=async(path,opt={})=>{const r=await fetch(path,opt);let d={};try{d=await r.json()}catch{}if(!r.ok){const error=new Error(publicMessage(d.error)||('HTTP '+r.status));error.data=d;error.status=r.status;throw error}return d};
let WFS=[],cur=null,genRunning=false,renderVersion=0;const pendingVideoSubmitKey='jt-pending-video-submit',mediaStateByWorkflow=new Map(),MAX_VIDEO_UPLOAD_BYTES=60*1024*1024;
function ensureMediaState(workflowId){if(!mediaStateByWorkflow.has(workflowId))mediaStateByWorkflow.set(workflowId,{tokens:{},names:{},uploadIds:{},previewUrls:{},files:{},uploading:{},expired:{},thumbnails:{}});return mediaStateByWorkflow.get(workflowId)}
function selectVideoWorkflow(workflow){if(cur){const state=ensureMediaState(cur.id);state.formParams??={};for(const key of Object.keys(cur.rh_params||{})){const input=document.getElementById('param_'+key);if(input)state.formParams[key]=readParamValue(input)}if(cur.id!==workflow.id)revokeWorkflowMediaPreviews(cur.id)}cur=workflow;renderVersion++;renderForm();renderSwitch()}
async function recoverTasks(){return refreshVideoQueue()}
async function init(){const box=document.getElementById('wfSwitch'),form=document.getElementById('wfForm'),btn=document.getElementById('genBtn');box.innerHTML='<div class="config-loading">正在加载视频工作流…</div>';form.innerHTML='<div class="config-loading">加载完成后可设置提示词和素材</div>';btn.disabled=true;try{const a=await api('/api/workflows');WFS=a.filter(w=>w.kind==='video');if(!WFS.length)throw new Error('没有可用的视频工作流');box.replaceChildren();const grouped={};WFS.forEach(w=>(grouped[w.section||'其他']??=[]).push(w));Object.entries(grouped).forEach(([section,items])=>{const group=document.createElement('div'),heading=document.createElement('div');group.className='workflow-section';heading.className='workflow-section-title';heading.textContent=section;group.appendChild(heading);items.forEach(w=>{const b=document.createElement('button'),name=document.createElement('b');b.type='button';b.dataset.wf=w.id;name.textContent=w.name;b.appendChild(name);b.onclick=()=>selectVideoWorkflow(w);group.appendChild(b)});box.appendChild(group)});selectVideoWorkflow(WFS[0]);btn.disabled=false}catch(e){cur=null;box.innerHTML='<div class="config-error"><b>视频配置加载失败</b><span></span><button type="button">重新加载</button></div>';box.querySelector('span').textContent=e.message;box.querySelector('button').onclick=retryWorkflows;form.innerHTML='<div class="config-error"><span>请确认服务连接后重试，现有任务和素材不会被提交。</span></div>'}}function retryWorkflows(){init()}
function renderSwitch(){document.querySelectorAll('#wfSwitch button').forEach(b=>b.classList.toggle('active',b.dataset.wf===cur.id))}
function isVideoType(t){return t==='video'}
const videoThumbnails=new WeakMap();let thumbnailChain=Promise.resolve();
function prepareVideoThumbnail(file){
  if(typeof File==='undefined'||!(file instanceof File))return Promise.resolve(null);
  if(videoThumbnails.has(file))return videoThumbnails.get(file);
  const pending=thumbnailChain.then(()=>new Promise(resolve=>{
    const video=document.createElement('video'),url=URL.createObjectURL(file);let finished=false;
    const finish=value=>{if(finished)return;finished=true;clearTimeout(timer);video.onloadeddata=null;video.onerror=null;video.removeAttribute('src');video.load();URL.revokeObjectURL(url);resolve(value)};
    const timer=setTimeout(()=>finish(null),6000);video.muted=true;video.playsInline=true;video.preload='auto';
    video.onerror=()=>finish(null);video.onloadeddata=()=>{try{if(!video.videoWidth||!video.videoHeight)return finish(null);const canvas=document.createElement('canvas'),scale=Math.min(160/video.videoWidth,90/video.videoHeight,1);canvas.width=Math.max(1,Math.round(video.videoWidth*scale));canvas.height=Math.max(1,Math.round(video.videoHeight*scale));canvas.getContext('2d').drawImage(video,0,0,canvas.width,canvas.height);canvas.toBlob(blob=>{if(!blob||blob.size>32768)return finish(null);const reader=new FileReader();reader.onload=()=>finish(String(reader.result).split(',')[1]);reader.onerror=()=>finish(null);reader.readAsDataURL(blob)},'image/jpeg',.6)}catch{finish(null)}};video.src=url;
  })).catch(()=>null);videoThumbnails.set(file,pending);thumbnailChain=pending.then(()=>{});return pending;
}
async function prepareImageThumbnail(file){try{const bitmap=await createImageBitmap(file),canvas=document.createElement('canvas'),scale=Math.min(160/bitmap.width,90/bitmap.height,1);canvas.width=Math.max(1,Math.round(bitmap.width*scale));canvas.height=Math.max(1,Math.round(bitmap.height*scale));canvas.getContext('2d').drawImage(bitmap,0,0,canvas.width,canvas.height);bitmap.close();const data=canvas.toDataURL('image/jpeg',.6).split(',')[1];return data.length<=44000?data:null}catch{return null}}
function persistTaskThumbnails(jobId,files,workflow){
  for(const [key,file] of Object.entries(files).filter(([key])=>workflow.rh_media?.[key]?.type!=='audio'))(isVideoType(workflow.rh_media?.[key]?.type)?prepareVideoThumbnail(file):prepareImageThumbnail(file)).then(async data=>{if(!data)return;try{await api('/api/video-thumbnail',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:jobId,key,data})});refreshVideoQueue()}catch{/* Optional preview never blocks a paid task. */}});
}
function pasteReferenceImage(event){
  if(!cur||document.body.closest('.page-host')?.hidden||document.getElementById('queueEditor')||histOverlay.classList.contains('open')||favOverlay.classList.contains('open'))return;
  const file=Array.from(event.clipboardData?.items||[]).find(item=>item.kind==='file'&&item.type.startsWith('image/'))?.getAsFile();if(!file)return;
  const drops=Array.from(document.querySelectorAll('.drop')).filter(drop=>cur.rh_media?.[drop.dataset.mediaKey]?.type==='image'&&drop.getClientRects().length);
  const focused=document.activeElement?.closest?.('.drop');const target=drops.includes(focused)?focused:drops.length===1?drops[0]:null;
  if(!target){if(drops.length){event.preventDefault();document.getElementById('genStatus').textContent='有多个参考图位置，请先点击对应上传框的“粘贴到这里”再按 Ctrl＋V'}return}
  event.preventDefault();const key=target.dataset.mediaKey,m=cur.rh_media[key],ext={'image/png':'.png','image/jpeg':'.jpg','image/webp':'.webp'}[file.type];
  const named=ext&&!/\.(png|jpe?g|webp)$/i.test(file.name)?new File([file],'剪贴板-'+Date.now()+ext,{type:file.type}):file;
  uploadMedia(key,m,named,target,cur,renderVersion,ensureMediaState(cur.id));
}
function mediaAccept(type){return type==='audio'?'.mp3,.wav,.flac,.m4a,.ogg,audio/*':isVideoType(type)?'.mp4,.mov,.avi,.webm,.mkv,video/mp4,video/quicktime,video/x-msvideo,video/webm,video/x-matroska':'.png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp'}
function validateSelectedMedia(file,m){const suffix=(String(file?.name||'').match(/\.[^.]+$/)||[''])[0].toLowerCase(),allowed=m.type==='audio'?['.mp3','.wav','.flac','.m4a','.ogg']:isVideoType(m.type)?['.mp4','.mov','.avi','.webm','.mkv']:['.png','.jpg','.jpeg','.webp'];if(!allowed.includes(suffix))return m.type==='audio'?'请选择 MP3、WAV、FLAC、M4A 或 OGG 音频':isVideoType(m.type)?'请选择 MP4、MOV、WebM、AVI 或 MKV 视频':'请选择 JPG、PNG 或 WebP 图片；HEIC 请先导出为 JPG';if(!Number.isFinite(file.size)||file.size>MAX_VIDEO_UPLOAD_BYTES)return'文件超过60MB限制';if(file.size===0)return'文件为空，请重新选择';return''}
function revokeLocalMediaPreview(key,state){const value=state.previewUrls[key];if(value)URL.revokeObjectURL(value);delete state.previewUrls[key]}
function revokeWorkflowMediaPreviews(workflowId){const state=mediaStateByWorkflow.get(workflowId);if(!state)return;Object.keys(state.previewUrls).forEach(key=>revokeLocalMediaPreview(key,state))}
function replaceLocalMediaPreview(key,m,file,drop,state){revokeLocalMediaPreview(key,state);const existing=drop.querySelector('.local-media-preview');if(existing)drop.removeChild(existing);const media=document.createElement(m.type==='audio'?'audio':isVideoType(m.type)?'video':'img');media.className='local-media-preview';media.src=URL.createObjectURL(file);state.previewUrls[key]=media.src;state.files[key]=file;const remove=drop.querySelector('.media-remove');if(remove)remove.hidden=false;if(isVideoType(m.type)||m.type==='audio'){media.controls=true;media.playsInline=true;media.preload='metadata';if(isVideoType(m.type)){prepareVideoThumbnail(file);if(!['h3_remix_full','h3_reference_optimized'].includes(cur?.id)||key==='source_video')detectSourceDuration(media,key,file,drop,state)}}else media.alt='已选择的'+String(m.label||'图片');media.onerror=()=>{const note=drop.querySelector('.fn');if(note)note.textContent+=' · 当前浏览器无法预览此编码'};drop.append(media)}
function detectSourceDuration(media,key,file,drop,state){
  if(!cur?.rh_params?.duration)return;
  const workflow=cur,version=renderVersion,previous=state.durationSelection;
  if(previous?.file!==file)state.durationSelection={file,value:null,note:'正在读取视频时长…',manual:false};
  const selection=state.durationSelection;
  const active=()=>cur===workflow&&renderVersion===version&&state.files[key]===file&&state.durationSelection===selection;
  const show=()=>{if(!active())return;const input=document.getElementById('param_duration'),note=document.getElementById('durationAutoNote');if(input&&selection.value!==null)input.value=selection.value;if(note)note.textContent=selection.note};
  const failed=()=>{if(!active()||selection.manual)return;selection.note='无法读取视频时长，请手动填写';show()};
  const timer=setTimeout(failed,10000);
  media.addEventListener('loadedmetadata',()=>{clearTimeout(timer);if(!active()||selection.manual)return;const seconds=media.duration;if(!Number.isFinite(seconds)||seconds<=0){failed();return}const p=workflow.rh_params.duration,min=Number(p.min),max=p.max===undefined?Infinity:Number(p.max),step=Number(p.step)||1;const rounded=min+Math.round((seconds-min)/step)*step;selection.value=Math.max(min,Math.min(max,rounded));selection.note='检测到 '+seconds.toFixed(2)+' 秒，已填入 '+selection.value+' 秒'+(seconds<min?'（最短 '+min+' 秒）':seconds>max?'（最长 '+max+' 秒）':'（按整秒取近似值）')+'；可手动修改';show()},{once:true});
  media.addEventListener('error',()=>{clearTimeout(timer);failed()},{once:true});
}
function paramDefault(key,p){const state=ensureMediaState(cur.id),selected=key==='duration'?state.durationSelection:null;return selected?.value??state.formParams?.[key]??(Object.prototype.hasOwnProperty.call(p,'default')?p.default:(cur.params_defaults||{})[key])}
function optionValue(option){return typeof option==='object'?String(option.value??option.name??''):String(option)}
function optionLabel(option){const aliases={'minimax-n1':'dog','minimax-n2':'un','minimax-n3':'fig','minimax-n4':'v4','minimax-n5':'aio','minimax-n6':'hp'};return typeof option==='object'?String(option.label??option.name??option.value??''):(aliases[String(option)]??String(option))}
function renderForm(){const f=document.getElementById('wfForm'),workflow=cur,version=renderVersion,state=ensureMediaState(workflow.id);f._compactUploads?.destroy();f.replaceChildren();const intro=document.createElement('div'),title=document.createElement('b'),desc=document.createElement('span');intro.className='note';title.textContent=workflow.name;desc.textContent=workflow.desc;intro.append(title,document.createElement('br'),desc);f.appendChild(intro);
  const media=Object.entries(workflow.rh_media||{});
  media.forEach(([key,m])=>{const lab=document.createElement('label');lab.textContent=m.label+(m.required?'（必传）':'（可选）');f.appendChild(lab);
    const drop=document.createElement('div'),copy=document.createElement('span'),fn=document.createElement('div'),inp=document.createElement('input');drop.className='drop';drop.tabIndex=0;drop.setAttribute('role','button');drop.setAttribute('aria-label','选择或拖入'+String(m.label||'素材'));drop.dataset.mediaKey=key;drop.dataset.mediaType=isVideoType(m.type)?'video':'image';copy.className='upload-heading';const icon=document.createElement('span'),formats=document.createElement('span');icon.className='upload-kind-icon';icon.setAttribute('aria-hidden','true');icon.textContent=isVideoType(m.type)?'▶':'▧';copy.textContent=isVideoType(m.type)?'上传'+String(m.label||'视频'):'上传'+String(m.label||'参考图');formats.className='upload-formats';formats.textContent=isVideoType(m.type)?'点击或拖入视频 · MP4 / MOV / WebM 等':'点击或拖入图片 · JPG / PNG / WebP';fn.className='fn';fn.setAttribute('aria-live','polite');inp.type='file';inp.hidden=true;inp.accept=mediaAccept(m.type);drop.append(icon,copy,formats,fn,inp);if(state.tokens[key]){drop.classList.add('has-file');fn.textContent='✓ '+state.names[key]+' 已上传'}else if(state.expired?.[key]){drop.classList.add('is-expired');fn.textContent='✗ '+(typeof state.expired[key]==='string'&&state.expired[key]?state.expired[key]+' · ':'')+'原素材已过期，请重新上传'}const accept=file=>{if(!file)return;const error=validateSelectedMedia(file,m);if(error){fn.textContent='✗ '+error;return}uploadMedia(key,m,file,drop,workflow,version,state)};drop.onclick=event=>{if(event.target!==inp)inp.click()};drop.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();inp.click()}};drop.ondragover=event=>{event.preventDefault();drop.classList.add('is-dragging')};drop.ondragleave=()=>drop.classList.remove('is-dragging');drop.ondrop=event=>{event.preventDefault();drop.classList.remove('is-dragging');accept(event.dataTransfer?.files?.[0])};inp.onchange=()=>{accept(inp.files[0]);inp.value=''};
    if(state.files[key]){replaceLocalMediaPreview(key,m,state.files[key],drop,state);if(!state.tokens[key])fn.textContent=state.files[key].name+' · 尚未上传成功，请重新选择重试'}else if(state.tokens[key]&&state.thumbnails?.[key]){const preview=document.createElement('img');preview.className='local-media-preview';preview.src=state.thumbnails[key];preview.alt='已上传的'+String(m.label||'素材');preview.onerror=()=>preview.remove();drop.append(preview)}if(state.uploading[key])fn.textContent='上传中…';
    const trigger=document.createElement('button'),remove=document.createElement('button');trigger.type=remove.type='button';trigger.className='upload-trigger';trigger.append(icon,copy);drop.prepend(trigger);trigger.onclick=event=>{event.stopPropagation();inp.click()};remove.className='media-remove';remove.title='删除已选择素材';remove.setAttribute('aria-label','删除'+String(m.label||'素材'));remove.hidden=!state.files[key]&&!state.tokens[key]&&!state.expired?.[key];remove.onclick=event=>{event.stopPropagation();state.uploadIds[key]=(state.uploadIds[key]||0)+1;delete state.tokens[key];delete state.names[key];delete state.files[key];delete state.uploading[key];delete state.expired?.[key];delete state.thumbnails?.[key];revokeLocalMediaPreview(key,state);drop.querySelector('.local-media-preview')?.remove();drop.querySelector('.upload-retry')?.remove();drop.classList.remove('has-file','is-expired');fn.textContent='';remove.hidden=true;if(key==='source_video'){delete state.durationSelection;const note=document.getElementById('durationAutoNote');if(note)note.textContent='选择视频后自动读取时长，可手动修改'}};drop.append(remove);
    drop.onclick=event=>{if(event.target!==inp&&!event.target.closest('video,button'))inp.click()};drop.onkeydown=event=>{if(event.target===drop&&(event.key==='Enter'||event.key===' ')){event.preventDefault();inp.click()}};f.appendChild(drop)});
  const params=Object.entries(cur.rh_params||{});
  f.querySelectorAll('.drop').forEach(drop=>{if(workflow.rh_media[drop.dataset.mediaKey].type!=='image')return;const hint=document.createElement('button');hint.type='button';hint.className='paste-target';hint.textContent='粘贴到这里（Ctrl＋V）';hint.onclick=event=>{event.stopPropagation();drop.focus()};drop.append(hint)});
  params.filter(([,p])=>p.group!=='lora').forEach(([key,p])=>{const lab=document.createElement('label');lab.textContent=p.label+(p.required?'（必填）':'');f.appendChild(lab);let inp;
    if(p.type==='text'||p.type==='textarea'||key==='prompt'||key==='negative'){inp=document.createElement('textarea');if(cur.prompt_placeholder&&key==='prompt')inp.placeholder=cur.prompt_placeholder;if(key==='prompt'&&cur.prompt_hint){const h=document.createElement('div');h.className='note';h.style.color='#c26a4a';h.textContent=cur.prompt_hint;f.appendChild(h)}}
    else if(p.type==='boolean'){inp=document.createElement('input');inp.type='checkbox'}
    else if(p.type==='select'){inp=document.createElement('select');(p.options||[]).forEach(option=>{const item=document.createElement('option');item.value=optionValue(option);item.textContent=optionLabel(option);inp.appendChild(item)})}
    else{inp=document.createElement('input');inp.type=(p.type==='number'||p.type==='float'||p.type==='int'||p.vtype==='int'||p.vtype==='float')?'number':'text';if(p.min!==undefined)inp.min=p.min;if(p.max!==undefined)inp.max=p.max;if(p.step!==undefined)inp.step=p.step;else if(p.type==='int'||p.vtype==='int')inp.step='1'}
    inp.id='param_'+key;inp.dataset.paramType=p.vtype||p.type||'text';const d=paramDefault(key,p);if(d!==undefined){if(inp.type==='checkbox')inp.checked=d===true;else inp.value=d}f.appendChild(inp);if(key==='duration'){const note=document.createElement('div');note.id='durationAutoNote';note.className='note';note.setAttribute('aria-live','polite');note.textContent=state.durationSelection?.note||'选择视频后自动读取时长，可手动修改';f.appendChild(note);inp.addEventListener('input',()=>{if(state.durationSelection){state.durationSelection.manual=true;state.durationSelection.value=inp.value;state.durationSelection.note='已手动设置时长';note.textContent=state.durationSelection.note}})}});
  if(state.negativePrompt&&!workflow.rh_params?.negative){const label=document.createElement('label'),input=document.createElement('textarea');label.textContent='负面提示词';input.id='param_negative';input.value=state.negativePrompt;input.oninput=()=>{state.negativePrompt=input.value};f.append(label,input)}
  const promptInput=f.querySelector('#param_prompt');if(promptInput)renderPromptPresets(f,promptInput,workflow.id);
  renderLoraSettings(f,params,state);
  enhanceRemixForm(f,workflow,state);
  installVideoCompactForm(f,workflow,state);
  (cur.fixed_features||[]).forEach(text=>{const note=document.createElement('div');note.className='note unavailable';note.textContent=text;f.appendChild(note)})}
function sendMediaFile(url,file,onProgress){return new Promise((resolve,reject)=>{const request=new XMLHttpRequest();request.open('POST',url);request.timeout=600000;request.setRequestHeader('Content-Type','application/octet-stream');request.upload.onprogress=event=>{if(event.lengthComputable)onProgress(Math.round(event.loaded/event.total*100))};request.onload=()=>{let data={};try{data=JSON.parse(request.responseText)}catch{}if(request.status>=200&&request.status<300&&data.uploadToken)resolve(data);else reject(new Error(data.error||'上传服务返回错误（'+request.status+'）'))};request.onerror=()=>reject(new Error('网络连接中断，请重新选择文件重试'));request.ontimeout=()=>reject(new Error('上传超时，请检查网络或压缩文件后重试'));request.send(file)})}
async function uploadMedia(key,m,file,drop,workflow,version,state){const fnEl=drop.querySelector('.fn'),error=validateSelectedMedia(file,m);if(error){fnEl.textContent='✗ '+error;return}const uploadId=(state.uploadIds[key]||0)+1;state.uploadIds[key]=uploadId;state.uploading[key]=true;drop.querySelector('.upload-retry')?.remove();delete state.tokens[key];delete state.names[key];delete state.expired?.[key];delete state.thumbnails?.[key];replaceLocalMediaPreview(key,m,file,drop,state);fnEl.textContent='上传中…';drop.classList.remove('has-file','is-expired');try{const query=new URLSearchParams({workflow:workflow.id,input_key:key,filename:file.name});const r=await sendResumableMediaFile('/api/upload?'+query,file,percent=>{if(state.uploadIds[key]!==uploadId)return;const activeDrop=currentMediaDrop(workflow.id,key,version,drop);if(activeDrop)activeDrop.querySelector('.fn').textContent=percent<100?'上传中 '+percent+'%':'文件已传完，云端接收中…'});if(state.uploadIds[key]!==uploadId)return;state.tokens[key]=r.uploadToken;state.names[key]=file.name;const activeDrop=currentMediaDrop(workflow.id,key,version,drop);if(activeDrop){activeDrop.classList.add('has-file');activeDrop.querySelector('.fn').textContent='✓ '+file.name+' 已上传'}}catch(e){if(state.uploadIds[key]!==uploadId)return;delete state.tokens[key];delete state.names[key];const activeDrop=currentMediaDrop(workflow.id,key,version,drop);if(activeDrop){activeDrop.classList.remove('has-file');activeDrop.querySelector('.fn').textContent='✗ 上传暂未完成：'+publicMessage(e.message);const retry=document.createElement('button');retry.type='button';retry.className='upload-retry';retry.textContent='继续上传';retry.onclick=event=>{event.stopPropagation();uploadMedia(key,m,file,activeDrop,workflow,renderVersion,state)};activeDrop.append(retry)}}finally{if(state.uploadIds[key]===uploadId)delete state.uploading[key]}}
function currentMediaDrop(workflowId,key,version,original){if(cur?.id!==workflowId)return null;if(version===renderVersion&&original.isConnected)return original;return Array.from(document.querySelectorAll('.drop')).find(item=>item.dataset.mediaKey===key)||null}
async function sendResumableMediaFile(url,file,onProgress){
  return sendAccountMediaFile(url,file,onProgress);
}
function readParamValue(el){if(el.type==='checkbox')return el.checked;if(el.value==='')return'';if(el.dataset.paramType==='int')return Number.parseInt(el.value,10);if(el.dataset.paramType==='float'||el.dataset.paramType==='number')return Number(el.value);return el.value}
function collectParams(){const p={};Object.keys(cur.rh_params||{}).forEach(k=>{const el=document.getElementById('param_'+k);if(el){if(cur.rh_params[k].group==='lora'&&!el.disabled&&!el.checkValidity()){const drawer=el.closest('details');if(drawer)drawer.open=true;el.reportValidity();throw new Error('请检查 '+cur.rh_params[k].label)}const value=readParamValue(el);if(value!=='')p[k]=value}});return p}
function safeMediaUrl(value){if(!value||!String(value).trim())return'';try{const u=new URL(String(value),location.origin);return ['http:','https:'].includes(u.protocol)&&!u.username&&!u.password?u.href:''}catch{return''}}
function hasRealSeed(j){const value=j?.params?.seed??j?.seed;return typeof value==='number'&&Number.isFinite(value)}
function seedSegment(j){const value=j?.params?.seed??j?.seed;return hasRealSeed(j)?('种子：'+value+' · '):''}
function resultMediaKind(im,url){const type=String(im.file_type||im.fileType||im.outputType||im.output_type||im.type||'').trim().toLowerCase().split(';')[0].replace(/^\./,''),path=new URL(url||location.origin).pathname;if(type==='application/zip'||type==='zip'||/\.zip$/i.test(path))return'file';if(type.startsWith('video/')||['video','mp4','mov','webm','avi','mkv'].includes(type)||/\.(mp4|mov|webm|avi|mkv)$/i.test(path))return'video';if(type.startsWith('image/')||['image','png','jpg','jpeg','webp','gif','avif'].includes(type)||/\.(png|jpe?g|webp|gif|avif)$/i.test(path))return'image';return'file'}
const galleryItems=[],clearedGalleryJobs=new Set(),clearedTaskJobs=new Set();let galleryIndex=-1;
function registerGalleryJob(j,select=true){if(!select&&(j.gallery_cleared||clearedGalleryJobs.has(j.id)))return;let added=false;(j.images||[]).forEach((im,i)=>{const key=j.id+':'+i;if(!galleryItems.some(x=>x.key===key)){galleryItems.push({key,j,im,i});added=true}});if(select){const index=galleryItems.findIndex(x=>x.j.id===j.id);if(index>=0)galleryIndex=index}else if(galleryIndex<0&&galleryItems.length)galleryIndex=0;if(galleryIndex>=0&&(select||added))renderMediaGallery()}
function removeGalleryJobs(ids){
  if(!ids.size)return;ids.forEach(id=>clearedGalleryJobs.add(id));hideGalleryHint();const selected=galleryItems[galleryIndex]?.key;
  for(let i=galleryItems.length-1;i>=0;i--)if(ids.has(galleryItems[i].j.id))galleryItems.splice(i,1);
  document.getElementById('galleryThumbs').replaceChildren();galleryIndex=galleryItems.findIndex(item=>item.key===selected);
  if(galleryItems.length){if(galleryIndex<0)galleryIndex=0;renderMediaGallery()}else{galleryIndex=-1;const main=document.getElementById('galleryMain');main.querySelectorAll('video').forEach(video=>{video.pause();video.removeAttribute('src');video.load()});main.replaceChildren();delete main.dataset.key;document.getElementById('mediaGallery').hidden=true;for(const t of tasks.values())t.card.classList.remove('is-selected')}
}
let videoClearBusy=false;
async function clearVideoView(scope,button){
  if(videoClearBusy)return;videoClearBusy=true;const controls=document.querySelectorAll('.video-clear');controls.forEach(el=>el.disabled=true);const label=button.textContent,status=document.getElementById('genStatus');button.textContent='清除中…';
  try{const result=await api('/api/video-clear',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scope}),signal:AbortSignal.timeout(20000)});if(!result.ok||!Array.isArray(result.cleared_ids))throw new Error('清除结果未确认');const ids=new Set(result.cleared_ids);removeGalleryJobs(ids);if(scope!=='gallery'){closeTaskDetails();ids.forEach(id=>{clearedTaskJobs.add(id);removeTaskCard(id)});historyVersion++;if(histOverlay.classList.contains('open'))await history()}await refreshVideoQueue();document.getElementById('videoEmpty').classList.toggle('hidden',tasks.size>0||galleryItems.length>0);status.textContent='已清除 '+ids.size+' 个'+({history:'历史任务',errors:'错误任务',gallery:'播放器列表任务'}[scope]);button.title=status.textContent}
  catch(e){status.textContent='清除失败：'+e.message;button.title=status.textContent}
  finally{videoClearBusy=false;button.textContent=label;controls.forEach(el=>el.disabled=false)}
}
function installVideoClearControls(){
  const make=(id,label,scope)=>{const button=document.createElement('button');button.id=id;button.type='button';button.className='video-clear';button.textContent=label;button.title=scope==='gallery'?'清空播放器列表，历史与收藏保留':'清除已结束的记录，正在生成和排队的任务保留';button.onclick=()=>clearVideoView(scope,button);return button};
  const header=document.querySelector('#histOverlay .library-header');header.insertBefore(make('clearVideoHistory','清除历史','history'),header.querySelector('.close'));
  document.querySelector('.task-panel-head').append(make('clearVideoErrors','清除错误','errors'));
  const toolbar=document.createElement('div');toolbar.className='gallery-list-tools';const label=document.createElement('span');label.textContent='播放列表';toolbar.append(label,make('clearVideoGallery','清空列表','gallery'));const thumbs=document.getElementById('galleryThumbs');thumbs.parentElement.insertBefore(toolbar,thumbs);
}
function selectGalleryItem(index){if(!galleryItems.length)return;galleryIndex=(index+galleryItems.length)%galleryItems.length;renderMediaGallery(true)}
// Keep the source thumbnail stable; a newly decoded result frame may be black.
function resultThumbnail(item){const url=safeMediaUrl(item.im.url);return resultMediaKind(item.im,url)==='image'?(safeMediaUrl(item.im.preview_url)||url):''}
function jobConfigurationText(job){
  const params=job?.params||job?.selection_snapshot?.params||{},workflow=WFS.find(w=>w.id===job?.workflow),promptKey=['prompt','instruction','requirements','text','positive'].find(key=>params[key]),lines=['提示词：'+(job?.prompt||params[promptKey]||'未记录')];
  let recorded=false;
  for(let slot=1;slot<=3;slot++){const model=params['lora_'+slot+'_model'],strength=params['lora_'+slot+'_strength'];if(model===undefined)continue;recorded=true;lines.push('LoRA '+slot+'：'+(model==='none'?'不加载':optionLabel(model)+(strength===undefined?' · 强度未记录':' · 强度 '+strength)+(strength===0?'（已关闭）':'')))}
  if(!recorded)lines.push('LoRA：此任务未记录配置');
  for(const [key,value] of Object.entries(params)){if(key===promptKey||key==='prompt'||/^lora_[123]_(model|strength)$/.test(key)||value===null||value===undefined)continue;const label=workflow?.rh_params?.[key]?.label||key;lines.push(label+'：'+(typeof value==='object'?JSON.stringify(value):String(value)))}
  return lines.join('\n');
}
let galleryHint=null,galleryHintOwner=null,galleryHintTimer=null,galleryHintOpenTimer=null;
function hideGalleryHint(){clearTimeout(galleryHintOpenTimer);clearTimeout(galleryHintTimer);if(galleryHint)galleryHint.hidden=true;galleryHintOwner=null}
function deferGalleryHintHide(){clearTimeout(galleryHintOpenTimer);clearTimeout(galleryHintTimer);galleryHintTimer=setTimeout(()=>{if(!galleryHint?.matches(':hover')&&!galleryHint?.contains(document.activeElement)&&!galleryHintOwner?.matches(':hover'))hideGalleryHint()},300)}
function showGalleryHint(button,entry){
  clearTimeout(galleryHintOpenTimer);clearTimeout(galleryHintTimer);
  if(!galleryHint){galleryHint=document.createElement('div');galleryHint.id='galleryJobHint';galleryHint.className='gallery-job-hint';galleryHint.tabIndex=0;galleryHint.setAttribute('role','region');galleryHint.setAttribute('aria-label','视频提示词与 LoRA 详情');galleryHint.onpointerenter=()=>clearTimeout(galleryHintTimer);galleryHint.onpointerleave=deferGalleryHintHide;galleryHint.onfocus=()=>clearTimeout(galleryHintTimer);galleryHint.onblur=deferGalleryHintHide;galleryHint.onkeydown=e=>{if(e.key==='Escape'){hideGalleryHint();button.focus()}};document.body.append(galleryHint)}
  galleryHintOwner=button;galleryHint.textContent=jobConfigurationText({...tasks.get(entry.j.id)?.job,...entry.j});galleryHint.hidden=false;
  const rect=button.getBoundingClientRect(),height=galleryHint.offsetHeight;
  galleryHint.style.left=Math.max(8,Math.min(rect.left,window.innerWidth-galleryHint.offsetWidth-8))+'px';
  galleryHint.style.top=Math.max(8,rect.top>=height+16?rect.top-height-8:Math.min(rect.bottom+8,window.innerHeight-height-8))+'px';
  button.setAttribute('aria-describedby',galleryHint.id);
}
function renderGalleryThumbs(){
  const thumbs=document.getElementById('galleryThumbs');
  galleryItems.forEach((entry,index)=>{
    let b=thumbs.children[index];
    if(!b){b=document.createElement('button');b.type='button';b.onclick=()=>{hideGalleryHint();selectGalleryItem(index)};b.onpointerenter=e=>{if(e.pointerType==='touch')return;if(galleryHintOwner===b&&!galleryHint.hidden){clearTimeout(galleryHintTimer);return}hideGalleryHint();galleryHintOpenTimer=setTimeout(()=>{if(b.isConnected&&b.matches(':hover'))showGalleryHint(b,entry)},2000)};b.onpointerleave=deferGalleryHintHide;b.onfocus=()=>showGalleryHint(b,entry);b.onblur=deferGalleryHintHide;b.onkeydown=e=>{if(e.key==='Escape')hideGalleryHint()};thumbs.append(b)}
    b.className='gallery-thumb'+(index===galleryIndex?' active':'');
    const src=resultThumbnail(entry)||tasks.get(entry.j.id)?.sourceThumbnail||'',kind=resultMediaKind(entry.im,safeMediaUrl(entry.im.url)),signature=src+'|'+kind;
    if(b.dataset.preview!==signature){b.dataset.preview=signature;b.replaceChildren();if(src){const img=document.createElement('img');img.src=src;img.loading='lazy';img.decoding='async';img.alt=resultThumbnail(entry)?'生成结果':'原视频参考缩略图';b.append(img)}else{const span=document.createElement('span');span.textContent=kind==='video'?'▶':'▧';b.append(span)}}
    b.setAttribute('aria-label','播放结果 '+(index+1));b.setAttribute('aria-pressed',String(index===galleryIndex));
  });
  for(const id of ['galleryPrev','galleryNext'])document.getElementById(id).disabled=galleryItems.length<2;
}
function renderMediaGallery(autoplay=false){
  const main=document.getElementById('galleryMain');if(!main||galleryIndex<0)return;const item=galleryItems[galleryIndex];
  // Polling only appends thumbnails; keep the selected player and its playback position.
  if(main.dataset.key!==item.key){main.dataset.key=item.key;main.replaceChildren();const url=safeMediaUrl(item.im.url),kind=resultMediaKind(item.im,url),note=document.createElement('div');note.className='gallery-meta';note.textContent=seedSegment(item.j)+String(item.im.stage_label||item.im.file||'结果');main.append(note);
    const viewport=document.createElement('div');viewport.className='gallery-viewport';main.append(viewport);
    if(kind==='file'){const file=document.createElement('div');file.className='file-result';file.textContent='结果文件已生成，可直接下载';viewport.append(file)}else{const media=document.createElement(kind==='video'?'video':'img');if(kind==='video'){media.controls=true;media.playsInline=true;media.preload='auto';}else media.alt='生成结果';media.src=kind==='video'?url:(safeMediaUrl(item.im.preview_url)||url);viewport.append(media)}
    const actions=document.createElement('div'),download=document.createElement('a'),favorite=document.createElement('button');actions.className='gallery-actions';download.className='dl';download.href=url;download.target='_blank';download.rel='noopener noreferrer';download.textContent='⬇ 下载原文件';favorite.className='dl';favorite.textContent='♥ 收藏';favorite.disabled=kind==='file';favorite.onclick=()=>saveGalleryFavorite(item,favorite);actions.append(favorite,download);main.append(actions);
  }renderGalleryThumbs();for(const t of tasks.values())t.card.classList.toggle('is-selected',t.job?.id===item.j.id);document.getElementById('mediaGallery').hidden=false;document.getElementById('videoEmpty').classList.add('hidden');
  if(autoplay){const player=main.querySelector('video');if(player)player.play().catch(()=>{if(main.contains(player)){player.muted=true;player.play().catch(()=>{})}})}
}
function addResult(j){registerGalleryJob(j)}
const tasks=new Map(); // job_id -> {card, timeEl, metaEl, spinEl, timer, startTs, wfName}
function closeTaskDetails(){for(const t of tasks.values()){t.clearDetailsTimers?.();if(t.info.matches(':popover-open'))t.info.hidePopover()}}
window.addEventListener('resize',closeTaskDetails);
window.addEventListener('resize',hideGalleryHint);
document.getElementById('galleryThumbs').addEventListener('scroll',hideGalleryHint,{passive:true});
document.querySelector('.preview-stage').addEventListener('scroll',hideGalleryHint,{passive:true});
document.querySelector('.preview-stage').addEventListener('scroll',()=>requestAnimationFrame(()=>{for(const t of tasks.values())if(t.info.matches(':popover-open'))t.positionDetails?.()}),{passive:true});
function fmtTime(s){s=Math.floor(s);const m=String(Math.floor(s/60)).padStart(2,'0'),ss=String(s%60).padStart(2,'0');return m+':'+ss}
function refreshTaskCount(){const n=tasks.size;document.getElementById('taskCount').textContent=n+' 个任务（最多2个并发）'}
function taskStatusText(j){const s=j.provider_status||j.status;if(j.status==='done')return '✓ 完成';if(j.status==='error')return '✗ 失败';if(s==='SUBMITTING')return '排队中…';if(s==='RUNNING')return '生成中…';return s||'处理中…'}
function videoCoinText(j){if(j.rh_coins!==null&&j.rh_coins!==undefined&&j.rh_coins!=='')return'RH币：'+String(j.rh_coins);return(j.status==='done'||j.status==='error')?'RH币：未返回':'RH币：统计中'}
function taskStatusClass(j){if(j.status==='done')return 'done';if(j.status==='error')return 'err';return ''}
function canRedoVideoTask(job){return job?.redoable??(['done','error','cancelled'].includes(job?.status)&&!job.queue_hold&&(!job.cancel_requested||job.cancel_confirmed)&&!['RUNNING','QUEUED','RECOVERING','SUBMITTING'].includes(job.provider_status))}
function taskGroup(key){
  const list=document.getElementById('taskList');let group=list.querySelector('[data-group="'+key+'"]');if(group)return group;
  group=document.createElement(key==='done'?'details':'section');group.dataset.group=key;group.className='task-group';const heading=document.createElement(key==='done'?'summary':'h3'),grid=document.createElement('div');grid.className='task-grid';group.append(heading,grid);
  const next=key==='active'?list.querySelector('[data-group=done],[data-group=other]'):key==='done'?list.querySelector('[data-group=other]'):null;list.insertBefore(group,next);return group;
}
function addTaskCard(jobId,wfName){
  if(tasks.has(jobId))return tasks.get(jobId);const card=document.createElement('div'),tile=document.createElement('button'),thumb=document.createElement('span'),badge=document.createElement('span'),info=document.createElement('div'),name=document.createElement('div'),meta=document.createElement('div'),time=document.createElement('div'),view=document.createElement('button'),files=document.createElement('div'),actions=document.createElement('div');card.className='task-card';card.dataset.jobId=jobId;card.dataset.status='pending';tile.className='task-tile';tile.type='button';tile.setAttribute('aria-label',wfName+' · 同步队列中');thumb.className='task-picture';thumb.textContent='▧';badge.className='task-badge';badge.textContent='同步队列中';info.className='task-details';info.setAttribute('popover','auto');name.className='task-name';name.textContent=wfName;meta.className='task-meta';meta.textContent='已提交，正在同步任务状态';files.className='queue-files';actions.className='queue-actions';actions.hidden=true;time.className='task-time';view.className='task-view';view.type='button';view.textContent='播放结果';view.hidden=true;info.append(name,files,meta,time,actions,view);tile.append(thumb,badge);card.append(tile,info);const group=taskGroup('active');group.lastChild.append(card);group.hidden=false;group.firstChild.textContent='进行中 · '+group.lastChild.children.length;document.getElementById('videoEmpty').classList.add('hidden');const t={card,tile,thumb,badge,info,timeEl:time,metaEl:meta,viewEl:view,filesEl:files,actionsEl:actions,wfName,pendingSince:Date.now(),job:{id:jobId,status:'pending'}};tasks.set(jobId,t);
  let openTimer,closeTimer;
  const clearTimers=()=>{clearTimeout(openTimer);clearTimeout(closeTimer)},position=()=>{const rect=tile.getBoundingClientRect();info.style.left=Math.max(8,Math.min(rect.left,window.innerWidth-info.offsetWidth-8))+'px';const below=window.innerHeight-rect.bottom-14,above=rect.top-14,useBelow=below>=Math.min(info.scrollHeight+32,420)||below>=above;info.style.maxHeight=Math.max(80,useBelow?below:above)+'px';info.style.top=(useBelow?rect.bottom+6:Math.max(8,rect.top-info.offsetHeight-6))+'px'},show=()=>{clearTimers();if(!card.isConnected)return;if(!info.matches(':popover-open'))info.showPopover();position()},hide=()=>{clearTimers();closeTimer=setTimeout(()=>{if(!info.matches(':hover')&&!info.contains(document.activeElement)&&info.matches(':popover-open'))info.hidePopover()},180)};
  tile.onpointerenter=e=>{if(e.pointerType==='touch')return;clearTimers();if(info.matches(':popover-open'))position();else openTimer=setTimeout(()=>{if(tile.matches(':hover'))show()},2000)};tile.onpointerleave=hide;tile.onfocus=show;tile.onclick=()=>{show();if(t.job?.status==='done')view.click()};info.onpointerenter=clearTimers;info.onpointerleave=hide;info.onfocusout=hide;
  t.clearDetailsTimers=clearTimers;t.positionDetails=position;
  for(const [action,label] of [['top','置顶插队'],['up','上移'],['down','下移'],['edit','编辑参数']]){const b=document.createElement('button');b.type='button';b.textContent=label;b.dataset.action=action;b.onclick=()=>{info.hidePopover();return action==='edit'?openQueueEditor(t.job):queueAction(t.job,action)};actions.append(b)}
  const remove=document.createElement('button');remove.type='button';remove.className='task-remove';remove.hidden=true;remove.title='取消任务';remove.setAttribute('aria-label','取消任务');remove.onclick=event=>{event.stopPropagation();if(!t.job||t.busy||t.job.cancel_requested)return;clearTimers();info.hidePopover();queueAction(t.job,t.job.status==='queued'?'cancel':'cancel_running')};card.append(remove);t.removeEl=remove;
  const redo=document.createElement('button'),quickRedo=document.createElement('button');redo.type=quickRedo.type='button';redo.className='task-redo dl';redo.textContent='重做一次';quickRedo.className='task-redo-quick';quickRedo.textContent='↻';quickRedo.title='重做一次（恢复素材与配置到表单）';quickRedo.setAttribute('aria-label','重做一次');redo.hidden=quickRedo.hidden=true;const repeat=event=>{event.stopPropagation();info.hidePopover();redoVideoTask(t)};redo.onclick=quickRedo.onclick=repeat;info.append(redo);card.append(quickRedo);t.redoEl=redo;t.redoQuickEl=quickRedo;return t;
}
function updateTaskThumbnail(t){const entry=galleryItems.find(x=>x.j.id===t.job?.id),result=entry&&resultThumbnail(entry),src=result||t.sourceThumbnail||'',signature=src+'|'+t.job?.status;if(t.thumbSignature===signature)return;t.thumbSignature=signature;t.thumb.replaceChildren();if(src){const img=document.createElement('img');img.src=src;img.loading='lazy';img.decoding='async';img.alt=result?'生成结果缩略图':'原视频首帧';img.onerror=()=>img.remove();t.thumb.append(img);if(!result){const hint=document.createElement('small');hint.textContent='原视频';t.thumb.append(hint)}}else t.thumb.textContent=t.job?.status==='done'?'▶':'▧'}
const resultLoads=new Map();let resultLoadChain=Promise.resolve();
function loadCompletedTask(j){if(resultLoads.has(j.id))return resultLoads.get(j.id);const pending=resultLoadChain.then(async()=>{const full=await api('/api/job/'+encodeURIComponent(j.id),{signal:AbortSignal.timeout(20000)});if(!(full.images||[]).length)throw new Error('结果同步中');registerGalleryJob(full,false);const t=tasks.get(j.id);if(t)updateTaskThumbnail(t);return full}).catch(e=>{resultLoads.delete(j.id);const t=tasks.get(j.id);if(t)t.metaEl.textContent+=' · 结果同步中，将自动重试';return null});resultLoads.set(j.id,pending);resultLoadChain=pending.then(()=>{});return pending}
function groupTaskCards(rows){for(const [key,title,statuses] of [['active','进行中',['pending','queued','running','recovering']],['done','已完成',['done']],['other','未完成 · 失败 / 已取消',['error','cancelled']]]){const group=taskGroup(key),items=rows.filter(j=>key==='other'?!['pending','queued','running','recovering','done'].includes(j.status):statuses.includes(j.status));group.hidden=!items.length;group.firstChild.textContent=title+' · '+items.length;const grid=group.lastChild;items.forEach((j,index)=>{const card=tasks.get(j.id).card;if(grid.children[index]!==card)grid.insertBefore(card,grid.children[index]||null)})}if(rows.length)document.getElementById('videoEmpty').classList.add('hidden')}
function removeTaskCard(jobId){const t=tasks.get(jobId);if(!t)return;if(t.timer)clearInterval(t.timer);t.clearDetailsTimers?.();t.card.remove();tasks.delete(jobId);refreshTaskCount()}
function renderTaskResult(j){registerGalleryJob(j);renderMediaGallery(true);document.querySelector('.preview-stage').scrollTo({top:0,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'})}
async function pollTask(jobId){return refreshVideoQueue()}
let queueTimer=null,queueFetching=false,queueRefreshAgain=false;
async function refreshVideoQueue(){
  clearTimeout(queueTimer);if(queueFetching){queueRefreshAgain=true;return}queueFetching=true;
  try{const state=await api('/api/video-queue'),rows=(state.jobs||[]).filter(j=>!['done','error','cancelled'].includes(j.status)||(!j.task_cleared&&!clearedTaskJobs.has(j.id))),ids=new Set(rows.map(j=>j.id)),list=document.getElementById('taskList');
    for(const [id,t] of tasks)if(!ids.has(id)&&(!t.pendingSince||Date.now()-t.pendingSince>60000))removeTaskCard(id);
    removeGalleryJobs(new Set(rows.filter(j=>j.gallery_cleared&&!clearedGalleryJobs.has(j.id)).map(j=>j.id)));
    rows.forEach((j,index)=>{const t=addTaskCard(j.id,j.wf_name||'视频任务');delete t.pendingSince;t.job=j;
      if(!t.configEl){t.configEl=document.createElement('div');t.configEl.className='task-configuration';t.info.insertBefore(t.configEl,t.metaEl)}t.configEl.textContent=jobConfigurationText(j);
      const mediaSignature=JSON.stringify([j.media,j.thumbnails]);if(t.mediaSignature!==mediaSignature){t.mediaSignature=mediaSignature;t.sourceThumbnail=Object.values(j.thumbnails||{}).find(src=>typeof src==='string'&&src.startsWith('/api/video-thumbnail/'));t.filesEl.replaceChildren();for(const [key,name] of Object.entries(j.media||{})){const item=document.createElement('div'),w=WFS.find(w=>w.id===j.workflow);item.className='queue-media';item.textContent=(w?.rh_media?.[key]?.label||'素材')+'：'+name;t.filesEl.append(item)}if(!Object.keys(j.media||{}).length)t.filesEl.textContent='无需上传素材'}
      t.metaEl.textContent=j.queue_hold?'提交超时，未收到云端任务号；暂占 1 个名额，正在自动核对，不会重复提交':j.provider_status==='SUBMIT_UNCONFIRMED_IDLE'?'旧任务结果未知；已核对并释放名额，不影响后续排队，未自动重提':j.status==='queued'?'等待第 '+j.position+' 位 · 尚未提交上游':j.status==='cancelled'?'已取消排队 · 未提交上游':j.status==='error'?(j.provider_status==='QUEUE_EXPIRED'?'素材已过期，请重新上传':j.error||'任务失败'):taskStatusText(j)+' · '+videoCoinText(j);
      t.card.dataset.status=j.status;t.badge.textContent=j.queue_hold?'核对中 · 占位':j.provider_status==='SUBMIT_UNCONFIRMED_IDLE'?'结果未知 · 已释放':j.status==='queued'?'排队 · 第 '+j.position+' 位':j.status==='done'?'✓ 已完成':j.status==='cancelled'?'已取消':j.status==='error'?'✕ 失败':'◉ 生成中';t.tile.setAttribute('aria-label',t.wfName+' · '+t.badge.textContent+' · 任务详情');t.timeEl.textContent=j.elapsed?'用时 '+fmtTime(j.elapsed):'';t.actionsEl.hidden=!j.editable;t.viewEl.hidden=j.status!=='done';updateTaskThumbnail(t);
      if(j.status==='cancelled'&&j.cancel_confirmed)t.metaEl.textContent='云端已确认停止，已释放并发名额';
      if(j.cancel_requested&&j.cancellable){t.badge.textContent='取消中 · 核对停止';t.metaEl.textContent=j.cancel_note||'等待云端确认取消；确认前仍占用并发名额'}
      t.actionsEl.hidden=!j.editable&&!j.cancellable;
      t.removeEl.hidden=!j.editable&&!j.cancellable;t.removeEl.disabled=!!t.busy||!!j.cancel_requested;t.removeEl.title=j.cancel_requested?'正在取消':j.status==='queued'?'取消排队':'取消生成';t.removeEl.setAttribute('aria-label',t.removeEl.title);
      t.redoEl.hidden=t.redoQuickEl.hidden=!canRedoVideoTask(j);t.redoEl.disabled=t.redoQuickEl.disabled=!!t.redoBusy;
      t.actionsEl.querySelectorAll('button').forEach(b=>{const cancel=b.dataset.action==='cancel_running';b.hidden=cancel?!j.cancellable:!j.editable;if(cancel)b.textContent=j.cancel_requested?'取消中…':'取消生成';b.disabled=t.busy||(cancel&&j.cancel_requested)||(['top','up'].includes(b.dataset.action)&&j.position===1)||(b.dataset.action==='down'&&j.position===state.waiting)});
      t.viewEl.onclick=async()=>{t.info.hidePopover();t.viewEl.disabled=true;try{const full=await loadCompletedTask(j);if(full)renderTaskResult(full)}finally{t.viewEl.disabled=false}};
      if(j.status==='done'&&!j.gallery_cleared&&!clearedGalleryJobs.has(j.id))loadCompletedTask(j);
    });groupTaskCards([...rows,...Array.from(tasks.values()).filter(t=>t.pendingSince).map(t=>t.job)]);document.getElementById('taskCount').textContent='执行 '+state.running+'/'+state.limit+' · 等待 '+state.waiting+'（最多2个并发）'+(state.draining?' · 维护中，暂缓启动':'');
  }catch(e){document.getElementById('taskCount').textContent='队列连接中断，自动重试：'+e.message}
  finally{queueFetching=false;queueTimer=setTimeout(refreshVideoQueue,queueRefreshAgain?0:document.hidden?15000:4000);queueRefreshAgain=false}
}
async function queueAction(job,action,extra={}){
  if(!job)return;const t=tasks.get(job.id);if(t?.busy)return;t.busy=true;t.actionsEl.querySelectorAll('button').forEach(b=>b.disabled=true);
  try{await api('/api/video-queue',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:job.id,revision:job.queue_revision,action,...extra})});return true}
  catch(e){document.getElementById('genStatus').textContent='队列操作失败：'+e.message;return false}
  finally{t.busy=false;await refreshVideoQueue()}
}
function restoreVideoTaskDraft(draft,fallbackJob){const workflowId=draft?.workflow||fallbackJob?.workflow,workflow=WFS.find(w=>w.id===workflowId);if(!workflow)throw new Error('未找到对应的视频工作流');if(cur&&cur.id!==workflow.id){const prevState=ensureMediaState(cur.id);prevState.formParams??={};for(const key of Object.keys(cur.rh_params||{})){const input=document.getElementById('param_'+key);if(input)prevState.formParams[key]=readParamValue(input)}revokeWorkflowMediaPreviews(cur.id)}const state=ensureMediaState(workflow.id);revokeWorkflowMediaPreviews(workflow.id);for(const key of Object.keys(state.uploadIds||{}))state.uploadIds[key]=(state.uploadIds[key]||0)+1;state.tokens={};state.names={};state.files={};state.uploading={};state.expired={};state.thumbnails={};delete state.durationSelection;const rawParams={...(fallbackJob?.params||{}),...(draft?.params||{})},promptValue=draft?.prompt??fallbackJob?.prompt??rawParams.prompt??'',negativeValue=draft?.negative_prompt??fallbackJob?.negative_prompt??rawParams.negative??'';state.formParams={...rawParams};if(promptValue!==undefined&&promptValue!==null&&workflow.rh_params?.prompt)state.formParams.prompt=promptValue;if(negativeValue!==undefined&&negativeValue!==null&&workflow.rh_params?.negative)state.formParams.negative=negativeValue;state.negativePrompt=String(negativeValue||'');state.loraParams={};for(const [key,param] of Object.entries(workflow.rh_params||{}))if(param.group==='lora'&&Object.prototype.hasOwnProperty.call(rawParams,key)&&rawParams[key]!==undefined&&rawParams[key]!==null)state.loraParams[key]=String(rawParams[key]);const mediaEntries=draft?.media||{},jobThumbs=draft?.thumbnails||fallbackJob?.thumbnails||{};let expiredCount=0,firstExpired=null,firstRestored=null;for(const [key,m] of Object.entries(workflow.rh_media||{})){const item=mediaEntries[key];if(!item)continue;const filename=typeof item==='object'?String(item.filename||item.name||key):String(item),token=typeof item==='object'&&item.valid!==false&&!item.expired?String(item.token||''):'',thumb=safeMediaUrl((typeof item==='object'&&item.thumbnail)||jobThumbs[key]||'');if(token){state.tokens[key]=token;state.names[key]=filename;if(thumb)state.thumbnails[key]=thumb;if(!firstRestored)firstRestored=key}else{state.expired[key]=filename||m.label||key;expiredCount++;if(!firstExpired)firstExpired=key}}cur=workflow;renderVersion++;renderForm();renderSwitch();const promptEl=document.getElementById('param_prompt');if(promptEl&&promptValue!==undefined&&promptValue!==null)promptEl.value=String(promptValue);const negEl=document.getElementById('param_negative');if(negEl&&negativeValue!==undefined&&negativeValue!==null)negEl.value=String(negativeValue);const loraDetails=document.querySelector('#wfForm .lora-settings');if(loraDetails)loraDetails.open=true;const targetSlot=firstExpired||firstRestored;if(targetSlot){const slotBtn=document.querySelector('#wfForm .compact-media-slot[data-slot="'+targetSlot+'"]');if(slotBtn&&!slotBtn.hidden)slotBtn.click()}const scroller=document.querySelector('.creation-scroll'),formEl=document.getElementById('wfForm');if(scroller)scroller.scrollTo({top:0,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});else if(formEl?.scrollIntoView)formEl.scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});return{expiredCount}}
async function redoVideoTask(t){
  if(t.redoBusy||!canRedoVideoTask(t.job))return;t.redoBusy=true;t.redoEl.disabled=t.redoQuickEl.disabled=true;
  const status=document.getElementById('genStatus');status.textContent='正在恢复任务配置…';
  try{const draft=await api('/api/video-redo-draft?job_id='+encodeURIComponent(t.job.id),{signal:AbortSignal.timeout(20000)});const {expiredCount}=restoreVideoTaskDraft(draft,t.job);localStorage.removeItem(pendingVideoSubmitKey);status.textContent=expiredCount?'已恢复任务配置；原素材已过期，请重新上传后再点生成':'✓ 已恢复任务配置，修改后点生成'}
  catch(e){status.textContent='恢复任务配置失败：'+e.message}
  finally{t.redoBusy=false;t.redoEl.disabled=t.redoQuickEl.disabled=false}
}
function openQueueEditor(job){
  if(!job?.editable||document.getElementById('queueEditor'))return;const w=WFS.find(w=>w.id===job.workflow);if(!w)return;
  const dialog=document.createElement('dialog'),form=document.createElement('form'),title=document.createElement('h3'),note=document.createElement('p'),actions=document.createElement('div'),save=document.createElement('button'),cancel=document.createElement('button'),fields=new Map();dialog.id='queueEditor';dialog.className='queue-editor';form.className='form';title.textContent='编辑等待任务';note.textContent='素材：'+(Object.values(job.media||{}).join('、')||'无')+'。保存前若任务已开始，会拒绝修改；更换素材请取消后重新提交。';form.append(title,note);
  for(const [key,p] of Object.entries(w.rh_params||{})){const label=document.createElement('label');label.textContent=p.label||key;let input;
    if(p.type==='select'){input=document.createElement('select');for(const option of p.options||[]){const el=document.createElement('option');el.value=optionValue(option);el.textContent=optionLabel(option);input.append(el)}}
    else if(p.type==='boolean'){input=document.createElement('input');input.type='checkbox'}
    else{input=document.createElement(['text','textarea'].includes(p.type)||['prompt','negative'].includes(key)?'textarea':'input');if(input.tagName==='INPUT'){input.type='text';input.inputMode='decimal'}}
    input.dataset.paramType=p.vtype||p.type||'text';input.name=key;if(input.type==='checkbox')input.checked=job.params?.[key]===true;else input.value=job.params?.[key]??p.default??'';label.append(input);form.append(label);fields.set(key,input);
  }
  save.type='submit';save.textContent='保存修改';cancel.type='button';cancel.textContent='返回';cancel.onclick=()=>dialog.close();actions.className='queue-actions';actions.append(save,cancel);form.append(actions);dialog.append(form);document.body.append(dialog);dialog.addEventListener('close',()=>dialog.remove(),{once:true});
  installWorkflowToggleButtons(form);
  form.onsubmit=async e=>{e.preventDefault();save.disabled=true;const params={};for(const [key,input] of fields){if(input.type==='checkbox')params[key]=input.checked;else if(input.value!=='')params[key]=input.value}if(await queueAction(job,'edit',{params}))dialog.close();else{save.disabled=false;note.textContent='保存失败，原任务未被此操作修改。请关闭编辑窗，核对最新队列状态后重试。'}};dialog.showModal();
}
async function generate(){
  if(genRunning||!cur)return;
  const workflow=cur,state=ensureMediaState(workflow.id),st=document.getElementById('genStatus');
  let params;try{params=collectParams()}catch(e){st.textContent=e.message;return}
  const active=Object.entries(workflow.rh_media||{}).filter(([,m])=>videoInputEnabled(workflow,m,params));
  if(active.some(([key])=>state.uploading[key])){st.textContent='素材仍在上传，请完成后再生成';return}
  const missing=active.filter(([key,m])=>m.required&&!state.tokens[key]);
  if(missing.length){st.textContent='缺少必传素材：'+missing.map(([,m])=>m.label).join('、');return}
  const prompt=(document.getElementById('param_prompt')?.value||'').trim();
  if(!prompt){st.textContent='提示词不能为空';return}
  genRunning=true;const btn=document.getElementById('genBtn');btn.disabled=true;btn.classList.add('is-loading');
  st.textContent='正在提交…';document.getElementById('genResult').innerHTML='';
  let pending={};try{pending=JSON.parse(localStorage.getItem(pendingVideoSubmitKey)||'{}')}catch{}
  const client_request_id=pending.workflow===workflow.id&&pending.id?pending.id:'video-'+Date.now()+'-'+Math.random().toString(36).slice(2);
  localStorage.setItem(pendingVideoSubmitKey,JSON.stringify({workflow:workflow.id,id:client_request_id}));
  try{
    const media=Object.fromEntries(active.filter(([key])=>state.tokens[key]).map(([key])=>[key,state.tokens[key]]));
    const submittedFiles=Object.fromEntries(active.filter(([key])=>state.files[key]).map(([key])=>[key,state.files[key]]));
    const body={workflow:workflow.id,prompt,negative_prompt:String(document.getElementById('param_negative')?.value??state.negativePrompt??'').trim(),media,params,client_request_id};
    const r=await api('/api/video-generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    localStorage.removeItem(pendingVideoSubmitKey);if(!r.job_id)throw new Error(r.error||'提交失败');
    addTaskCard(r.job_id,workflow.name);persistTaskThumbnails(r.job_id,submittedFiles,workflow);
    st.textContent='✓ 已提交，任务 '+r.job_id+' 在下方队列中';pollTask(r.job_id);
  }catch(e){const definitiveRejection=e.status>=400&&e.status<500;if(definitiveRejection)localStorage.removeItem(pendingVideoSubmitKey);st.textContent='✗ '+e.message+(definitiveRejection?'':'；网络不明时再次点击会复用请求号')}
  finally{genRunning=false;btn.classList.remove('is-loading');btn.disabled=false}
}
let historyVersion=0;
function sourceThumbnail(job){return safeMediaUrl(Object.values(job.thumbnails||{}).find(src=>typeof src==='string'&&src.startsWith('/api/video-thumbnail/')))}
function configurationDetails(job,className='favorite-details'){const details=document.createElement('details'),summary=document.createElement('summary'),text=document.createElement('div');details.className=className;summary.textContent='提示词与 LoRA 配置';text.className='library-configuration';text.textContent=jobConfigurationText(job);details.append(summary,text);if(className==='history-details'&&!job.params){let loaded=false;details.ontoggle=async()=>{if(!details.open||loaded)return;loaded=true;text.textContent='加载详情…';try{text.textContent=jobConfigurationText(await api('/api/job/'+encodeURIComponent(job.id)))}catch(e){loaded=false;text.textContent='详情读取失败：'+e.message}}}return details}
async function history(){
  const l=document.getElementById('histList'),version=++historyVersion;let cursor=null,busy=false,seen=new Set();l.replaceChildren();
  const more=document.createElement('button');more.className='dl';more.textContent='加载中…';l.append(more);
  const load=async()=>{if(busy)return;busy=true;more.disabled=true;more.textContent='加载中…';try{
    const query=new URLSearchParams({scope:'video',limit:'20'});if(cursor)query.set('before',JSON.stringify(cursor));
    const rows=await api('/api/jobs?'+query);if(version!==historyVersion)return;
    for(const j of rows){if(seen.has(j.id))continue;seen.add(j.id);const d=document.createElement('div'),title=document.createElement('b'),note=document.createElement('div'),button=document.createElement('button'),preview=document.createElement('div'),content=document.createElement('div'),filename=document.createElement('div');d.className='job history-card';preview.className='history-thumbnail';const src=sourceThumbnail(j);if(src){const img=document.createElement('img');img.src=src;img.loading='lazy';img.decoding='async';img.alt='原视频首帧';preview.append(img)}else preview.textContent='暂无首帧';content.className='history-summary';title.textContent=j.wf_name||WFS.find(w=>w.id===j.workflow)?.name||'视频';note.className='note';note.textContent=({done:'已完成',error:'失败',cancelled:'已取消',queued:'排队中',running:'生成中',recovering:'核对中'}[j.status]||j.status)+' · '+new Date(j.created*1000).toLocaleString()+' · '+videoCoinText(j);filename.className='note';filename.textContent=j.media?.source_video||Object.values(j.media||{}).join(' · ');button.className='dl';button.textContent='播放结果';button.disabled=j.status!=='done';button.onclick=async()=>{button.disabled=true;try{const full=await api('/api/job/'+encodeURIComponent(j.id));if(!(full.images||[]).length)throw new Error('暂无可播放结果');histOverlay.classList.remove('open');renderTaskResult(full)}catch(e){note.textContent='读取结果失败：'+e.message}finally{button.disabled=false}};content.append(title,note,filename,button);d.append(preview,content,configurationDetails(j,'history-details'));l.insertBefore(d,more)}
    if(rows.length){const last=rows[rows.length-1];cursor=[last.created,last.id]}
    more.hidden=rows.length<20;more.textContent='加载更早记录';
    if(!seen.size){const empty=document.createElement('p');empty.className='note';empty.textContent='当前浏览器会话暂无视频历史；更换浏览器或清除 Cookie 后不会显示原会话记录。';l.insertBefore(empty,more)}
  }catch(e){more.hidden=false;more.textContent='加载失败，点击重试：'+e.message}finally{busy=false;more.disabled=false}};more.onclick=load;await load();
}
async function saveGalleryFavorite(item,button){
  button.disabled=true;button.textContent='正在收藏…';
  try{const f=await api('/api/favorites',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:item.j.id,image_index:item.i}),signal:AbortSignal.timeout(20000)});button.textContent=f.archive_status==='saving'?'已加入收藏 · 后台保存中':'✓ 已收藏';if(f.archive_status==='saving')watchFavorite(f.id,button)}catch(e){button.disabled=false;button.textContent='收藏未确认，点击重试';button.title=e.message}
}
function watchFavorite(id,button){setTimeout(async()=>{if(!button.isConnected)return;try{const rows=await api('/api/favorites'),f=rows.find(x=>x.id===id);if(!f){button.disabled=false;button.textContent='请打开收藏核对';return}if(f.archive_status==='saving')return watchFavorite(id,button);button.textContent=f.archive_status==='error'?'保存失败，点击重试':'✓ 已收藏';button.disabled=f.archive_status!=='error';button.title=f.archive_error||''}catch{button.disabled=false;button.textContent='状态未确认，点击重试'}},4000)}
let favoriteTimer=null,favoriteVersion=0;
async function favorites(){
  clearTimeout(favoriteTimer);const l=document.getElementById('favList'),version=++favoriteVersion;if(!l.querySelector('.favorite-card'))l.textContent='加载中…';
  try{const rows=(await api('/api/favorites')).filter(f=>f.style_id==='video'||String(f.favorite_media_type||'').startsWith('video/'));if(version!==favoriteVersion)return;const existing=new Map(Array.from(l.querySelectorAll('.favorite-card')).map(d=>[d.dataset.favoriteId,d]));if(!existing.size)l.replaceChildren();
    for(const f of rows){let d=existing.get(f.id);existing.delete(f.id);if(!d){d=document.createElement('div');d.className='job favorite-card';d.dataset.favoriteId=f.id;const promptNode=document.createElement('div');promptNode.className='note favorite-prompt';promptNode.textContent=f.prompt||f.selection_snapshot?.params?.prompt||'视频收藏';const holder=document.createElement('div');holder.className='favorite-media';d.append(promptNode,holder,configurationDetails(f));l.append(d)}
      const holder=d.querySelector('.favorite-media'),signature=(f.archive_status||'ready')+'|'+f.image_url;
      if(holder.dataset.state===signature)continue;holder.dataset.state=signature;holder.replaceChildren();
      if(f.archive_status==='saving'||f.archive_status==='error'){const status=document.createElement('div');status.className='note';status.textContent=f.archive_status==='saving'?'后台保存中，完成后可播放和下载':publicMessage(f.archive_error)||'保存失败';holder.append(status);if(f.archive_status==='error'){const retry=document.createElement('button');retry.className='dl';retry.textContent='重试保存';retry.onclick=async()=>{await saveGalleryFavorite({j:{id:f.job_id},i:f.image_index},retry);favorites()};holder.append(retry)}}
      else{const isVideo=String(f.favorite_media_type||'').startsWith('video/'),media=document.createElement(isVideo?'video':'img');media.src=safeMediaUrl(f.image_url);if(isVideo){media.controls=true;media.playsInline=true;media.preload='metadata';const poster=sourceThumbnail(f);if(poster)media.poster=poster;const error=document.createElement('div'),retry=document.createElement('button');error.className='favorite-playback-error note';error.hidden=true;error.textContent='视频读取失败，请重试';retry.type='button';retry.className='dl';retry.textContent='重新加载视频';retry.onclick=()=>{error.hidden=true;media.load();media.play().catch(()=>{})};error.append(retry);media.onerror=()=>error.hidden=false;holder.append(media,error)}else{media.loading='lazy';holder.append(media)}const link=document.createElement('a');link.className='dl';link.href=safeMediaUrl(f.image_url);link.target='_blank';link.rel='noopener noreferrer';link.textContent='下载';holder.append(link)}
    }
    existing.forEach(d=>d.remove());if(!rows.length)l.textContent='当前浏览器会话暂无视频收藏';l.querySelector('.favorite-list-error')?.remove();
    if(rows.some(f=>f.archive_status==='saving'))favoriteTimer=setTimeout(()=>{if(favOverlay.classList.contains('open'))favorites()},5000);
  }catch(e){if(version!==favoriteVersion)return;let error=l.querySelector('.favorite-list-error');if(!error){if(!l.querySelector('.favorite-card'))l.replaceChildren();error=document.createElement('div');error.className='favorite-list-error note';l.append(error)}error.textContent='收藏加载失败：'+e.message;const retry=document.createElement('button');retry.className='dl';retry.textContent='重新加载';retry.onclick=favorites;error.append(retry)}
}
window.addEventListener('pagehide',()=>mediaStateByWorkflow.forEach((_,workflowId)=>revokeWorkflowMediaPreviews(workflowId)));document.addEventListener('paste',pasteReferenceImage);document.getElementById('genBtn').onclick=generate;document.getElementById('galleryPrev').onclick=()=>selectGalleryItem(galleryIndex-1);document.getElementById('galleryNext').onclick=()=>selectGalleryItem(galleryIndex+1);document.getElementById('histOpen').onclick=()=>{histOverlay.querySelector('.library-scroll').scrollTop=0;histOverlay.classList.add('open');history()};document.getElementById('favOpen').onclick=()=>{favOverlay.querySelector('.library-scroll').scrollTop=0;favOverlay.classList.add('open');favorites()};document.querySelectorAll('.library-overlay .close').forEach(b=>b.onclick=()=>b.closest('.library-overlay').classList.remove('open'));installVideoClearControls();init().then(()=>recoverTasks());
const CREATOR_ROUTES=['/','/realism','/video'];function scheduleRoutePrefetch(){}scheduleRoutePrefetch();
return {styleBoot:null};
}