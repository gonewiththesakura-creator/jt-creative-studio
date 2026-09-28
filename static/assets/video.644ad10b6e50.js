export function mount({document,window,fetch,location}){
const histOverlay=document.getElementById("histOverlay");
const favOverlay=document.getElementById("favOverlay");
// A library code is a bearer capability. Never put it in URLs or task payloads.
const tempMedia = {code:localStorage.getItem('jt-media-library')||'',data:null,target:null,busy:false,queue:[],poll:null};
function mediaLibraryIsOpen(){return !!document.getElementById('tempMediaLibrary')?.classList.contains('open')}
async function libraryRequest(action,body,code=tempMedia.code){
  return api('/api/media-library'+(action?'/'+action:''),{method:action?'POST':'GET',headers:{'Content-Type':'application/json','X-Media-Library':code},...(action?{body:JSON.stringify(body||{})}:{}),signal:AbortSignal.timeout(150000)});
}
function libraryNote(text){const note=document.getElementById('tempMediaNote');if(note)note.textContent=text}
function buildMediaLibrary(){
  if(document.getElementById('tempMediaLibrary'))return;
  const overlay=document.createElement('div');overlay.id='tempMediaLibrary';overlay.className='temp-media-overlay';overlay.setAttribute('role','dialog');overlay.setAttribute('aria-modal','true');overlay.setAttribute('aria-label','临时素材库');
  overlay.innerHTML='<section class="temp-media-panel"><header><div><h2>临时素材库</h2><p id="tempMediaExpiry">服务器保存 · 跨电脑复用 · 最多 10 个</p></div><button type="button" class="temp-media-close" aria-label="关闭素材库">×</button></header><div class="temp-media-toolbar"><button type="button" data-action="add">＋ 添加视频／图片</button><button type="button" data-action="copy">复制访问码</button><button type="button" data-action="connect">连接已有素材库</button><button type="button" data-action="new" hidden>新建素材库</button><input type="file" multiple hidden accept=".mp4,.mov,.avi,.webm,.mkv,.png,.jpg,.jpeg,.webp"></div><form class="temp-media-connect" hidden><input aria-label="素材库访问码" placeholder="粘贴另一台电脑的素材库访问码" autocomplete="off" spellcheck="false"><button>连接</button></form><p class="temp-media-hint">可拖入多个文件，或在此按 Ctrl＋V 粘贴图片。访问码可读取和删除素材，请只自己保管。</p><p id="tempMediaNote" role="status"></p><div id="tempMediaGrid" class="temp-media-grid"></div></section>';
  document.body.append(overlay);
  const close=()=>{overlay.classList.remove('open');clearInterval(tempMedia.poll);tempMedia.target?.drop?.focus()};
  overlay.querySelector('.temp-media-close').onclick=close;
  overlay.onclick=e=>{if(e.target===overlay)close()};
  overlay.onkeydown=e=>{if(e.key==='Escape'){e.preventDefault();close()}if(e.key==='Tab'){const focusable=Array.from(overlay.querySelectorAll('button,input')).filter(el=>!el.disabled&&!el.hidden&&!el.closest('[hidden]'));const first=focusable[0],last=focusable.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus()}}};
  const picker=overlay.querySelector('input[type=file]');picker.onchange=()=>{queueLibraryFiles(Array.from(picker.files));picker.value=''};
  overlay.querySelector('[data-action=add]').onclick=()=>picker.click();
  overlay.querySelector('[data-action=copy]').onclick=async()=>{if(!tempMedia.code)return;try{await navigator.clipboard.writeText(tempMedia.code);libraryNote('访问码已复制，在另一台电脑点“连接已有素材库”粘贴即可')}catch{const form=overlay.querySelector('form');form.hidden=false;const input=form.querySelector('input');input.value=tempMedia.code;input.focus();input.select();libraryNote('请按 Ctrl＋C 复制已选中的访问码')}};
  overlay.querySelector('[data-action=connect]').onclick=()=>{const form=overlay.querySelector('form');form.hidden=!form.hidden;if(!form.hidden)form.querySelector('input').focus()};
  overlay.querySelector('form').onsubmit=async e=>{e.preventDefault();if(tempMedia.busy){libraryNote('请等当前文件保存完成后再切换素材库');return}const code=e.target.querySelector('input').value.trim();try{const data=await libraryRequest('',null,code);tempMedia.code=code;tempMedia.data=data;localStorage.setItem('jt-media-library',code);e.target.hidden=true;renderMediaLibrary();libraryNote('已连接素材库')}catch(error){libraryNote(error.message)}};
  overlay.querySelector('[data-action=new]').onclick=()=>refreshMediaLibrary(true).catch(e=>libraryNote(e.message));
  overlay.ondragover=e=>{e.preventDefault();overlay.classList.add('dragging')};overlay.ondragleave=e=>{if(!overlay.contains(e.relatedTarget))overlay.classList.remove('dragging')};
  overlay.ondrop=e=>{e.preventDefault();overlay.classList.remove('dragging');queueLibraryFiles(Array.from(e.dataTransfer?.files||[]))};
  window.addEventListener('paste',e=>{if(!mediaLibraryIsOpen()||document.body.closest('.page-host')?.hidden)return;const files=Array.from(e.clipboardData?.items||[]).filter(i=>i.kind==='file'&&i.type.startsWith('image/')).map(i=>i.getAsFile()).filter(Boolean);if(files.length){e.preventDefault();queueLibraryFiles(files)}});
}
async function refreshMediaLibrary(create=false){
  if(create||!tempMedia.code){const result=await libraryRequest('create');tempMedia.code=result.code;localStorage.setItem('jt-media-library',result.code);tempMedia.data=result}
  else tempMedia.data=await libraryRequest('');
  renderMediaLibrary();
}
async function openMediaLibrary(target=null){
  buildMediaLibrary();tempMedia.target=target;const overlay=document.getElementById('tempMediaLibrary');overlay.classList.add('open');overlay.querySelector('.temp-media-close').focus();
  libraryNote(target?'选择'+target.mapping.label+'，首次选用需等待 RunningHub 接收':'添加后可在上传框中点击“从素材库选择”');
  try{await refreshMediaLibrary()}catch(e){tempMedia.data=null;renderMediaLibrary();libraryNote(e.message)}
  clearInterval(tempMedia.poll);tempMedia.poll=setInterval(()=>{if(!tempMedia.busy)refreshMediaLibrary().catch(e=>{tempMedia.data=null;renderMediaLibrary();libraryNote(e.message);clearInterval(tempMedia.poll)})},30000);
}
function renderMediaLibrary(){
  const grid=document.getElementById('tempMediaGrid');if(!grid)return;grid.replaceChildren();
  const data=tempMedia.data,expired=!data||data.expires*1000<=Date.now(),panel=document.getElementById('tempMediaLibrary');
  panel.querySelector('[data-action=new]').hidden=!expired;panel.querySelector('[data-action=add]').disabled=expired;
  document.getElementById('tempMediaExpiry').textContent=expired?'素材库已过期或无法访问，可连接其他库或新建':`${data.assets.length} / 10 个 · ${new Date(data.expires*1000).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})} 到期自动删除（创建起 2 小时）`;
  if(expired)return;
  for(const asset of data.assets){
    const card=document.createElement('article');card.className='temp-media-card';const preview=document.createElement('div');preview.className='temp-media-cover';
    if(asset.thumbnail){const image=document.createElement('img');image.src='data:image/jpeg;base64,'+asset.thumbnail;image.alt=asset.name;image.loading='lazy';preview.append(image)}else preview.textContent=asset.type==='video'?'▶':'▧';
    const name=document.createElement('div');name.className='temp-media-name';name.textContent=asset.name;name.title=asset.name;
    const meta=document.createElement('small');meta.textContent=(asset.type==='video'?'视频':'图片')+' · '+(asset.size/1024/1024).toFixed(1)+' MB'+(asset.duration?' · '+asset.duration.toFixed(1)+' 秒':'')+(!asset.ready?' · 未完成':'');
    const actions=document.createElement('div');actions.className='temp-media-actions';
    if(tempMedia.target){const use=document.createElement('button');use.type='button';use.textContent='选用';use.disabled=!asset.ready||asset.type!==tempMedia.target.mapping.type;use.onclick=()=>chooseLibraryAsset(asset);actions.append(use)}
    if(!asset.ready&&!tempMedia.busy){const resume=document.createElement('button');resume.type='button';resume.textContent='重选文件续传';resume.onclick=()=>{const input=document.createElement('input');input.type='file';input.accept=mediaAccept(asset.type);input.onchange=()=>{const file=input.files[0];if(!file)return;if(file.name!==asset.name||file.size!==asset.size){libraryNote('请选择相同名称、相同大小的原文件');return}queueLibraryFiles([file],asset)};input.click()};actions.append(resume)}
    const remove=document.createElement('button');remove.type='button';remove.textContent='删除';remove.disabled=tempMedia.busy;remove.onclick=async()=>{remove.disabled=true;try{await libraryRequest('delete',{id:asset.id});await refreshMediaLibrary()}catch(e){libraryNote(e.message);remove.disabled=false}};actions.append(remove);card.append(preview,name,meta,actions);grid.append(card);
  }
  if(!data.assets.length)grid.textContent='还没有素材。一次可选择最多 10 个文件，单个不超过 60MB。';
}
async function libraryThumbnail(file,type){
  if(type==='video'){
    const thumbnail=await prepareVideoThumbnail(file);
    const duration=await new Promise(resolve=>{const video=document.createElement('video'),url=URL.createObjectURL(file);let done=false;const finish=value=>{if(done)return;done=true;clearTimeout(timer);video.removeAttribute('src');video.load();URL.revokeObjectURL(url);resolve(value)};const timer=setTimeout(()=>finish(null),4000);video.onloadedmetadata=()=>finish(Number.isFinite(video.duration)?video.duration:null);video.onerror=()=>finish(null);video.preload='metadata';video.src=url});
    return {thumbnail,duration};
  }
  try{const bitmap=await createImageBitmap(file);try{const scale=Math.min(160/bitmap.width,90/bitmap.height,1),canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.round(bitmap.width*scale));canvas.height=Math.max(1,Math.round(bitmap.height*scale));canvas.getContext('2d').drawImage(bitmap,0,0,canvas.width,canvas.height);return {thumbnail:canvas.toDataURL('image/jpeg',.6).split(',')[1]}}finally{bitmap.close()}}catch{return {thumbnail:null}}
}
async function queueLibraryFiles(files,resume=null){
  if(!tempMedia.data||tempMedia.data.expires*1000<=Date.now()){libraryNote('请先连接或新建素材库');return}
  const available=10-tempMedia.data.assets.length-tempMedia.queue.length-(tempMedia.busy?1:0);
  if(!resume&&files.length>available){libraryNote('剩余位置不足，请最多选择 '+Math.max(0,available)+' 个文件');return}
  for(let file of files){const type=/\.(mp4|mov|avi|webm|mkv)$/i.test(file.name)?'video':'image';if(file.type.startsWith('image/')&&!/\.(png|jpe?g|webp)$/i.test(file.name)){const ext={'image/png':'png','image/jpeg':'jpg','image/webp':'webp'}[file.type];if(ext)file=new File([file],'剪贴板-'+Date.now()+'.'+ext,{type:file.type})}const error=validateSelectedMedia(file,{type});if(error){libraryNote(file.name+'：'+error);return}tempMedia.queue.push({file,type,resume})}
  if(tempMedia.busy)return;tempMedia.busy=true;renderMediaLibrary();
  try{while(tempMedia.queue.length){const item=tempMedia.queue.shift();try{await saveLibraryFile(item)}catch(e){libraryNote(item.file.name+' 保存未完成：'+e.message+'；可重选原文件续传')}}}
  finally{tempMedia.busy=false;await refreshMediaLibrary().catch(e=>libraryNote(e.message))}
}
async function saveLibraryFile({file,type,resume}){
  const code=tempMedia.code,row=resume||await libraryRequest('start',{filename:file.name,size:file.size,type},code);let offset=row.offset||0;
  const preview=libraryThumbnail(file,type);
  while(offset<file.size){const start=offset,chunk=file.slice(offset,offset+512*1024);let result;
    for(let attempt=0;attempt<3;attempt++){try{result=await api('/api/media-library/chunk?id='+row.id+'&offset='+start,{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Media-Library':code},body:chunk,signal:AbortSignal.timeout(150000)});break}catch(e){if(attempt===2||(e.status&&e.status<500&&e.status!==429))throw e;await new Promise(r=>setTimeout(r,800*(attempt+1)))}}
    offset=result.offset;libraryNote('保存 '+file.name+' · '+Math.floor(offset/file.size*100)+'%'+(tempMedia.queue.length?' · 还有 '+tempMedia.queue.length+' 个':''));
  }
  await libraryRequest('finish',{id:row.id,...await preview},code);await refreshMediaLibrary();libraryNote('✓ '+file.name+' 已保存，可重复选用');
}
function attachMediaLibraryButton(drop,key,mapping,workflow,state){
  const button=document.createElement('button');button.type='button';button.className='temp-media-pick';button.textContent='从素材库选择';button.onclick=e=>{e.stopPropagation();openMediaLibrary({drop,key,mapping,workflow,state})};drop.append(button);
}
function showLibrarySelection(drop,asset){
  drop.querySelector('.local-media-preview')?.remove();if(asset.libraryThumbnail){const img=document.createElement('img');img.className='local-media-preview';img.src='data:image/jpeg;base64,'+asset.libraryThumbnail;img.alt=asset.name;drop.append(img)}
}
async function chooseLibraryAsset(asset){
  const target=tempMedia.target;if(!target)return;const {drop,key,mapping,workflow,state}=target,code=tempMedia.code;
  document.getElementById('tempMediaLibrary').classList.remove('open');clearInterval(tempMedia.poll);
  const id=(state.uploadIds[key]||0)+1;state.uploadIds[key]=id;state.uploading[key]=true;delete state.tokens[key];delete state.names[key];revokeLocalMediaPreview(key,state);
  state.files[key]={name:asset.name,libraryThumbnail:asset.thumbnail,duration:asset.duration};showLibrarySelection(drop,state.files[key]);
  if(workflow.id==='h3_edit_n'&&key==='source_video'){
    const p=workflow.rh_params.duration,seconds=asset.duration,step=Number(p.step)||1;
    const value=seconds?Math.max(Number(p.min),Math.min(Number(p.max),Number(p.min)+Math.round((seconds-Number(p.min))/step)*step)):null;
    state.durationSelection={file:state.files[key],value,manual:false,note:seconds?'检测到 '+seconds.toFixed(2)+' 秒，已填入 '+value+' 秒；可手动修改':'未读取到时长，请手动填写（4–15 秒）'};
    if(cur===workflow){if(value!==null)document.getElementById('param_duration').value=value;document.getElementById('durationAutoNote').textContent=state.durationSelection.note}
  }
  const update=text=>{if(state.uploadIds[key]!==id)return;const current=currentMediaDrop(workflow.id,key,-1,drop);if(current)current.querySelector('.fn').textContent=text};
  update('素材已保存，正在交给 RunningHub…');
  try{for(let count=0;count<180;count++){
    const result=await libraryRequest('use',{id:asset.id,workflow:workflow.id,input_key:key,retry:count===0},code);if(state.uploadIds[key]!==id)return;
    if(result.status==='error')throw new Error(result.error);
    if(result.uploadToken){state.tokens[key]=result.uploadToken;state.names[key]=asset.name;update('✓ '+asset.name+' 已选用');currentMediaDrop(workflow.id,key,-1,drop)?.classList.add('has-file');return}
    await new Promise(r=>setTimeout(r,1500));
  }throw new Error('接收耗时较长，稍后从素材库重新选用即可，不用重新上传')}
  catch(e){update('✗ '+e.message)}finally{if(state.uploadIds[key]===id)delete state.uploading[key]}
}
const tempMediaOpen=document.createElement('button');tempMediaOpen.type='button';tempMediaOpen.className='temp-media-pick';tempMediaOpen.textContent='临时素材库';tempMediaOpen.onclick=()=>openMediaLibrary();document.querySelector('.pane-heading').append(tempMediaOpen);

const api=async(path,opt={})=>{const r=await fetch(path,opt);let d={};try{d=await r.json()}catch{}if(!r.ok){const error=new Error(d.error||('HTTP '+r.status));error.data=d;error.status=r.status;throw error}return d};
let WFS=[],cur=null,genRunning=false,renderVersion=0;const pendingVideoSubmitKey='jt-pending-video-submit',mediaStateByWorkflow=new Map(),MAX_VIDEO_UPLOAD_BYTES=60*1024*1024;
function ensureMediaState(workflowId){if(!mediaStateByWorkflow.has(workflowId))mediaStateByWorkflow.set(workflowId,{tokens:{},names:{},uploadIds:{},previewUrls:{},files:{},uploading:{}});return mediaStateByWorkflow.get(workflowId)}
function selectVideoWorkflow(workflow){if(cur&&cur.id!==workflow.id)revokeWorkflowMediaPreviews(cur.id);cur=workflow;renderVersion++;renderForm();renderSwitch()}
async function recoverTasks(){return refreshVideoQueue()}
async function init(){const box=document.getElementById('wfSwitch'),form=document.getElementById('wfForm'),btn=document.getElementById('genBtn');box.innerHTML='<div class="config-loading">正在加载视频工作流…</div>';form.innerHTML='<div class="config-loading">加载完成后可设置提示词和素材</div>';btn.disabled=true;try{const a=await api('/api/workflows');WFS=a.filter(w=>w.kind==='video');if(!WFS.length)throw new Error('没有可用的视频工作流');box.replaceChildren();const grouped={};WFS.forEach(w=>(grouped[w.section||'其他']??=[]).push(w));Object.entries(grouped).forEach(([section,items])=>{const group=document.createElement('div'),heading=document.createElement('div');group.className='workflow-section';heading.className='workflow-section-title';heading.textContent=section;group.appendChild(heading);items.forEach(w=>{const b=document.createElement('button'),name=document.createElement('b');b.type='button';b.dataset.wf=w.id;name.textContent=w.name;b.appendChild(name);b.onclick=()=>selectVideoWorkflow(w);group.appendChild(b)});box.appendChild(group)});selectVideoWorkflow(WFS[0]);btn.disabled=false}catch(e){cur=null;box.innerHTML='<div class="config-error"><b>视频配置加载失败</b><span></span><button type="button">重新加载</button></div>';box.querySelector('span').textContent=e.message;box.querySelector('button').onclick=retryWorkflows;form.innerHTML='<div class="config-error"><span>请确认服务连接后重试，现有任务和素材不会被提交。</span></div>'}}function retryWorkflows(){init()}
function renderSwitch(){document.querySelectorAll('#wfSwitch button').forEach(b=>b.classList.toggle('active',b.dataset.wf===cur.id))}
function isVideoType(t){return t==='video'}
const videoThumbnails=new WeakMap();let thumbnailChain=Promise.resolve();
function prepareVideoThumbnail(file){
  if(file?.libraryThumbnail)return Promise.resolve(file.libraryThumbnail);
  if(typeof File==='undefined'||!(file instanceof File))return Promise.resolve(null);
  if(videoThumbnails.has(file))return videoThumbnails.get(file);
  const pending=thumbnailChain.then(()=>new Promise(resolve=>{
    const video=document.createElement('video'),url=URL.createObjectURL(file);let finished=false;
    const finish=value=>{if(finished)return;finished=true;clearTimeout(timer);video.onloadeddata=null;video.onerror=null;video.removeAttribute('src');video.load();URL.revokeObjectURL(url);resolve(value)};
    const timer=setTimeout(()=>finish(null),6000);video.muted=true;video.playsInline=true;video.preload='auto';
    video.onerror=()=>finish(null);video.onloadeddata=()=>{try{if(!video.videoWidth||!video.videoHeight)return finish(null);const canvas=document.createElement('canvas'),scale=Math.min(160/video.videoWidth,90/video.videoHeight,1);canvas.width=Math.max(1,Math.round(video.videoWidth*scale));canvas.height=Math.max(1,Math.round(video.videoHeight*scale));canvas.getContext('2d').drawImage(video,0,0,canvas.width,canvas.height);canvas.toBlob(blob=>{if(!blob||blob.size>32768)return finish(null);const reader=new FileReader();reader.onload=()=>finish(String(reader.result).split(',')[1]);reader.onerror=()=>finish(null);reader.readAsDataURL(blob)},'image/jpeg',.6)}catch{finish(null)}};video.src=url;
  })).catch(()=>null);videoThumbnails.set(file,pending);thumbnailChain=pending.then(()=>{});return pending;
}
function persistTaskThumbnails(jobId,files,workflow){
  for(const [key,file] of Object.entries(files))if(isVideoType(workflow.rh_media?.[key]?.type))prepareVideoThumbnail(file).then(async data=>{if(!data)return;try{await api('/api/video-thumbnail',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:jobId,key,data})});refreshVideoQueue()}catch{/* Optional preview never blocks a paid task. */}});
}
function pasteReferenceImage(event){
  if(!cur||document.body.closest('.page-host')?.hidden||document.getElementById('queueEditor')||mediaLibraryIsOpen())return;
  const file=Array.from(event.clipboardData?.items||[]).find(item=>item.kind==='file'&&item.type.startsWith('image/'))?.getAsFile();if(!file)return;
  const drops=Array.from(document.querySelectorAll('.drop')).filter(drop=>!isVideoType(cur.rh_media?.[drop.dataset.mediaKey]?.type));
  const focused=document.activeElement?.closest?.('.drop');const target=drops.includes(focused)?focused:drops.length===1?drops[0]:null;
  if(!target){if(drops.length){event.preventDefault();document.getElementById('genStatus').textContent='有多个参考图位置，请先点击对应上传框的“粘贴到这里”再按 Ctrl＋V'}return}
  event.preventDefault();const key=target.dataset.mediaKey,m=cur.rh_media[key],ext={'image/png':'.png','image/jpeg':'.jpg','image/webp':'.webp'}[file.type];
  const named=ext&&!/\.(png|jpe?g|webp)$/i.test(file.name)?new File([file],'剪贴板-'+Date.now()+ext,{type:file.type}):file;
  uploadMedia(key,m,named,target,cur,renderVersion,ensureMediaState(cur.id));
}
function mediaAccept(type){return isVideoType(type)?'.mp4,.mov,.avi,.webm,.mkv,video/mp4,video/quicktime,video/x-msvideo,video/webm,video/x-matroska':'.png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp'}
function validateSelectedMedia(file,m){const suffix=(String(file?.name||'').match(/\.[^.]+$/)||[''])[0].toLowerCase(),allowed=isVideoType(m.type)?['.mp4','.mov','.avi','.webm','.mkv']:['.png','.jpg','.jpeg','.webp'];if(!allowed.includes(suffix))return isVideoType(m.type)?'请选择 MP4、MOV、WebM、AVI 或 MKV 视频':'请选择 JPG、PNG 或 WebP 图片；HEIC 请先导出为 JPG';if(!Number.isFinite(file.size)||file.size>MAX_VIDEO_UPLOAD_BYTES)return'文件超过60MB限制';if(file.size===0)return'文件为空，请重新选择';return''}
function revokeLocalMediaPreview(key,state){const value=state.previewUrls[key];if(value)URL.revokeObjectURL(value);delete state.previewUrls[key]}
function revokeWorkflowMediaPreviews(workflowId){const state=mediaStateByWorkflow.get(workflowId);if(!state)return;Object.keys(state.previewUrls).forEach(key=>revokeLocalMediaPreview(key,state))}
function replaceLocalMediaPreview(key,m,file,drop,state){revokeLocalMediaPreview(key,state);const existing=drop.querySelector('.local-media-preview');if(existing)drop.removeChild(existing);const media=document.createElement(isVideoType(m.type)?'video':'img');media.className='local-media-preview';media.src=URL.createObjectURL(file);state.previewUrls[key]=media.src;state.files[key]=file;if(isVideoType(m.type)){prepareVideoThumbnail(file);media.controls=true;media.playsInline=true;media.preload='metadata';detectSourceDuration(media,key,file,drop,state)}else media.alt='已选择的'+String(m.label||'图片');media.onerror=()=>{const note=drop.querySelector('.fn');if(note)note.textContent+=' · 当前浏览器无法预览此编码，可尝试 MP4/H.264 或 JPG'};drop.append(media)}
function detectSourceDuration(media,key,file,drop,state){
  if(cur?.id!=='h3_edit_n'||key!=='source_video')return;
  const workflow=cur,version=renderVersion,previous=state.durationSelection;
  if(previous?.file!==file)state.durationSelection={file,value:null,note:'正在读取视频时长…',manual:false};
  const selection=state.durationSelection;
  const active=()=>cur===workflow&&renderVersion===version&&state.files[key]===file&&state.durationSelection===selection;
  const show=()=>{if(!active())return;const input=document.getElementById('param_duration'),note=document.getElementById('durationAutoNote');if(input&&selection.value!==null)input.value=selection.value;if(note)note.textContent=selection.note};
  const failed=()=>{if(!active()||selection.manual)return;selection.note='无法读取视频时长，请手动填写（4–15 秒）';show()};
  const timer=setTimeout(failed,10000);
  media.addEventListener('loadedmetadata',()=>{clearTimeout(timer);if(!active()||selection.manual)return;const seconds=media.duration;if(!Number.isFinite(seconds)||seconds<=0){failed();return}const p=workflow.rh_params.duration,min=Number(p.min),max=Number(p.max),step=Number(p.step)||1;const rounded=min+Math.round((seconds-min)/step)*step;selection.value=Math.max(min,Math.min(max,rounded));selection.note='检测到 '+seconds.toFixed(2)+' 秒，已填入 '+selection.value+' 秒'+(seconds<min||seconds>max?'（工作流仅支持 '+min+'–'+max+' 秒）':'（按整秒取近似值）')+'；可手动修改';show()},{once:true});
  media.addEventListener('error',()=>{clearTimeout(timer);failed()},{once:true});
}
function paramDefault(key,p){const selected=cur?.id==='h3_edit_n'&&key==='duration'?ensureMediaState(cur.id).durationSelection:null;return selected?.value??(Object.prototype.hasOwnProperty.call(p,'default')?p.default:(cur.params_defaults||{})[key])}
function optionValue(option){return typeof option==='object'?String(option.value??option.name??''):String(option)}
function optionLabel(option){return typeof option==='object'?String(option.label??option.name??option.value??''):String(option)}
function renderForm(){const f=document.getElementById('wfForm'),workflow=cur,version=renderVersion,state=ensureMediaState(workflow.id);f.replaceChildren();const intro=document.createElement('div'),title=document.createElement('b'),desc=document.createElement('span');intro.className='note';title.textContent=workflow.name;desc.textContent=workflow.desc;intro.append(title,document.createElement('br'),desc);f.appendChild(intro);
  const media=Object.entries(workflow.rh_media||{});
  media.forEach(([key,m])=>{const lab=document.createElement('label');lab.textContent=m.label+(m.required?'（必传）':'（可选）');f.appendChild(lab);
    const drop=document.createElement('div'),copy=document.createElement('span'),fn=document.createElement('div'),inp=document.createElement('input');drop.className='drop';drop.tabIndex=0;drop.setAttribute('role','button');drop.setAttribute('aria-label','选择或拖入'+String(m.label||'素材'));drop.dataset.mediaKey=key;drop.dataset.mediaType=isVideoType(m.type)?'video':'image';copy.className='upload-heading';const icon=document.createElement('span'),formats=document.createElement('span');icon.className='upload-kind-icon';icon.setAttribute('aria-hidden','true');icon.textContent=isVideoType(m.type)?'▶':'▧';copy.textContent=isVideoType(m.type)?'上传'+String(m.label||'视频'):'上传'+String(m.label||'参考图');formats.className='upload-formats';formats.textContent=isVideoType(m.type)?'点击或拖入视频 · MP4 / MOV / WebM 等':'点击或拖入图片 · JPG / PNG / WebP';fn.className='fn';fn.setAttribute('aria-live','polite');inp.type='file';inp.hidden=true;inp.accept=mediaAccept(m.type);drop.append(icon,copy,formats,fn,inp);if(state.tokens[key]){drop.classList.add('has-file');fn.textContent='✓ '+state.names[key]+' 已上传'}const accept=file=>{if(!file)return;const error=validateSelectedMedia(file,m);if(error){fn.textContent='✗ '+error;return}uploadMedia(key,m,file,drop,workflow,version,state)};drop.onclick=event=>{if(event.target!==inp)inp.click()};drop.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();inp.click()}};drop.ondragover=event=>{event.preventDefault();drop.classList.add('is-dragging')};drop.ondragleave=()=>drop.classList.remove('is-dragging');drop.ondrop=event=>{event.preventDefault();drop.classList.remove('is-dragging');accept(event.dataTransfer?.files?.[0])};inp.onchange=()=>{accept(inp.files[0]);inp.value=''};
    if(state.files[key]){if(state.files[key] instanceof File)replaceLocalMediaPreview(key,m,state.files[key],drop,state);else showLibrarySelection(drop,state.files[key]);if(!state.tokens[key])fn.textContent=state.files[key].name+' · 尚未上传成功，请重新选择重试'}if(state.uploading[key])fn.textContent='上传中…';drop.onclick=event=>{if(event.target!==inp&&!event.target.closest('video'))inp.click()};drop.onkeydown=event=>{if(event.target===drop&&(event.key==='Enter'||event.key===' ')){event.preventDefault();inp.click()}};attachMediaLibraryButton(drop,key,m,workflow,state);f.appendChild(drop)});
  const params=Object.entries(cur.rh_params||{});
  f.querySelectorAll('.drop').forEach(drop=>{if(isVideoType(workflow.rh_media[drop.dataset.mediaKey].type))return;const hint=document.createElement('button');hint.type='button';hint.className='paste-target';hint.textContent='粘贴到这里（Ctrl＋V）';hint.onclick=event=>{event.stopPropagation();drop.focus()};drop.append(hint)});
  params.forEach(([key,p])=>{const lab=document.createElement('label');lab.textContent=p.label+(p.required?'（必填）':'');f.appendChild(lab);let inp;
    if(p.type==='text'||p.type==='textarea'||key==='prompt'||key==='negative'){inp=document.createElement('textarea');if(cur.prompt_placeholder&&key==='prompt')inp.placeholder=cur.prompt_placeholder;if(key==='prompt'&&cur.prompt_hint){const h=document.createElement('div');h.className='note';h.style.color='#c26a4a';h.textContent=cur.prompt_hint;f.appendChild(h)}}
    else if(p.type==='boolean'){inp=document.createElement('input');inp.type='checkbox'}
    else if(p.type==='select'){inp=document.createElement('select');(p.options||[]).forEach(option=>{const item=document.createElement('option');item.value=optionValue(option);item.textContent=optionLabel(option);inp.appendChild(item)})}
    else{inp=document.createElement('input');inp.type=(p.type==='number'||p.type==='int'||p.vtype==='int'||p.vtype==='float')?'number':'text';if(p.min!==undefined)inp.min=p.min;if(p.max!==undefined)inp.max=p.max;if(p.step!==undefined)inp.step=p.step;else if(p.type==='int'||p.vtype==='int')inp.step='1'}
    inp.id='param_'+key;inp.dataset.paramType=p.vtype||p.type||'text';const d=paramDefault(key,p);if(d!==undefined){if(inp.type==='checkbox')inp.checked=d===true;else inp.value=d}f.appendChild(inp);if(workflow.id==='h3_edit_n'&&key==='duration'){const note=document.createElement('div');note.id='durationAutoNote';note.className='note';note.setAttribute('aria-live','polite');note.textContent=state.durationSelection?.note||'选择视频后自动读取时长，可手动修改（4–15 秒）';f.appendChild(note);inp.addEventListener('input',()=>{if(state.durationSelection){state.durationSelection.manual=true;state.durationSelection.value=inp.value;state.durationSelection.note='已手动设置时长';note.textContent=state.durationSelection.note}})}});
  (cur.fixed_features||[]).forEach(text=>{const note=document.createElement('div');note.className='note unavailable';note.textContent=text;f.appendChild(note)})}
