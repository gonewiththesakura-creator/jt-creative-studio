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
