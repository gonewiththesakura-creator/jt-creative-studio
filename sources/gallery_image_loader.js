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