function sendMediaFile(url,file,onProgress){return new Promise((resolve,reject)=>{const request=new XMLHttpRequest();request.open('POST',url);request.timeout=600000;request.setRequestHeader('Content-Type','application/octet-stream');request.upload.onprogress=event=>{if(event.lengthComputable)onProgress(Math.round(event.loaded/event.total*100))};request.onload=()=>{let data={};try{data=JSON.parse(request.responseText)}catch{}if(request.status>=200&&request.status<300&&data.uploadToken)resolve(data);else reject(new Error(data.error||'上传服务返回错误（'+request.status+'）'))};request.onerror=()=>reject(new Error('网络连接中断，请重新选择文件重试'));request.ontimeout=()=>reject(new Error('上传超时，请检查网络或压缩文件后重试'));request.send(file)})}
async function uploadMedia(key,m,file,drop,workflow,version,state){const fnEl=drop.querySelector('.fn'),error=validateSelectedMedia(file,m);if(error){fnEl.textContent='✗ '+error;return}const uploadId=(state.uploadIds[key]||0)+1;state.uploadIds[key]=uploadId;state.uploading[key]=true;drop.querySelector('.upload-retry')?.remove();delete state.tokens[key];delete state.names[key];replaceLocalMediaPreview(key,m,file,drop,state);fnEl.textContent='上传中…';drop.classList.remove('has-file');try{const query=new URLSearchParams({workflow:workflow.id,input_key:key,filename:file.name});const r=await sendResumableMediaFile('/api/upload?'+query,file,percent=>{if(state.uploadIds[key]!==uploadId)return;const activeDrop=currentMediaDrop(workflow.id,key,version,drop);if(activeDrop)activeDrop.querySelector('.fn').textContent=percent<100?'上传中 '+percent+'%':'文件已传完，RunningHub 接收中…'});if(state.uploadIds[key]!==uploadId)return;state.tokens[key]=r.uploadToken;state.names[key]=file.name;const activeDrop=currentMediaDrop(workflow.id,key,version,drop);if(activeDrop){activeDrop.classList.add('has-file');activeDrop.querySelector('.fn').textContent='✓ '+file.name+' 已上传'}}catch(e){if(state.uploadIds[key]!==uploadId)return;delete state.tokens[key];delete state.names[key];const activeDrop=currentMediaDrop(workflow.id,key,version,drop);if(activeDrop){activeDrop.classList.remove('has-file');activeDrop.querySelector('.fn').textContent='✗ 上传暂未完成：'+e.message;const retry=document.createElement('button');retry.type='button';retry.className='upload-retry';retry.textContent='继续上传';retry.onclick=event=>{event.stopPropagation();uploadMedia(key,m,file,activeDrop,workflow,renderVersion,state)};activeDrop.append(retry)}}finally{if(state.uploadIds[key]===uploadId)delete state.uploading[key]}}
function currentMediaDrop(workflowId,key,version,original){if(cur?.id!==workflowId)return null;if(version===renderVersion&&original.isConnected)return original;return Array.from(document.querySelectorAll('.drop')).find(item=>item.dataset.mediaKey===key)||null}
const resumableFiles=new WeakMap();
async function sendResumableMediaFile(url,file,onProgress){
  let scopes=resumableFiles.get(file);if(!scopes){scopes=new Map();resumableFiles.set(file,scopes)}let row=scopes.get(url);
  const jsonPost=(path,body)=>api(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(150000)});
  const retry=async action=>{let last;for(let i=0;i<3;i++){try{return await action()}catch(e){last=e;if(e.status&&e.status<500&&![408,429].includes(e.status))throw e;if(i<2)await new Promise(r=>setTimeout(r,800*(i+1)))}}throw last};
  if(!row){const q=new URL(url,location.origin).searchParams;row={...(await jsonPost('/api/upload-start',{workflow:q.get('workflow'),input_key:q.get('input_key'),filename:file.name,size:file.size})),offset:0};scopes.set(url,row)}
  try{
    while(row.offset<file.size){const end=Math.min(row.offset+512*1024,file.size),offset=row.offset,chunk=file.slice(offset,end);const result=await retry(()=>api('/api/upload-chunk?id='+row.upload_id+'&offset='+offset,{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:chunk,signal:AbortSignal.timeout(150000)}));row.offset=result.offset;onProgress(Math.min(99,Math.floor(row.offset/file.size*100)))}
    onProgress(100);
    for(let n=0;n<100;n++){const result=await retry(()=>jsonPost('/api/upload-finish',{upload_id:row.upload_id}));if(result.uploadToken)return result;if(result.status==='error'){scopes.delete(url);throw new Error(result.error)}await new Promise(r=>setTimeout(r,1500))}
    throw new Error('云端仍在接收，请点击继续上传查询结果');
  }catch(e){if(e.status===404)scopes.delete(url);throw e}
}
function readParamValue(el){if(el.type==='checkbox')return el.checked;if(el.value==='')return'';if(el.dataset.paramType==='int')return Number.parseInt(el.value,10);if(el.dataset.paramType==='float'||el.dataset.paramType==='number')return Number(el.value);return el.value}
function collectParams(){const p={};Object.keys(cur.rh_params||{}).forEach(k=>{const el=document.getElementById('param_'+k);if(el){const value=readParamValue(el);if(value!=='')p[k]=value}});return p}
function safeMediaUrl(value){if(!value||!String(value).trim())return'';try{const u=new URL(String(value),location.origin);return ['http:','https:'].includes(u.protocol)&&!u.username&&!u.password?u.href:''}catch{return''}}
function hasRealSeed(j){const value=j?.params?.seed??j?.seed;return typeof value==='number'&&Number.isFinite(value)}
function seedSegment(j){const value=j?.params?.seed??j?.seed;return hasRealSeed(j)?('种子：'+value+' · '):''}
function resultMediaKind(im,url){const type=String(im.file_type||im.fileType||im.outputType||im.output_type||im.type||'').trim().toLowerCase().split(';')[0].replace(/^\./,''),path=new URL(url||location.origin).pathname;if(type==='application/zip'||type==='zip'||/\.zip$/i.test(path))return'file';if(type.startsWith('video/')||['video','mp4','mov','webm','avi','mkv'].includes(type)||/\.(mp4|mov|webm|avi|mkv)$/i.test(path))return'video';if(type.startsWith('image/')||['image','png','jpg','jpeg','webp','gif','avif'].includes(type)||/\.(png|jpe?g|webp|gif|avif)$/i.test(path))return'image';return'file'}
const galleryItems=[];let galleryIndex=-1;
function registerGalleryJob(j,select=true){let added=false;(j.images||[]).forEach((im,i)=>{const key=j.id+':'+i;if(!galleryItems.some(x=>x.key===key)){galleryItems.push({key,j,im,i});added=true}});if(select){const index=galleryItems.findIndex(x=>x.j.id===j.id);if(index>=0)galleryIndex=index}else if(galleryIndex<0&&galleryItems.length)galleryIndex=0;if(galleryIndex>=0&&(select||added))renderMediaGallery()}
function selectGalleryItem(index){if(!galleryItems.length)return;galleryIndex=(index+galleryItems.length)%galleryItems.length;renderMediaGallery()}
// Keep the source thumbnail stable; a newly decoded result frame may be black.
function resultThumbnail(item){const url=safeMediaUrl(item.im.url);return resultMediaKind(item.im,url)==='image'?(safeMediaUrl(item.im.preview_url)||url):''}
function renderGalleryThumbs(){const thumbs=document.getElementById('galleryThumbs');thumbs.replaceChildren();galleryItems.forEach((entry,index)=>{const b=document.createElement('button'),src=resultThumbnail(entry)||tasks.get(entry.j.id)?.sourceThumbnail;b.className='gallery-thumb'+(index===galleryIndex?' active':'');b.type='button';b.onclick=()=>selectGalleryItem(index);if(src){const img=document.createElement('img');img.src=src;img.loading='lazy';img.decoding='async';img.alt=resultThumbnail(entry)?'生成结果':'原视频参考缩略图';b.append(img)}else{const span=document.createElement('span');span.textContent=resultMediaKind(entry.im,safeMediaUrl(entry.im.url))==='video'?'▶':'▧';b.append(span)}b.title=entry.j.wf_name||entry.j.workflow||'生成结果';b.setAttribute('aria-label','查看结果 '+(index+1));b.setAttribute('aria-pressed',String(index===galleryIndex));thumbs.append(b)});for(const id of ['galleryPrev','galleryNext'])document.getElementById(id).disabled=galleryItems.length<2}
function renderMediaGallery(){
  const main=document.getElementById('galleryMain');if(!main||galleryIndex<0)return;const item=galleryItems[galleryIndex];
  // Polling only appends thumbnails; keep the selected player and its playback position.
  if(main.dataset.key!==item.key){main.dataset.key=item.key;main.replaceChildren();const url=safeMediaUrl(item.im.url),kind=resultMediaKind(item.im,url),note=document.createElement('div');note.className='gallery-meta';note.textContent=seedSegment(item.j)+String(item.im.stage_label||item.im.file||'结果');main.append(note);
    if(kind==='file'){const file=document.createElement('div');file.className='file-result';file.textContent='结果文件已生成，可直接下载';main.append(file)}else{const media=document.createElement(kind==='video'?'video':'img');if(kind==='video'){media.controls=true;media.playsInline=true;media.preload='metadata';}else media.alt='生成结果';media.src=kind==='video'?url:(safeMediaUrl(item.im.preview_url)||url);main.append(media)}
    const actions=document.createElement('div'),download=document.createElement('a'),favorite=document.createElement('button');actions.className='gallery-actions';download.className='dl';download.href=url;download.target='_blank';download.rel='noopener noreferrer';download.textContent='⬇ 下载原文件';favorite.className='dl';favorite.textContent='♥ 收藏';favorite.disabled=kind==='file';favorite.onclick=async()=>{favorite.disabled=true;try{await api('/api/favorites',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:item.j.id,image_index:item.i})});favorite.textContent='✓ 已收藏'}catch(e){favorite.disabled=false;favorite.textContent='收藏失败：'+e.message}};actions.append(favorite,download);main.append(actions);
  }renderGalleryThumbs();document.getElementById('mediaGallery').hidden=false;document.getElementById('videoEmpty').classList.add('hidden');
}
function addResult(j){registerGalleryJob(j)}
const tasks=new Map(); // job_id -> {card, timeEl, metaEl, spinEl, timer, startTs, wfName}
function closeTaskDetails(){document.querySelectorAll('.task-details:popover-open').forEach(el=>el.hidePopover())}
window.addEventListener('resize',closeTaskDetails);
document.querySelector('.preview-stage').addEventListener('scroll',closeTaskDetails,{passive:true});
function fmtTime(s){s=Math.floor(s);const m=String(Math.floor(s/60)).padStart(2,'0'),ss=String(s%60).padStart(2,'0');return m+':'+ss}
function refreshTaskCount(){const n=tasks.size;document.getElementById('taskCount').textContent=n+' 个任务（最多2个并发）'}
function taskStatusText(j){const s=j.provider_status||j.status;if(j.status==='done')return '✓ 完成';if(j.status==='error')return '✗ 失败';if(s==='SUBMITTING')return '排队中…';if(s==='RUNNING')return '生成中…';return s||'处理中…'}
function videoCoinText(j){if(j.rh_coins!==null&&j.rh_coins!==undefined&&j.rh_coins!=='')return'RH币：'+String(j.rh_coins);return(j.status==='done'||j.status==='error')?'RH币：未返回':'RH币：统计中'}
function taskStatusClass(j){if(j.status==='done')return 'done';if(j.status==='error')return 'err';return ''}
function addTaskCard(jobId,wfName){
  if(tasks.has(jobId))return tasks.get(jobId);const card=document.createElement('div'),tile=document.createElement('button'),thumb=document.createElement('span'),badge=document.createElement('span'),info=document.createElement('div'),name=document.createElement('div'),meta=document.createElement('div'),time=document.createElement('div'),view=document.createElement('button'),files=document.createElement('div'),actions=document.createElement('div');card.className='task-card';card.dataset.jobId=jobId;tile.className='task-tile';tile.type='button';tile.setAttribute('aria-label',wfName+' · 任务详情');thumb.className='task-picture';badge.className='task-badge';info.className='task-details';info.setAttribute('popover','auto');name.className='task-name';name.textContent=wfName;meta.className='task-meta';files.className='queue-files';actions.className='queue-actions';time.className='task-time';view.className='task-view';view.type='button';view.textContent='播放结果';view.hidden=true;info.append(name,files,meta,time,actions,view);tile.append(thumb,badge);card.append(tile,info);document.getElementById('taskList').append(card);const t={card,tile,thumb,badge,info,timeEl:time,metaEl:meta,viewEl:view,filesEl:files,actionsEl:actions,wfName};tasks.set(jobId,t);
  let closeTimer;const show=()=>{clearTimeout(closeTimer);if(!info.matches(':popover-open'))info.showPopover();const rect=tile.getBoundingClientRect();info.style.left=Math.max(8,Math.min(rect.left,window.innerWidth-info.offsetWidth-8))+'px';const below=window.innerHeight-rect.bottom-14,above=rect.top-14,useBelow=below>=Math.min(info.scrollHeight+32,420)||below>=above;info.style.maxHeight=Math.max(80,useBelow?below:above)+'px';info.style.top=(useBelow?rect.bottom+6:Math.max(8,rect.top-info.offsetHeight-6))+'px'},hide=()=>{closeTimer=setTimeout(()=>{if(!info.matches(':hover')&&!info.contains(document.activeElement))info.hidePopover()},180)};tile.onpointerenter=e=>{if(e.pointerType!=='touch')show()};tile.onpointerleave=hide;tile.onfocus=show;tile.onclick=()=>{show();if(t.job?.status==='done')view.click()};info.onpointerenter=()=>clearTimeout(closeTimer);info.onpointerleave=hide;info.onfocusout=hide;
  for(const [action,label] of [['top','置顶插队'],['up','上移'],['down','下移'],['edit','编辑参数'],['cancel','取消排队']]){const b=document.createElement('button');b.type='button';b.textContent=label;b.dataset.action=action;b.onclick=()=>{info.hidePopover();return action==='edit'?openQueueEditor(t.job):queueAction(t.job,action)};actions.append(b)}return t;
}
function updateTaskThumbnail(t){const entry=galleryItems.find(x=>x.j.id===t.job?.id),result=entry&&resultThumbnail(entry),src=result||t.sourceThumbnail||'',signature=src+'|'+t.job?.status;if(t.thumbSignature===signature)return;t.thumbSignature=signature;t.thumb.replaceChildren();if(src){const img=document.createElement('img');img.src=src;img.loading='lazy';img.decoding='async';img.alt=result?'生成结果缩略图':'原视频首帧';img.onerror=()=>img.remove();t.thumb.append(img);if(!result){const hint=document.createElement('small');hint.textContent='原视频';t.thumb.append(hint)}}else t.thumb.textContent=t.job?.status==='done'?'▶':'▧'}
const resultLoads=new Map();let resultLoadChain=Promise.resolve();
function loadCompletedTask(j){if(resultLoads.has(j.id))return resultLoads.get(j.id);const pending=resultLoadChain.then(async()=>{const full=await api('/api/job/'+encodeURIComponent(j.id),{signal:AbortSignal.timeout(20000)});if(!(full.images||[]).length)throw new Error('结果同步中');registerGalleryJob(full,false);const t=tasks.get(j.id);if(t)updateTaskThumbnail(t);return full}).catch(e=>{resultLoads.delete(j.id);const t=tasks.get(j.id);if(t)t.metaEl.textContent+=' · 结果同步中，将自动重试';return null});resultLoads.set(j.id,pending);resultLoadChain=pending.then(()=>{});return pending}
function groupTaskCards(rows){const list=document.getElementById('taskList');for(const [key,title,statuses] of [['active','进行中',['queued','running','recovering']],['done','已完成',['done']],['other','未完成 · 失败 / 已取消',['error','cancelled']]]){let group=list.querySelector('[data-group="'+key+'"]');if(!group){group=document.createElement('section');group.dataset.group=key;group.className='task-group';const titleEl=document.createElement('h3'),grid=document.createElement('div');grid.className='task-grid';group.append(titleEl,grid);list.append(group)}const items=rows.filter(j=>key==='other'?!['queued','running','recovering','done'].includes(j.status):statuses.includes(j.status));group.hidden=!items.length;group.firstChild.textContent=title+' · '+items.length;const grid=group.lastChild;items.forEach((j,index)=>{const card=tasks.get(j.id).card;if(grid.children[index]!==card)grid.insertBefore(card,grid.children[index]||null)})}if(rows.length)document.getElementById('videoEmpty').classList.add('hidden')}
function removeTaskCard(jobId){const t=tasks.get(jobId);if(!t)return;if(t.timer)clearInterval(t.timer);t.card.remove();tasks.delete(jobId);refreshTaskCount()}
function renderTaskResult(j){registerGalleryJob(j)}
async function pollTask(jobId){return refreshVideoQueue()}
let queueTimer=null,queueFetching=false,queueRefreshAgain=false;
async function refreshVideoQueue(){
  clearTimeout(queueTimer);if(queueFetching){queueRefreshAgain=true;return}queueFetching=true;
  try{const state=await api('/api/video-queue'),rows=state.jobs||[],ids=new Set(rows.map(j=>j.id)),list=document.getElementById('taskList');
    for(const id of tasks.keys())if(!ids.has(id))removeTaskCard(id);
    rows.forEach((j,index)=>{const t=addTaskCard(j.id,j.wf_name||'视频任务');t.job=j;
      const mediaSignature=JSON.stringify([j.media,j.thumbnails]);if(t.mediaSignature!==mediaSignature){t.mediaSignature=mediaSignature;t.sourceThumbnail=Object.values(j.thumbnails||{}).find(src=>typeof src==='string'&&src.startsWith('/api/video-thumbnail/'));t.filesEl.replaceChildren();for(const [key,name] of Object.entries(j.media||{})){const item=document.createElement('div'),w=WFS.find(w=>w.id===j.workflow);item.className='queue-media';item.textContent=(w?.rh_media?.[key]?.label||'素材')+'：'+name;t.filesEl.append(item)}if(!Object.keys(j.media||{}).length)t.filesEl.textContent='无需上传素材'}
      t.metaEl.textContent=j.queue_hold?'提交结果待核对，保留并发名额以防重复计费':j.status==='queued'?'等待第 '+j.position+' 位 · 尚未提交上游':j.status==='cancelled'?'已取消排队 · 未提交上游':j.status==='error'?(j.provider_status==='QUEUE_EXPIRED'?'素材已过期，请重新上传':j.error||'任务失败'):taskStatusText(j)+' · '+videoCoinText(j);
      t.card.dataset.status=j.status;t.badge.textContent=j.queue_hold?'待核对':j.status==='queued'?'排队 · 第 '+j.position+' 位':j.status==='done'?'✓ 已完成':j.status==='cancelled'?'已取消':j.status==='error'?'✕ 失败':'◉ 生成中';t.tile.setAttribute('aria-label',t.wfName+' · '+t.badge.textContent+' · 任务详情');t.timeEl.textContent=j.elapsed?'用时 '+fmtTime(j.elapsed):'';t.actionsEl.hidden=!j.editable;t.viewEl.hidden=j.status!=='done';updateTaskThumbnail(t);
      t.actionsEl.querySelectorAll('button').forEach(b=>b.disabled=t.busy||(['top','up'].includes(b.dataset.action)&&j.position===1)||(b.dataset.action==='down'&&j.position===state.waiting));
      t.viewEl.onclick=async()=>{t.viewEl.disabled=true;try{const full=await loadCompletedTask(j);if(full){renderTaskResult(full);t.info.hidePopover();document.getElementById('mediaGallery').scrollIntoView({block:'nearest'})}}finally{t.viewEl.disabled=false}};
      if(j.status==='done')loadCompletedTask(j);
    });groupTaskCards(rows);document.getElementById('taskCount').textContent='执行 '+state.running+'/'+state.limit+' · 等待 '+state.waiting+'（最多2个并发）'+(state.draining?' · 维护中，暂缓启动':'');
  }catch(e){document.getElementById('taskCount').textContent='队列连接中断，自动重试：'+e.message}
  finally{queueFetching=false;queueTimer=setTimeout(refreshVideoQueue,queueRefreshAgain?0:document.hidden?15000:4000);queueRefreshAgain=false}
}
async function queueAction(job,action,extra={}){
  if(!job)return;const t=tasks.get(job.id);if(t?.busy)return;t.busy=true;t.actionsEl.querySelectorAll('button').forEach(b=>b.disabled=true);
  try{await api('/api/video-queue',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:job.id,revision:job.queue_revision,action,...extra})});return true}
  catch(e){document.getElementById('genStatus').textContent='队列操作失败：'+e.message;return false}
  finally{t.busy=false;await refreshVideoQueue()}
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
  form.onsubmit=async e=>{e.preventDefault();save.disabled=true;const params={};for(const [key,input] of fields){if(input.type==='checkbox')params[key]=input.checked;else if(input.value!=='')params[key]=input.value}if(await queueAction(job,'edit',{params}))dialog.close();else{save.disabled=false;note.textContent='保存失败，原任务未被此操作修改。请关闭编辑窗，核对最新队列状态后重试。'}};dialog.showModal();
}
async function generate(){if(genRunning)return;if(!cur)return;const workflow=cur,state=ensureMediaState(workflow.id);if(Object.values(state.uploading).some(Boolean)){document.getElementById('genStatus').textContent='素材仍在上传，请完成后再生成';return}genRunning=true;const btn=document.getElementById('genBtn');btn.disabled=true;btn.classList.add('is-loading');const st=document.getElementById('genStatus');st.textContent='正在提交…';document.getElementById('genResult').innerHTML='';let pending={};try{pending=JSON.parse(localStorage.getItem(pendingVideoSubmitKey)||'{}')}catch{}const client_request_id=pending.workflow===workflow.id&&pending.id?pending.id:'video-'+Date.now()+'-'+Math.random().toString(36).slice(2);localStorage.setItem(pendingVideoSubmitKey,JSON.stringify({workflow:workflow.id,id:client_request_id}));try{const prompt=(document.getElementById('param_prompt')?.value||'').trim();if(!prompt)throw new Error('提示词不能为空');const required=Object.entries(workflow.rh_media||{}).filter(([,m])=>m.required).map(([k])=>k);const missing=required.filter(k=>!state.tokens[k]);if(missing.length)throw new Error('缺少必传素材：'+missing.join(', '));const submittedFiles={...state.files};const body={workflow:workflow.id,prompt:prompt,negative_prompt:(document.getElementById('param_negative')?.value||'').trim(),media:{...state.tokens},params:collectParams(),client_request_id};const r=await api('/api/video-generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});localStorage.removeItem(pendingVideoSubmitKey);if(!r.job_id)throw new Error(r.error||'提交失败');addTaskCard(r.job_id,workflow.name);persistTaskThumbnails(r.job_id,submittedFiles,workflow);st.textContent='✓ 已提交，任务 '+r.job_id+' 在下方队列中';pollTask(r.job_id)}catch(e){const definitiveRejection=e.status>=400&&e.status<500;if(definitiveRejection)localStorage.removeItem(pendingVideoSubmitKey);st.textContent='✗ '+e.message+(definitiveRejection?'':'；网络不明时再次点击会复用请求号')}finally{genRunning=false;btn.classList.remove('is-loading');btn.disabled=false}}
async function history(){const l=document.getElementById('histList');l.textContent='加载中…';const a=await api('/api/jobs?scope=video');l.replaceChildren();a.filter(j=>j.workflow&&WFS.find(w=>w.id===j.workflow)).slice(0,10).forEach(j=>{const w=WFS.find(x=>x.id===j.workflow),d=document.createElement('div'),title=document.createElement('b'),note=document.createElement('div'),button=document.createElement('button');d.className='job';title.textContent=w?w.name:'视频';note.className='note';note.textContent=j.status+' · '+videoCoinText(j)+' · '+(j.elapsed||'')+'秒';button.className='dl';button.textContent='查看结果';button.onclick=()=>{addResult(j);histOverlay.classList.remove('open')};d.append(title,note,button);l.appendChild(d)})}
async function favorites(){const l=document.getElementById('favList');l.textContent='加载中…';const a=await api('/api/favorites');l.replaceChildren();a.filter(f=>f.style_id==='video').forEach(f=>{const d=document.createElement('div');d.className='job';const promptNode=document.createElement('div');promptNode.className='note';promptNode.textContent=(f.prompt||'').slice(0,120);const isVideo=String(f.favorite_media_type||'').startsWith('video/'),media=document.createElement(isVideo?'video':'img');media.src=f.image_url;if(isVideo)media.controls=true;const link=document.createElement('a');link.className='dl';link.href=f.image_url;link.target='_blank';link.rel='noopener noreferrer';link.textContent='⬇ 下载';d.append(promptNode,media,link);l.appendChild(d)})}
window.addEventListener('pagehide',()=>mediaStateByWorkflow.forEach((_,workflowId)=>revokeWorkflowMediaPreviews(workflowId)));window.addEventListener('paste',pasteReferenceImage);document.getElementById('genBtn').onclick=generate;document.getElementById('galleryPrev').onclick=()=>selectGalleryItem(galleryIndex-1);document.getElementById('galleryNext').onclick=()=>selectGalleryItem(galleryIndex+1);document.getElementById('histOpen').onclick=()=>{histOverlay.querySelector('.library-scroll').scrollTop=0;histOverlay.classList.add('open');history()};document.getElementById('favOpen').onclick=()=>{favOverlay.querySelector('.library-scroll').scrollTop=0;favOverlay.classList.add('open');favorites()};document.querySelectorAll('.library-overlay .close').forEach(b=>b.onclick=()=>b.closest('.library-overlay').classList.remove('open'));init().then(()=>recoverTasks());
const CREATOR_ROUTES=['/','/realism','/video'];function scheduleRoutePrefetch(){}scheduleRoutePrefetch();
return {styleBoot:null};
}