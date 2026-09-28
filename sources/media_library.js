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
