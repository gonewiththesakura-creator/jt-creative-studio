export function mount({document,window,fetch,location,localStorage,sessionStorage}){
const workflowPreview=document.getElementById("workflowPreview");
const previewEmpty=document.getElementById("previewEmpty");
const previewMessage=document.getElementById("previewMessage");
const workflowPreviewCaption=document.getElementById("workflowPreviewCaption");
const subworkflowPanel=document.getElementById("subworkflowPanel");
const operateControls=document.getElementById("operateControls");
const commonControls=document.getElementById("commonControls");
const advancedControls=document.getElementById("advancedControls");
const workflowNote=document.getElementById("workflowNote");
const generateBtn=document.getElementById("generateBtn");
const workflowSelect=document.getElementById("workflowSelect");
const generateStatus=document.getElementById("generateStatus");
const commonDrawer=document.getElementById("commonDrawer");
const advancedDrawer=document.getElementById("advancedDrawer");
const favOverlay=document.getElementById("favOverlay");
const histOverlay=document.getElementById("histOverlay");
const galleryPrev=document.getElementById("galleryPrev");
const galleryNext=document.getElementById("galleryNext");
const histOpen=document.getElementById("histOpen");
const favOpen=document.getElementById("favOpen");
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


const api=async(path,opt={})=>{const response=await fetch(path,opt);let data={};try{data=await response.json()}catch{}if(!response.ok){const error=new Error(data.error||('HTTP '+response.status));error.data=data;error.status=response.status;throw error}return data};
const ACTIVE_KEY='jt-active-realism-jobs',SOURCE_PAGE='realism',pendingSubmitKey='jt-pending-realism-submit';let workflows=[],current=null,renderVersion=0;const stateByWorkflow=new Map(),controlRefs=new Map();
const WORKFLOW_PREVIEWS={"realcomic":"/static/assets/preview.18b706ed4425.webp","realism_krea2":"/static/assets/preview.0270fd69a8bc.webp","realism_2511":"/static/assets/preview.a48410e17fed.webp","realism_multisample":"/static/assets/preview.68719c8f1d52.webp","realism_qwen_zi":"/static/assets/preview.cb120bd36fb8.webp","realism_zi_flowmatch":"/static/assets/preview.de1d1cf19403.webp"},WORKFLOW_PREVIEW_THUMBS={"realcomic":"/static/assets/preview.46d999fa4701.webp","realism_krea2":"/static/assets/preview.90ed3cae61e4.webp","realism_2511":"/static/assets/preview.ed7e8d525912.webp","realism_multisample":"/static/assets/preview.7e08581ad5d0.webp","realism_qwen_zi":"/static/assets/preview.b501ee909520.webp","realism_zi_flowmatch":"/static/assets/preview.a7f9d2af5597.webp"},previewCache=new Map();
function preloadImage(url){if(!url)return Promise.resolve('');if(previewCache.has(url))return previewCache.get(url);const promise=new Promise(resolve=>{const image=new Image();image.decoding='async';image.onload=()=>resolve(url);image.onerror=()=>resolve('');image.src=url});previewCache.set(url,promise);return promise}
async function preloadWorkflowPreviews(){await Promise.all(Object.values(WORKFLOW_PREVIEW_THUMBS).map(preloadImage))}
async function loadFullWorkflowPreview(id,url){if(!url)return;const loaded=await preloadImage(url);if(loaded&&current?.id===id&&!tasks.size)workflowPreview.src=loaded}
function currentPreviewUrl(){return current?WORKFLOW_PREVIEWS[current.id]||'':''}function updateWorkflowPreview(){if(tasks.size){previewEmpty.classList.add('hidden');return}const id=current?.id||'',full=currentPreviewUrl(),thumb=current?WORKFLOW_PREVIEW_THUMBS[current.id]||full:'';workflowPreview.classList.toggle('visible',Boolean(thumb));previewMessage.classList.toggle('hidden',Boolean(thumb));workflowPreviewCaption.hidden=!thumb;if(thumb){workflowPreview.src=thumb;workflowPreview.alt=current.name+'效果预览';workflowPreviewCaption.textContent=current.name+' · 效果预览';loadFullWorkflowPreview(id,full)}else{workflowPreview.removeAttribute('src');workflowPreviewCaption.textContent=''}previewEmpty.classList.remove('hidden')}
function getActiveIds(){try{const ids=JSON.parse(sessionStorage.getItem(ACTIVE_KEY)||'[]').filter(Boolean),legacy=sessionStorage.getItem('jt-active-realcomic-cloud');if(legacy)ids.push(legacy);return[...new Set(ids)]}catch{return[]}}function setActiveIds(ids){sessionStorage.setItem(ACTIVE_KEY,JSON.stringify([...new Set(ids)]));sessionStorage.removeItem('jt-active-realcomic-cloud')}function rememberActiveJob(id){setActiveIds([...getActiveIds(),id])}function forgetActiveJob(id){setActiveIds(getActiveIds().filter(item=>item!==id))}
function optionValue(option){return typeof option==='object'?String(option.value??option.index??option.name??''):String(option)}function optionLabel(option){return typeof option==='object'?String(option.label??option.name??option.value??option.index??''):String(option)}
function ensureState(workflow){if(!stateByWorkflow.has(workflow.id)){const params={},media={};Object.entries(workflow.rh_params||{}).forEach(([key,mapping])=>{if(Object.prototype.hasOwnProperty.call(mapping,'default'))params[key]=mapping.default;else if(Object.prototype.hasOwnProperty.call(workflow.params_defaults||{},key))params[key]=workflow.params_defaults[key];else if(mapping.type==='boolean')params[key]=false;else params[key]=''});stateByWorkflow.set(workflow.id,{params,media,mediaNames:{},uploadIds:{}})}const state=stateByWorkflow.get(workflow.id);state.uploadIds??={};return state}
function controlShell(key,mapping){const box=document.createElement('article');box.className='control';box.dataset.controlKey=key;const title=document.createElement('div'),caption=document.createElement('span');title.className='control-head';caption.className='control-title';caption.textContent=String(mapping.label||key);if(mapping.required){const required=document.createElement('span');required.className='required';required.textContent=' *';caption.appendChild(required)}title.appendChild(caption);box.appendChild(title);if(mapping.description||mapping.help){const help=document.createElement('div');help.className='control-help';help.textContent=String(mapping.description||mapping.help);box.appendChild(help)}return box}
function renderTextControl(key,mapping,state){const box=controlShell(key,mapping),control=document.createElement('textarea');control.value=String(state.params[key]??'');control.placeholder=String(mapping.placeholder||'');control.maxLength=Number(mapping.max_length||10000);control.oninput=()=>state.params[key]=control.value;box.appendChild(control);controlRefs.set(key,{type:'text',mapping,control});if(['prompt','instruction','requirements'].includes(key))renderPromptPresets(box,control,current.id);return box}
function renderBooleanControl(key,mapping,state){const box=controlShell(key,mapping),row=document.createElement('label'),control=document.createElement('input');row.className='bool-row';row.append(document.createTextNode('关闭 / 开启'),control);control.type='checkbox';control.setAttribute('aria-label',mapping.label||key);control.checked=state.params[key]===true;control.onchange=()=>{state.params[key]=control.checked;updateDependencies();updateGenerateAvailability()};box.appendChild(row);controlRefs.set(key,{type:'boolean',mapping,control,box});return box}
function renderSelectControl(key,mapping,state){const box=controlShell(key,mapping),control=document.createElement('select');(mapping.options||[]).forEach(option=>{const item=document.createElement('option');item.value=optionValue(option);item.textContent=optionLabel(option);control.appendChild(item)});control.value=String(state.params[key]??optionValue((mapping.options||[])[0]||''));control.onchange=()=>state.params[key]=control.value;box.appendChild(control);controlRefs.set(key,{type:'select',mapping,control});return box}
function renderNumberControl(key,mapping,state){const box=controlShell(key,mapping),control=document.createElement('input');control.type='number';if(mapping.min!==undefined)control.min=mapping.min;if(mapping.max!==undefined)control.max=mapping.max;if(mapping.step!==undefined)control.step=mapping.step;else control.step=mapping.type==='int'?'1':'any';control.value=state.params[key]??'';control.oninput=()=>state.params[key]=readControlValue({type:mapping.type,mapping,control});box.appendChild(control);controlRefs.set(key,{type:mapping.type,mapping,control,box});return box}
function readControlValue(ref){if(ref.type==='image')return undefined;if(ref.type==='boolean')return ref.control.checked;if(ref.type==='int')return ref.control.value;if(ref.type==='float'||ref.type==='number')return ref.control.value===''?'':Number(ref.control.value);return ref.control.value}
function groupFor(key,mapping){if(mapping.group==='advanced'||mapping.group==='output')return'advanced';if(mapping.group==='common')return'common';return /seed|step|cfg|denoise|strength|scale|upscale|output|route|branch|mode/i.test(key)?'advanced':'common'}
function renderControl(key,mapping,state,version){const type=String(mapping.type||'text').toLowerCase();if(type==='image')return renderImageControl(key,mapping,state,version);if(['text','string','textarea'].includes(type))return renderTextControl(key,mapping,state);if(['boolean','bool','switch'].includes(type))return renderBooleanControl(key,mapping,state);if(['select','enum','combo'].includes(type))return renderSelectControl(key,mapping,state);if(['int','integer','float','number'].includes(type)){const normalized={...mapping,type:type==='integer'?'int':type};return renderNumberControl(key,normalized,state)}const unsupported=controlShell(key,mapping);unsupported.append('该控件类型暂不支持：'+type);return unsupported}
function isCoreOperateControl(mapping){const type=String(mapping.type||'text').toLowerCase();return mapping.required&&(type==='image'||['text','string','textarea'].includes(type))}
function isInputEnabled(mapping,state){const rule=mapping.depends_on;return !rule||state.params[rule.key]===rule.value}
function updateDependencies(){const state=ensureState(current);controlRefs.forEach(ref=>{if(!ref.mapping.depends_on)return;const enabled=isInputEnabled(ref.mapping,state);ref.control.disabled=!enabled;if(ref.type==='image'){ref.drop.hidden=!enabled;ref.status.hidden=!enabled}else ref.box?.classList.toggle('disabled',!enabled)})}
function renderSubworkflows(){subworkflowPanel.replaceChildren();if(current.subworkflows?.length){const title=document.createElement('div');title.className='field-label';title.textContent='3in1子功能';const box=document.createElement('div');box.className='config-stack';current.subworkflows.forEach(item=>{const row=document.createElement('button');row.type='button';row.className='config-drawer-head';row.disabled=!item.available;row.textContent=item.label+(item.available?' · 当前可用':' · 暂不可用：'+item.reason);box.appendChild(row)});subworkflowPanel.append(title,box)}if(current.fixed_features?.length){const fixed=document.createElement('div');fixed.className='workflow-note';fixed.textContent=current.fixed_features.join('；');subworkflowPanel.appendChild(fixed)}}
function renderForm(){document.querySelector('.creation-scroll')._compactUploads?.destroy();renderVersion++;controlRefs.clear();renderSubworkflows();const version=renderVersion,state=ensureState(current);operateControls.innerHTML='';commonControls.innerHTML='';advancedControls.innerHTML='';Object.entries(current.rh_media||{}).forEach(([key,mapping])=>{const target=isCoreOperateControl(mapping)?operateControls:commonControls;target.appendChild(renderControl(key,mapping,state,version))});Object.entries(current.rh_params||{}).forEach(([key,mapping])=>{if(controlRefs.has(key))return;let target;if(isCoreOperateControl(mapping))target=operateControls;else target=groupFor(key,mapping)==='advanced'?advancedControls:commonControls;target.appendChild(renderControl(key,mapping,state,version))});if(!operateControls.children.length)operateControls.innerHTML='<div class="config-state">此方案无需上传素材</div>';if(!commonControls.children.length)commonControls.innerHTML='<div class="config-state">此方案没有额外常用设置</div>';if(!advancedControls.children.length)advancedControls.innerHTML='<div class="config-state">此方案没有额外高级设置</div>';workflowNote.textContent=current.desc||'';updateDependencies();updateGenerateAvailability();installImageCompactForm()}
function updateGenerateAvailability(){if(!current){generateBtn.disabled=true;generateBtn.textContent='没有可用工作流';return}const state=ensureState(current),media=Object.entries(current.rh_media||{}).filter(([,mapping])=>isInputEnabled(mapping,state)),missing=media.filter(([key,mapping])=>mapping.required&&!state.media[key]).map(([,mapping])=>mapping.label);generateBtn.disabled=missing.length>0||media.some(([key])=>state.uploading?.[key]);generateBtn.textContent=missing.length?'请先上传：'+missing.join('、'):'开始运行 '+current.name}
function selectWorkflow(id){current=workflows.find(item=>item.id===id)||workflows[0]||null;if(!current)return updateGenerateAvailability();workflowSelect.value=current.id;renderForm();updateWorkflowPreview()}
function showWorkflowLoadError(error){const box=document.createElement('div'),retry=document.createElement('button');box.className='config-state error';box.textContent='工作流配置加载失败：'+error.message;retry.className='retry';retry.type='button';retry.textContent='重新加载';retry.onclick=loadWorkflows;box.appendChild(document.createElement('br'));box.appendChild(retry);commonControls.replaceChildren(box);const empty=document.createElement('div');empty.className='config-state';empty.textContent='没有提交任何任务';advancedControls.replaceChildren(empty)}
async function loadWorkflows(){workflowSelect.disabled=true;workflowSelect.innerHTML='<option>正在加载…</option>';generateBtn.disabled=true;try{const all=await api('/api/workflows');workflows=all.filter(item=>['rh_workflow','ai_app'].includes(item.kind));if(!workflows.length)throw new Error('配置中没有可用的图片编辑方案');workflowSelect.innerHTML='';workflows.forEach(workflow=>{const option=document.createElement('option');option.value=workflow.id;option.textContent=workflow.name;workflowSelect.appendChild(option)});workflowSelect.disabled=false;const requested=new URLSearchParams(location.search).get('workflow');selectWorkflow(workflows.some(x=>x.id===requested)?requested:(workflows.find(w=>w.id==='qwen21_wardrobe')||workflows[0]).id)}catch(error){current=null;workflowSelect.innerHTML='<option>加载失败</option>';showWorkflowLoadError(error);generateStatus.textContent='请检查服务后重试';updateGenerateAvailability()}}
function blobToB64(blob){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=reject;reader.readAsDataURL(blob)})}
function snapshotSelections(){const state=ensureState(current);controlRefs.forEach((ref,key)=>{if(ref.type!=='image')state.params[key]=readControlValue(ref)});return{source_page:SOURCE_PAGE,workflow:current.id,params:JSON.parse(JSON.stringify(state.params)),media:JSON.parse(JSON.stringify(state.media)),media_names:JSON.parse(JSON.stringify(state.mediaNames))}}
function applySnapshot(snapshot){if(!snapshot||![SOURCE_PAGE,'realcomic'].includes(snapshot.source_page))return;const workflow=workflows.find(item=>item.id===(snapshot.workflow||'realcomic'));if(!workflow)return;const params=snapshot.source_page==='realcomic'?{requirements:snapshot.requirements||''}:JSON.parse(JSON.stringify(snapshot.params||{}));stateByWorkflow.set(workflow.id,{params,media:{},mediaNames:JSON.parse(JSON.stringify(snapshot.media_names||{}))});selectWorkflow(workflow.id);commonDrawer.classList.add('open');advancedDrawer.classList.add('open');generateStatus.textContent='参数已恢复；云端素材已过期，请重新上传';favOverlay.classList.remove('open')}
function statusText(job){const phase=job.provider_status||job.status;if(job.status==='done')return'✓ 已完成';if(job.status==='error')return'✗ '+(job.error||'失败');if(phase==='SUBMITTING')return'正在提交';if(phase==='QUEUED')return'排队中';if(phase==='RUNNING')return'运行中';if(phase==='FINALIZING')return'正在整理结果';return phase||'处理中'}
function coinText(job){if(job.rh_coins!==null&&job.rh_coins!==undefined&&job.rh_coins!=='')return'RH币：'+String(job.rh_coins);return(job.status==='done'||job.status==='error')?'RH币：未返回':'RH币：统计中'}
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
  if(videoClearBusy)return;videoClearBusy=true;const controls=document.querySelectorAll('.video-clear');controls.forEach(el=>el.disabled=true);const label=button.textContent,status=document.getElementById('generateStatus');button.textContent='清除中…';
  try{const result=await api('/api/image-edit-clear',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scope}),signal:AbortSignal.timeout(20000)});if(!result.ok||!Array.isArray(result.cleared_ids))throw new Error('清除结果未确认');const ids=new Set(result.cleared_ids);removeGalleryJobs(ids);if(scope!=='gallery'){closeTaskDetails();ids.forEach(id=>{clearedTaskJobs.add(id);removeTaskCard(id)});historyVersion++;if(histOverlay.classList.contains('open'))await history()}await refreshVideoQueue();document.getElementById('previewEmpty').classList.toggle('hidden',tasks.size>0||galleryItems.length>0);status.textContent='已清除 '+ids.size+' 个'+({history:'历史任务',errors:'错误任务',gallery:'结果列表任务'}[scope]);button.title=status.textContent}
  catch(e){status.textContent='清除失败：'+e.message;button.title=status.textContent}
  finally{videoClearBusy=false;button.textContent=label;controls.forEach(el=>el.disabled=false)}
}
function installVideoClearControls(){
  const make=(id,label,scope)=>{const button=document.createElement('button');button.id=id;button.type='button';button.className='video-clear';button.textContent=label;button.title=scope==='gallery'?'清空结果列表，历史与收藏保留':'清除已结束的记录，正在生成和排队的任务保留';button.onclick=()=>clearVideoView(scope,button);return button};
  const header=document.querySelector('#histOverlay .library-header');header.insertBefore(make('clearVideoHistory','清除历史','history'),header.querySelector('.close'));
  document.querySelector('.task-panel-head').append(make('clearVideoErrors','清除错误','errors'));
  const toolbar=document.createElement('div');toolbar.className='gallery-list-tools';const label=document.createElement('span');label.textContent='播放列表';toolbar.append(label,make('clearVideoGallery','清空列表','gallery'));const thumbs=document.getElementById('galleryThumbs');thumbs.parentElement.insertBefore(toolbar,thumbs);
}
function selectGalleryItem(index){if(!galleryItems.length)return;galleryIndex=(index+galleryItems.length)%galleryItems.length;renderMediaGallery(true)}
// Keep the source thumbnail stable; a newly decoded result frame may be black.
function resultThumbnail(item){const url=safeMediaUrl(item.im.url);return resultMediaKind(item.im,url)==='image'?(safeMediaUrl(item.im.preview_url)||url):''}
function jobConfigurationText(job){
  const params=job?.params||job?.selection_snapshot?.params||{},workflow=workflows.find(w=>w.id===job?.workflow),promptKey=['prompt','instruction','requirements','text','positive'].find(key=>params[key]),lines=['提示词：'+(job?.prompt||params[promptKey]||'未记录')];
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
  if(!galleryHint){galleryHint=document.createElement('div');galleryHint.id='galleryJobHint';galleryHint.className='gallery-job-hint';galleryHint.tabIndex=0;galleryHint.setAttribute('role','region');galleryHint.setAttribute('aria-label','图片提示词与参数详情');galleryHint.onpointerenter=()=>clearTimeout(galleryHintTimer);galleryHint.onpointerleave=deferGalleryHintHide;galleryHint.onfocus=()=>clearTimeout(galleryHintTimer);galleryHint.onblur=deferGalleryHintHide;galleryHint.onkeydown=e=>{if(e.key==='Escape'){hideGalleryHint();button.focus()}};document.body.append(galleryHint)}
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
    if(b.dataset.preview!==signature){b.dataset.preview=signature;b.replaceChildren();if(src){const img=document.createElement('img');img.src=src;img.loading='lazy';img.decoding='async';img.alt=resultThumbnail(entry)?'生成结果':'参考图片参考缩略图';b.append(img)}else{const span=document.createElement('span');span.textContent=kind==='video'?'▶':'▧';b.append(span)}}
    b.setAttribute('aria-label','查看结果 '+(index+1));b.setAttribute('aria-pressed',String(index===galleryIndex));
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
  }renderGalleryThumbs();for(const t of tasks.values())t.card.classList.toggle('is-selected',t.job?.id===item.j.id);document.getElementById('mediaGallery').hidden=false;document.getElementById('previewEmpty').classList.add('hidden');
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
  if(tasks.has(jobId))return tasks.get(jobId);const card=document.createElement('div'),tile=document.createElement('button'),thumb=document.createElement('span'),badge=document.createElement('span'),info=document.createElement('div'),name=document.createElement('div'),meta=document.createElement('div'),time=document.createElement('div'),view=document.createElement('button'),files=document.createElement('div'),actions=document.createElement('div');card.className='task-card';card.dataset.jobId=jobId;card.dataset.status='pending';tile.className='task-tile';tile.type='button';tile.setAttribute('aria-label',wfName+' · 同步队列中');thumb.className='task-picture';thumb.textContent='▧';badge.className='task-badge';badge.textContent='同步队列中';info.className='task-details';info.setAttribute('popover','auto');name.className='task-name';name.textContent=wfName;meta.className='task-meta';meta.textContent='已提交，正在同步任务状态';files.className='queue-files';actions.className='queue-actions';actions.hidden=true;time.className='task-time';view.className='task-view';view.type='button';view.textContent='查看结果';view.hidden=true;info.append(name,files,meta,time,actions,view);tile.append(thumb,badge);card.append(tile,info);const group=taskGroup('active');group.lastChild.append(card);group.hidden=false;group.firstChild.textContent='进行中 · '+group.lastChild.children.length;document.getElementById('previewEmpty').classList.add('hidden');const t={card,tile,thumb,badge,info,timeEl:time,metaEl:meta,viewEl:view,filesEl:files,actionsEl:actions,wfName,pendingSince:Date.now(),job:{id:jobId,status:'pending'}};tasks.set(jobId,t);
  let openTimer,closeTimer;
  const clearTimers=()=>{clearTimeout(openTimer);clearTimeout(closeTimer)},position=()=>{const rect=tile.getBoundingClientRect();info.style.left=Math.max(8,Math.min(rect.left,window.innerWidth-info.offsetWidth-8))+'px';const below=window.innerHeight-rect.bottom-14,above=rect.top-14,useBelow=below>=Math.min(info.scrollHeight+32,420)||below>=above;info.style.maxHeight=Math.max(80,useBelow?below:above)+'px';info.style.top=(useBelow?rect.bottom+6:Math.max(8,rect.top-info.offsetHeight-6))+'px'},show=()=>{clearTimers();if(!card.isConnected)return;if(!info.matches(':popover-open'))info.showPopover();position()},hide=()=>{clearTimers();closeTimer=setTimeout(()=>{if(!info.matches(':hover')&&!info.contains(document.activeElement)&&info.matches(':popover-open'))info.hidePopover()},180)};
  tile.onpointerenter=e=>{if(e.pointerType==='touch')return;clearTimers();if(info.matches(':popover-open'))position();else openTimer=setTimeout(()=>{if(tile.matches(':hover'))show()},2000)};tile.onpointerleave=hide;tile.onfocus=show;tile.onclick=()=>{show();if(t.job?.status==='done')view.click()};info.onpointerenter=clearTimers;info.onpointerleave=hide;info.onfocusout=hide;
  t.clearDetailsTimers=clearTimers;t.positionDetails=position;
  for(const [action,label] of [['top','置顶插队'],['up','上移'],['down','下移'],['edit','编辑参数']]){const b=document.createElement('button');b.type='button';b.textContent=label;b.dataset.action=action;b.onclick=()=>{info.hidePopover();return action==='edit'?openQueueEditor(t.job):queueAction(t.job,action)};actions.append(b)}
  const remove=document.createElement('button');remove.type='button';remove.className='task-remove';remove.hidden=true;remove.title='取消任务';remove.setAttribute('aria-label','取消任务');remove.onclick=event=>{event.stopPropagation();if(!t.job||t.busy||t.job.cancel_requested)return;clearTimers();info.hidePopover();queueAction(t.job,t.job.status==='queued'?'cancel':'cancel_running')};card.append(remove);t.removeEl=remove;
  const redo=document.createElement('button'),quickRedo=document.createElement('button');redo.type=quickRedo.type='button';redo.className='task-redo dl';redo.textContent='重做一次';quickRedo.className='task-redo-quick';quickRedo.textContent='↻';quickRedo.title='重做一次（复用素材与配置，更换随机种子）';quickRedo.setAttribute('aria-label','重做一次');redo.hidden=quickRedo.hidden=true;const repeat=event=>{event.stopPropagation();info.hidePopover();redoVideoTask(t)};redo.onclick=quickRedo.onclick=repeat;info.append(redo);card.append(quickRedo);t.redoEl=redo;t.redoQuickEl=quickRedo;return t;
}
function updateTaskThumbnail(t){const entry=galleryItems.find(x=>x.j.id===t.job?.id),result=entry&&resultThumbnail(entry),src=result||t.sourceThumbnail||'',signature=src+'|'+t.job?.status;if(t.thumbSignature===signature)return;t.thumbSignature=signature;t.thumb.replaceChildren();if(src){const img=document.createElement('img');img.src=src;img.loading='lazy';img.decoding='async';img.alt=result?'生成结果缩略图':'参考图片';img.onerror=()=>img.remove();t.thumb.append(img);if(!result){const hint=document.createElement('small');hint.textContent='参考图片';t.thumb.append(hint)}}else t.thumb.textContent=t.job?.status==='done'?'▶':'▧'}
const resultLoads=new Map();let resultLoadChain=Promise.resolve();
function loadCompletedTask(j){if(resultLoads.has(j.id))return resultLoads.get(j.id);const pending=resultLoadChain.then(async()=>{const full=await api('/api/job/'+encodeURIComponent(j.id),{signal:AbortSignal.timeout(20000)});if(!(full.images||[]).length)throw new Error('结果同步中');registerGalleryJob(full,false);const t=tasks.get(j.id);if(t)updateTaskThumbnail(t);return full}).catch(e=>{resultLoads.delete(j.id);const t=tasks.get(j.id);if(t)t.metaEl.textContent+=' · 结果同步中，将自动重试';return null});resultLoads.set(j.id,pending);resultLoadChain=pending.then(()=>{});return pending}
function groupTaskCards(rows){for(const [key,title,statuses] of [['active','进行中',['pending','queued','running','recovering']],['done','已完成',['done']],['other','未完成 · 失败 / 已取消',['error','cancelled']]]){const group=taskGroup(key),items=rows.filter(j=>key==='other'?!['pending','queued','running','recovering','done'].includes(j.status):statuses.includes(j.status));group.hidden=!items.length;group.firstChild.textContent=title+' · '+items.length;const grid=group.lastChild;items.forEach((j,index)=>{const card=tasks.get(j.id).card;if(grid.children[index]!==card)grid.insertBefore(card,grid.children[index]||null)})}if(rows.length)document.getElementById('previewEmpty').classList.add('hidden')}
function removeTaskCard(jobId){const t=tasks.get(jobId);if(!t)return;if(t.timer)clearInterval(t.timer);t.clearDetailsTimers?.();t.card.remove();tasks.delete(jobId);refreshTaskCount()}
function renderTaskResult(j){registerGalleryJob(j);renderMediaGallery(true);document.querySelector('.preview-stage').scrollTo({top:0,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'})}
async function pollTask(jobId){return refreshVideoQueue()}
let queueTimer=null,queueFetching=false,queueRefreshAgain=false;
async function refreshVideoQueue(){
  clearTimeout(queueTimer);if(queueFetching){queueRefreshAgain=true;return}queueFetching=true;
  try{const state=await api('/api/image-edit-queue'),rows=(state.jobs||[]).filter(j=>!['done','error','cancelled'].includes(j.status)||(!j.task_cleared&&!clearedTaskJobs.has(j.id))),ids=new Set(rows.map(j=>j.id)),list=document.getElementById('taskList');
    for(const [id,t] of tasks)if(!ids.has(id)&&(!t.pendingSince||Date.now()-t.pendingSince>60000))removeTaskCard(id);
    removeGalleryJobs(new Set(rows.filter(j=>j.gallery_cleared&&!clearedGalleryJobs.has(j.id)).map(j=>j.id)));
    rows.forEach((j,index)=>{const t=addTaskCard(j.id,j.wf_name||'图片编辑任务');delete t.pendingSince;t.job=j;
      if(!t.configEl){t.configEl=document.createElement('div');t.configEl.className='task-configuration';t.info.insertBefore(t.configEl,t.metaEl)}t.configEl.textContent=jobConfigurationText(j);
      const mediaSignature=JSON.stringify([j.media,j.thumbnails]);if(t.mediaSignature!==mediaSignature){t.mediaSignature=mediaSignature;t.sourceThumbnail=Object.values(j.thumbnails||{}).find(src=>typeof src==='string'&&src.startsWith('/api/video-thumbnail/'));t.filesEl.replaceChildren();for(const [key,name] of Object.entries(j.media||{})){const item=document.createElement('div'),w=workflows.find(w=>w.id===j.workflow);item.className='queue-media';item.textContent=(w?.rh_media?.[key]?.label||'素材')+'：'+name;t.filesEl.append(item)}if(!Object.keys(j.media||{}).length)t.filesEl.textContent='无需上传素材'}
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
  try{await api('/api/image-edit-queue',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:job.id,revision:job.queue_revision,action,...extra})});return true}
  catch(e){document.getElementById('generateStatus').textContent='队列操作失败：'+e.message;return false}
  finally{t.busy=false;await refreshVideoQueue()}
}
async function redoVideoTask(t){
  if(t.redoBusy||!canRedoVideoTask(t.job))return;t.redoBusy=true;t.redoEl.disabled=t.redoQuickEl.disabled=true;
  const pendingKey='jt-pending-video-redo-'+t.job.id,status=document.getElementById('generateStatus');let client_request_id=localStorage.getItem(pendingKey);if(!client_request_id){client_request_id='redo-'+Date.now()+'-'+Math.random().toString(36).slice(2);localStorage.setItem(pendingKey,client_request_id)}status.textContent='正在提交重做…';
  try{const result=await api('/api/image-edit-generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({redo_job_id:t.job.id,client_request_id}),signal:AbortSignal.timeout(20000)});if(!result.job_id)throw new Error('提交结果未确认');localStorage.removeItem(pendingKey);status.textContent='✓ 已加入队列 · 重做任务 '+result.job_id;await refreshVideoQueue()}
  catch(e){const rejected=e.status>=400&&e.status<500;if(rejected)localStorage.removeItem(pendingKey);status.textContent='重做未完成：'+e.message+(rejected?'':'；再次点击会核对同一次提交')}
  finally{t.redoBusy=false;t.redoEl.disabled=t.redoQuickEl.disabled=false}
}
function openQueueEditor(job){
  if(!job?.editable||document.getElementById('queueEditor'))return;const w=workflows.find(w=>w.id===job.workflow);if(!w)return;
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
let historyVersion=0;
function sourceThumbnail(job){return safeMediaUrl(Object.values(job.thumbnails||{}).find(src=>typeof src==='string'&&src.startsWith('/api/video-thumbnail/')))}
function configurationDetails(job,className='favorite-details'){const details=document.createElement('details'),summary=document.createElement('summary'),text=document.createElement('div');details.className=className;summary.textContent='提示词与 LoRA 配置';text.className='library-configuration';text.textContent=jobConfigurationText(job);details.append(summary,text);if(className==='history-details'&&!job.params){let loaded=false;details.ontoggle=async()=>{if(!details.open||loaded)return;loaded=true;text.textContent='加载详情…';try{text.textContent=jobConfigurationText(await api('/api/job/'+encodeURIComponent(job.id)))}catch(e){loaded=false;text.textContent='详情读取失败：'+e.message}}}return details}
async function history(){
  const l=document.getElementById('histList'),version=++historyVersion;let cursor=null,busy=false,seen=new Set();l.replaceChildren();
  const more=document.createElement('button');more.className='dl';more.textContent='加载中…';l.append(more);
  const load=async()=>{if(busy)return;busy=true;more.disabled=true;more.textContent='加载中…';try{
    const query=new URLSearchParams({scope:'realism',limit:'20'});if(cursor)query.set('before',JSON.stringify(cursor));
    const rows=await api('/api/jobs?'+query);if(version!==historyVersion)return;
    for(const j of rows){if(seen.has(j.id))continue;seen.add(j.id);const d=document.createElement('div'),title=document.createElement('b'),note=document.createElement('div'),button=document.createElement('button'),preview=document.createElement('div'),content=document.createElement('div'),filename=document.createElement('div');d.className='job history-card';preview.className='history-thumbnail';const src=sourceThumbnail(j);if(src){const img=document.createElement('img');img.src=src;img.loading='lazy';img.decoding='async';img.alt='参考图片';preview.append(img)}else preview.textContent='暂无缩略图';content.className='history-summary';title.textContent=j.wf_name||workflows.find(w=>w.id===j.workflow)?.name||'视频';note.className='note';note.textContent=({done:'已完成',error:'失败',cancelled:'已取消',queued:'排队中',running:'生成中',recovering:'核对中'}[j.status]||j.status)+' · '+new Date(j.created*1000).toLocaleString()+' · '+videoCoinText(j);filename.className='note';filename.textContent=j.media?.source_video||Object.values(j.media||{}).join(' · ');button.className='dl';button.textContent='查看结果';button.disabled=j.status!=='done';button.onclick=async()=>{button.disabled=true;try{const full=await api('/api/job/'+encodeURIComponent(j.id));if(!(full.images||[]).length)throw new Error('暂无可查看结果');const items=full.images.map((im,i)=>{const url=safeMediaUrl(im.url),kind=resultMediaKind(im,url);return kind==='file'?null:{kind,src:kind==='video'?url:(safeMediaUrl(im.preview_url)||url),full:url,jobId:full.id,index:i,label:title.textContent+' · '+String(im.stage_label||im.file||'结果')}}).filter(Boolean);if(!items.length||window.dispatchEvent(new CustomEvent('jt:lightbox',{cancelable:true,detail:{items}}))){histOverlay.classList.remove('open');renderTaskResult(full)}}catch(e){note.textContent='读取结果失败：'+e.message}finally{button.disabled=false}};content.append(title,note,filename,button);d.append(preview,content,configurationDetails(j,'history-details'));l.insertBefore(d,more)}
    if(rows.length){const last=rows[rows.length-1];cursor=[last.created,last.id]}
    more.hidden=rows.length<20;more.textContent='加载更早记录';
    if(!seen.size){const empty=document.createElement('p');empty.className='note';empty.textContent='还没有图片编辑记录，生成后会出现在这里。';l.insertBefore(empty,more)}
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
  try{const rows=(await api('/api/favorites')).filter(f=>f.style_id==='realism'||['realism','realcomic'].includes(f.selection_snapshot?.source_page));if(version!==favoriteVersion)return;const existing=new Map(Array.from(l.querySelectorAll('.favorite-card')).map(d=>[d.dataset.favoriteId,d]));if(!existing.size)l.replaceChildren();
    for(const f of rows){let d=existing.get(f.id);existing.delete(f.id);if(!d){d=document.createElement('div');d.className='job favorite-card';d.dataset.favoriteId=f.id;const promptNode=document.createElement('div');promptNode.className='note favorite-prompt';promptNode.textContent=f.prompt||f.selection_snapshot?.params?.prompt||'图片编辑收藏';const holder=document.createElement('div');holder.className='favorite-media';const apply=document.createElement('button');apply.type='button';apply.className='dl apply';apply.textContent='套用参数';apply.onclick=()=>applySnapshot(f.selection_snapshot);d.append(promptNode,holder,configurationDetails(f),apply);l.append(d)}
      const holder=d.querySelector('.favorite-media'),signature=(f.archive_status||'ready')+'|'+f.image_url;
      if(holder.dataset.state===signature)continue;holder.dataset.state=signature;holder.replaceChildren();
      if(f.archive_status==='saving'||f.archive_status==='error'){const status=document.createElement('div');status.className='note';status.textContent=f.archive_status==='saving'?'后台保存中，完成后可播放和下载':publicMessage(f.archive_error)||'保存失败';holder.append(status);if(f.archive_status==='error'){const retry=document.createElement('button');retry.className='dl';retry.textContent='重试保存';retry.onclick=async()=>{await saveGalleryFavorite({j:{id:f.job_id},i:f.image_index},retry);favorites()};holder.append(retry)}}
      else{const isVideo=String(f.favorite_media_type||'').startsWith('video/'),media=document.createElement(isVideo?'video':'img');media.src=safeMediaUrl(f.image_url);if(isVideo){media.controls=true;media.playsInline=true;media.preload='metadata';const poster=sourceThumbnail(f);if(poster)media.poster=poster;const error=document.createElement('div'),retry=document.createElement('button');error.className='favorite-playback-error note';error.hidden=true;error.textContent='视频读取失败，请重试';retry.type='button';retry.className='dl';retry.textContent='重新加载视频';retry.onclick=()=>{error.hidden=true;media.load();media.play().catch(()=>{})};error.append(retry);media.onerror=()=>error.hidden=false;holder.append(media,error)}else{media.loading='lazy';holder.append(media)}const link=document.createElement('a');link.className='dl';link.href=safeMediaUrl(f.image_url);link.target='_blank';link.rel='noopener noreferrer';link.textContent='下载';holder.append(link)}
    }
    existing.forEach(d=>d.remove());if(!rows.length)l.textContent='还没有图片编辑收藏。在结果上点收藏，它就会出现在这里。';l.querySelector('.favorite-list-error')?.remove();
    if(rows.some(f=>f.archive_status==='saving'))favoriteTimer=setTimeout(()=>{if(favOverlay.classList.contains('open'))favorites()},5000);
  }catch(e){if(version!==favoriteVersion)return;let error=l.querySelector('.favorite-list-error');if(!error){if(!l.querySelector('.favorite-card'))l.replaceChildren();error=document.createElement('div');error.className='favorite-list-error note';l.append(error)}error.textContent='收藏加载失败：'+e.message;const retry=document.createElement('button');retry.className='dl';retry.textContent='重新加载';retry.onclick=favorites;error.append(retry)}
}

// Image form keeps its native schema controls; task UI comes from the video runtime.
const imagePreviewUrls=new Map();
function installImageCompactForm(){
 const root=document.querySelector('.creation-scroll'),state=ensureState(current),items=[];
 const options=document.createElement('div');options.className='compact-upload-options';operateControls.prepend(options);
 for(const [key,ref] of controlRefs){
  if(ref.type!=='image')continue;
  for(const toggle of ref.box.querySelectorAll('.reference-toggle'))options.append(toggle);
  items.push({key,type:'image',label:ref.mapping.label||key,box:ref.box,drop:ref.drop,
   filled:()=>!!state.media[key],hasFile:()=>!!state.files?.[key],enabled:()=>isInputEnabled(ref.mapping,state)});
 }
 installCompactUploads(root,items,{before:options});installWorkflowToggleButtons(root);
}
function renderImageControl(key,mapping,state,version){
 const box=controlShell(key,mapping),workflow=current,drop=document.createElement('div'),button=document.createElement('button'),input=document.createElement('input'),status=document.createElement('div'),remove=document.createElement('button'),paste=document.createElement('button');
 const dependency=mapping.depends_on,toggle=dependency&&workflow.rh_params?.[dependency.key];if(toggle?.type==='boolean'){const toggleBox=renderBooleanControl(dependency.key,toggle,state);toggleBox.classList.add('reference-toggle');box.append(toggleBox)}
 drop.className='upload-box drop';drop.tabIndex=0;drop.dataset.mediaKey=key;drop.setAttribute('role','group');drop.setAttribute('aria-label',String(mapping.label||'参考图片'));
 button.type='button';button.className='upload-trigger';button.textContent='▧ 上传'+String(mapping.label||'图片');input.type='file';input.accept='image/png,image/jpeg,image/webp';input.hidden=true;
 const help=document.createElement('small');help.textContent='点击或拖入图片 · JPG / PNG / WebP · 最大30MB';status.className='upload-status';status.setAttribute('aria-live','polite');
 remove.type='button';remove.className='media-remove';remove.title='删除已选择图片';remove.setAttribute('aria-label','删除'+String(mapping.label||'图片'));
 paste.type='button';paste.className='paste-target';paste.textContent='粘贴到这里（Ctrl＋V）';paste.onclick=event=>{event.stopPropagation();drop.focus()};
 const showPreview=()=>{drop.querySelector('img')?.remove();const file=state.files?.[key];if(file){const picture=document.createElement('img'),url=URL.createObjectURL(file),old=imagePreviewUrls.get(workflow.id+':'+key);if(old)URL.revokeObjectURL(old);imagePreviewUrls.set(workflow.id+':'+key,url);picture.src=url;picture.className='local-image-preview';picture.alt='已选择的'+String(mapping.label||'图片');drop.append(picture)}remove.hidden=!file&&!state.media[key];drop.classList.toggle('has-file',!!state.media[key])};
 const active=()=>current?.id===workflow.id&&version===renderVersion&&drop.isConnected;
 const acceptFile=async file=>{
  if(!file||!isInputEnabled(mapping,state))return;if(!['image/png','image/jpeg','image/webp'].includes(file.type)||!file.size||file.size>30*1024*1024){status.textContent='请选择30MB以内的 JPG、PNG 或 WebP 图片';return}
  state.uploading??={};state.files??={};const uploadId=(state.uploadIds[key]||0)+1;state.uploadIds[key]=uploadId;state.files[key]=file;state.uploading[key]=true;delete state.media[key];showPreview();status.textContent='上传中…';updateGenerateAvailability();
  try{const query=new URLSearchParams({workflow:workflow.id,input_key:key,filename:file.name});const result=await sendAccountMediaFile('/api/upload?'+query,file,percent=>{if(active()&&state.uploadIds[key]===uploadId)status.textContent=percent<100?'上传中 '+percent+'%':'文件已传完，云端接收中…'});if(state.uploadIds[key]!==uploadId)return;state.media[key]=result.uploadToken;state.mediaNames[key]=file.name;if(active()){drop.classList.add('has-file');status.textContent='✓ '+file.name+' 已上传';status.className='upload-status ok'}}
  catch(error){if(state.uploadIds[key]!==uploadId)return;delete state.media[key];delete state.mediaNames[key];if(active()){status.className='upload-status err';status.textContent='上传未完成：'+error.message;const retry=document.createElement('button');retry.type='button';retry.className='retry';retry.textContent='重试上传';retry.onclick=()=>{retry.remove();acceptFile(file)};box.append(retry)}}
  finally{if(state.uploadIds[key]===uploadId)delete state.uploading[key];if(current?.id===workflow.id)updateGenerateAvailability()}
 };
 remove.onclick=event=>{event.stopPropagation();state.uploadIds[key]=(state.uploadIds[key]||0)+1;delete state.media[key];delete state.mediaNames[key];delete state.files?.[key];delete state.uploading?.[key];const old=imagePreviewUrls.get(workflow.id+':'+key);if(old)URL.revokeObjectURL(old);imagePreviewUrls.delete(workflow.id+':'+key);box.querySelectorAll('.retry').forEach(node=>node.remove());showPreview();status.textContent='尚未上传';status.className='upload-status';updateGenerateAvailability()};
 button.onclick=()=>input.click();drop.onclick=event=>{if(event.target===drop||event.target===help)input.click()};drop.onkeydown=event=>{if(event.target===drop&&(event.key==='Enter'||event.key===' ')){event.preventDefault();input.click()}};input.onchange=()=>{acceptFile(input.files[0]);input.value=''};
 drop.ondragover=event=>{event.preventDefault();drop.classList.add('is-dragging')};drop.ondragleave=()=>drop.classList.remove('is-dragging');drop.ondrop=event=>{event.preventDefault();drop.classList.remove('is-dragging');acceptFile(event.dataTransfer?.files?.[0])};
 drop.append(button,help,paste,remove,input);status.textContent=state.uploading?.[key]?'上传中…':state.media[key]?'✓ '+state.mediaNames[key]+' 已上传':'尚未上传';showPreview();box.append(drop,status);controlRefs.set(key,{type:'image',mapping,control:input,drop,status,box,acceptFile});return box;
}
function pasteImageEditReference(event){
 if(!current||document.body.closest('.page-host')?.hidden||document.getElementById('queueEditor')||histOverlay.classList.contains('open')||favOverlay.classList.contains('open'))return;
 const item=Array.from(event.clipboardData?.items||[]).find(item=>item.kind==='file'&&item.type.startsWith('image/')),file=item?.getAsFile();if(!file)return;
 const refs=Array.from(controlRefs.values()).filter(ref=>ref.type==='image'&&ref.drop.getClientRects().length&&isInputEnabled(ref.mapping,ensureState(current))),focused=refs.find(ref=>ref.drop===document.activeElement||ref.drop.contains(document.activeElement)),target=focused||(refs.length===1?refs[0]:null);if(!target){if(refs.length){event.preventDefault();generateStatus.textContent='请先点击对应图片框的“粘贴到这里”，再按 Ctrl＋V'}return}
 event.preventDefault();target.acceptFile(file);
}
function readParamValue(input){if(input.type==='checkbox')return input.checked;return input.value}
async function submitWorkflow(){
 if(!current||generateBtn.disabled)return;const workflow=current,snapshot=snapshotSelections(),state=ensureState(workflow);generateBtn.disabled=true;generateBtn.setAttribute('aria-busy','true');generateStatus.textContent='正在加入队列…';let pending={};try{pending=JSON.parse(localStorage.getItem(pendingSubmitKey)||'{}')}catch{}
 const client_request_id=pending.workflow===workflow.id&&pending.id?pending.id:'image-edit-'+Date.now()+'-'+Math.random().toString(36).slice(2);localStorage.setItem(pendingSubmitKey,JSON.stringify({workflow:workflow.id,id:client_request_id}));
 const activeEntries=entries=>Object.fromEntries(Object.entries(entries||{}).filter(([key])=>isInputEnabled(workflow.rh_media[key]||{},state))),media=activeEntries(state.media);snapshot.media_names=activeEntries(snapshot.media_names);try{const response=await api('/api/image-edit-generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({workflow:workflow.id,media,params:snapshot.params,selection_snapshot:snapshot,client_request_id}),signal:AbortSignal.timeout(20000)});localStorage.removeItem(pendingSubmitKey);addTaskCard(response.job_id,workflow.name);persistImageTaskThumbnails(response.job_id,activeEntries(state.files));generateStatus.textContent='✓ 已加入图片编辑队列，任务号：'+response.job_id;await refreshVideoQueue()}
 catch(error){const definitiveRejection=error.status>=400&&error.status<500;if(definitiveRejection)localStorage.removeItem(pendingSubmitKey);generateStatus.textContent='提交未完成：'+error.message+(definitiveRejection?'':'；再次点击会复用同一请求号')}
 finally{generateBtn.setAttribute('aria-busy','false');updateGenerateAvailability()}
}
async function persistImageTaskThumbnails(jobId,files){for(const [key,file] of Object.entries(files)){try{const bitmap=await createImageBitmap(file),canvas=document.createElement('canvas'),scale=Math.min(160/bitmap.width,90/bitmap.height,1);canvas.width=Math.max(1,Math.round(bitmap.width*scale));canvas.height=Math.max(1,Math.round(bitmap.height*scale));canvas.getContext('2d').drawImage(bitmap,0,0,canvas.width,canvas.height);bitmap.close();const data=canvas.toDataURL('image/jpeg',.6).split(',')[1];if(data.length>44000)continue;await api('/api/video-thumbnail',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:jobId,key,data})});await refreshVideoQueue()}catch{/* A thumbnail never retries a generation. */}}}
async function restoreTasks(){return refreshVideoQueue()}
document.querySelectorAll('.config-drawer-head').forEach(button=>button.onclick=()=>button.closest('.config-drawer').classList.toggle('open'));
workflowSelect.onchange=()=>selectWorkflow(workflowSelect.value);generateBtn.onclick=submitWorkflow;galleryPrev.onclick=()=>selectGalleryItem(galleryIndex-1);galleryNext.onclick=()=>selectGalleryItem(galleryIndex+1);
histOpen.onclick=()=>{histOverlay.classList.add('open');history()};favOpen.onclick=()=>{favOverlay.classList.add('open');favorites()};document.querySelectorAll('.library-overlay .close').forEach(button=>button.onclick=()=>button.closest('.library-overlay').classList.remove('open'));
document.addEventListener('paste',pasteImageEditReference);window.addEventListener('pagehide',()=>{imagePreviewUrls.forEach(url=>URL.revokeObjectURL(url));imagePreviewUrls.clear()});
installVideoClearControls();loadWorkflows().then(restoreTasks);

return {styleBoot:null};
}