const personalRhStorage='jt-personal-rh-key';
let personalRhKey=sessionStorage.getItem(personalRhStorage)||localStorage.getItem(personalRhStorage)||'';
const directMediaCache=new WeakMap();
let directTransfers=0;const directWaiters=[];
function initPersonalUpload(){
  // Retired library identifiers are no longer used by this page.
  localStorage.removeItem('jt-media-library');
  const settings=document.createElement('details');settings.className='personal-upload';settings.id='personalUpload';
  settings.innerHTML='<summary>RunningHub 个人直传 <span></span></summary><p>图片和视频直接上传 RunningHub。填写与工作台生成账户相同的 API Key。</p><form><input type="password" aria-label="个人 RunningHub API Key" placeholder="填写个人 RunningHub API Key" autocomplete="off" spellcheck="false"><label><input type="checkbox">记住此浏览器（仅在自己的电脑勾选）</label><div><button type="submit">保存</button><button type="button" data-clear>清除</button></div><p class="personal-upload-note" role="status"></p></form>';
  document.querySelector('.pane-heading').after(settings);
  const input=settings.querySelector('input[type=password]'),remember=settings.querySelector('input[type=checkbox]'),note=settings.querySelector('.personal-upload-note');
  remember.checked=!!localStorage.getItem(personalRhStorage);
  const update=()=>{settings.querySelector('summary span').textContent=personalRhKey?'已设置':'未设置';input.value='';input.placeholder=personalRhKey?'已设置，填写可更换 Key':'填写个人 RunningHub API Key'};
  settings.querySelector('form').onsubmit=e=>{e.preventDefault();const value=input.value.trim()||personalRhKey;if(!/^[A-Za-z0-9_-]{16,128}$/.test(value)){note.textContent='请填写有效的 RunningHub API Key';return}personalRhKey=value;localStorage.removeItem(personalRhStorage);sessionStorage.removeItem(personalRhStorage);(remember.checked?localStorage:sessionStorage).setItem(personalRhStorage,value);note.textContent=remember.checked?'已保存到此浏览器，上传时自动校验账户':'已保存到当前标签页，关闭标签页后清除';update()};
  settings.querySelector('[data-clear]').onclick=()=>{personalRhKey='';localStorage.removeItem(personalRhStorage);sessionStorage.removeItem(personalRhStorage);note.textContent='个人 Key 已清除';update()};update();
}
function personalKeyRequired(){
  if(personalRhKey)return personalRhKey;
  const settings=document.getElementById('personalUpload');settings.open=true;settings.querySelector('input[type=password]').focus();
  throw new Error('请先在“RunningHub 个人直传”中填写并保存 Key，再点击继续上传');
}
function directUploadBinary(file,key,onProgress){return new Promise((resolve,reject)=>{
  const xhr=new XMLHttpRequest();xhr.open('POST','https://www.runninghub.ai/openapi/v2/media/upload/binary');xhr.timeout=180000;xhr.setRequestHeader('Authorization','Bearer '+key);
  xhr.upload.onprogress=e=>{if(e.lengthComputable)onProgress(Math.min(99,Math.floor(e.loaded/e.total*100)))};
  xhr.onerror=()=>reject(new Error('直连 RunningHub 网络中断，请点击继续上传重试'));
  xhr.ontimeout=()=>reject(new Error('RunningHub 接收超时，请点击继续上传重试'));
  xhr.onload=()=>{let result={};try{result=JSON.parse(xhr.responseText)}catch{}
    if(xhr.status<200||xhr.status>=300||![0,200].includes(result.code)){const error=new Error([401,403].includes(xhr.status)?'RunningHub 拒绝此 Key，请检查账户或更换 Key':'RunningHub 暂未接收成功（'+String(result.code??xhr.status)+'），请重试');error.status=xhr.status;reject(error);return}
    const name=result.data?.filename||result.data?.fileName;if(typeof name!=='string'||!/^(api|openapi)\/[A-Za-z0-9._/-]+$/.test(name)||name.split('/').some(part=>!part||part==='.'||part==='..')){reject(new Error('RunningHub 未返回有效的文件标识'));return}onProgress(100);resolve(name)
  };
  const form=new FormData();form.append('file',file,file.name);xhr.send(form);
})}
async function sendDirectMediaFile(url,file,onProgress){
  const key=personalKeyRequired(),q=new URL(url,location.origin).searchParams;
  const post=(action,body)=>api('/api/upload-direct-'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(20000)});
  const {challenge}=await post('start',{workflow:q.get('workflow'),input_key:q.get('input_key'),filename:file.name,size:file.size});
  const proof=name=>globalThis.sha256.hmac(key,challenge+'\n'+name);
  await post('verify',{challenge,proof:proof('')});
  const fingerprint=globalThis.sha256(key);let cached=directMediaCache.get(file);
  if(!cached||cached.fingerprint!==fingerprint){
    const pending=(async()=>{
      if(directTransfers>=2)await new Promise(resolve=>directWaiters.push(resolve));else directTransfers++;
      try{return await directUploadBinary(file,key,onProgress)}finally{const next=directWaiters.shift();if(next)next();else directTransfers--}
    })();
    cached={fingerprint,pending};directMediaCache.set(file,cached);
    pending.catch(()=>{if(directMediaCache.get(file)===cached)directMediaCache.delete(file)});
  }
  const provider_name=await cached.pending;onProgress(100);
  // On a registration failure the provider result stays cached; retry never
  // uploads the same File again. Only this small signed receipt hits our server.
  return post('register',{challenge,proof:proof(provider_name),provider_name});
}
initPersonalUpload();
