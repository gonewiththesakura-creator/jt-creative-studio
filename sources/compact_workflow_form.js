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
      const button=slotButtons.get(item.key),available=rows.includes(item),filled=!!item.filled(),show=available&&(filled||item.hasFile?.()||item===next);
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
