const KEY = 'jt-singularity-appearance-v1';
// All persisted values are finite, bounded numbers; unknown properties are ignored.
const fields = [
 ['构图','offsetX','水平位置',-.8,.8,.01,.19],['构图','offsetY','垂直位置',-.5,.5,.01,.015],
 ['构图','mobileX','手机水平位置',-.5,.5,.01,0],['构图','mobileY','手机垂直位置',-.5,.5,.01,.015],
 ['构图','radius','观察距离',13,40,.1,20],['构图','azimuth','环绕角度',-180,180,1,0],
 ['构图','elevation','俯仰角度',4,65,1,12],['构图','tilt','画面倾斜角度（°）',-180,180,1,0],['构图','zoom','画面缩放',.5,1.8,.01,1],
 ['光场','mass','黑洞质量',.7,1.35,.01,1],['光场','lensing','引力弯曲',.5,1.5,.01,1],
 ['光场','temperature','吸积盘色温',.3,1.6,.01,.95],['光场','exposure','曝光亮度',.2,1.8,.01,.95],
 ['光场','bloom','光晕强度',0,.5,.005,.075],['光场','opacity','背景不透明度',0,1,.01,.9],
 ['动态','speed','时间速度',0,2,.05,1],['动态','flow','盘面流速',0,2,.05,1],
 ['动态','starMotion','星点漂移与闪烁',0,3,.1,1],
 ['动态','quality','渲染精度',.5,1.5,.1,1],
 ['玻璃','glassOpacity','面板不透明度',.05,1,.01,.78],['玻璃','glassBlur','毛玻璃模糊',0,40,1,20],
 ['玻璃','fieldOpacity','输入区域不透明度',.05,1,.01,.85],['玻璃','chromeOpacity','顶栏不透明度',.05,1,.01,.68],
 ['玻璃','edge','玻璃边缘亮度',0,.6,.01,.16]
];
const defaults = Object.fromEntries(fields.map(([,key,,,,,value])=>[key,value]));
function normalize(data) {
 const result={...defaults};
 for(const [,key,,min,max,step] of fields){
  const value=data?.[key];
  if(typeof value==='number' && Number.isFinite(value)) result[key]=Math.min(max,Math.max(min,Math.round(value/step)*step));
 }
 return result;
}

export function installAppearance(controls, onChange) {
 let settings={...defaults};
 try {settings=normalize(JSON.parse(localStorage.getItem(KEY)||'null'));} catch {}
 const button=document.createElement('button');button.type='button';button.className='topbar-action';button.id='appearanceOpen';button.textContent='外观';button.setAttribute('aria-expanded','false');button.setAttribute('aria-controls','appearancePanel');controls.append(button);
 const panel=document.createElement('section');panel.id='appearancePanel';panel.className='appearance-panel';panel.hidden=true;panel.setAttribute('aria-label','黑洞与玻璃外观控制台');
 panel.innerHTML='<header><div><small>APPEARANCE</small><h2>黑洞与玻璃</h2></div><button type="button" aria-label="关闭外观控制台">×</button></header><p class="appearance-note">拖动或输入数值即时预览。保存后，当前浏览器的三个工作台页面共用这组设置。</p><div class="appearance-fields"></div><footer><button type="button" data-setting-action="save">保存设置</button><button type="button" data-setting-action="reset">恢复默认</button><button type="button" data-setting-action="export">导出配置</button><button type="button" data-setting-action="import">导入配置</button><input type="file" accept="application/json,.json" hidden><p role="status" aria-live="polite"></p></footer>';
 document.body.append(panel);
 const inputs=new Map(),status=panel.querySelector('[role=status]'),container=panel.querySelector('.appearance-fields');
 let currentGroup,group;
 for(const [section,key,label,min,max,step] of fields){
  if(section!==currentGroup){currentGroup=section;group=document.createElement('fieldset');const title=document.createElement('legend');title.textContent=section;group.append(title);container.append(group);}
  const row=document.createElement('label');row.className='appearance-field';row.innerHTML='<span></span><input type="number"><input type="range">';row.querySelector('span').textContent=label;
  const list=[...row.querySelectorAll('input')];
  for(const input of list){input.min=min;input.max=max;input.step=step;input.value=settings[key];input.dataset.appearance=key;input.setAttribute('aria-label',label+(input.type==='range'?'滑块':'数值'));input.addEventListener('input',()=>{if(input.value===''||!Number.isFinite(input.valueAsNumber))return;settings=normalize({...settings,[key]:input.valueAsNumber});list.filter(other=>other!==input).forEach(other=>other.value=settings[key]);status.textContent='尚未保存';apply();});input.addEventListener('change',()=>input.value=settings[key]);}
  inputs.set(key,list);group.append(row);
 }
 function apply(){
  const style=document.body.style;
  style.setProperty('--appearance-glass',`rgba(15,16,20,${settings.glassOpacity})`);
  style.setProperty('--appearance-field',`rgba(17,18,22,${settings.fieldOpacity})`);
  style.setProperty('--appearance-chrome',`rgba(6,7,10,${settings.chromeOpacity})`);
  style.setProperty('--appearance-blur',settings.glassBlur+'px');
  style.setProperty('--appearance-edge',`rgba(255,230,200,${settings.edge})`);
  style.setProperty('--appearance-opacity',settings.opacity);
  onChange({...settings});
 }
 function sync(){for(const [key,list] of inputs)for(const input of list)input.value=settings[key];apply();}
 function close(){panel.hidden=true;button.setAttribute('aria-expanded','false');button.focus();}
 button.onclick=()=>{panel.hidden=!panel.hidden;button.setAttribute('aria-expanded',String(!panel.hidden));if(!panel.hidden){panel.scrollTop=0;panel.querySelector('header button').focus();}};
 panel.querySelector('header button').onclick=close;
 document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!panel.hidden){e.stopImmediatePropagation();close();}},true);
 panel.querySelector('[data-setting-action=save]').onclick=()=>{try{localStorage.setItem(KEY,JSON.stringify(settings));status.textContent='已保存，刷新或下次打开仍使用这些数值。';}catch{status.textContent='浏览器不允许保存，请导出配置备份。';}};
 panel.querySelector('[data-setting-action=reset]').onclick=()=>{settings={...defaults};sync();status.textContent='已恢复默认，点击保存后固定。';};
 panel.querySelector('[data-setting-action=export]').onclick=()=>{const blob=new Blob([JSON.stringify({version:1,settings},null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='jt-singularity-appearance.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);status.textContent='已导出，可在其他设备导入；也可用来设置网站统一默认值。';};
 const file=panel.querySelector('input[type=file]');panel.querySelector('[data-setting-action=import]').onclick=()=>file.click();
 file.onchange=async()=>{const selected=file.files[0];file.value='';if(!selected)return;try{if(selected.size>16384)throw Error();const data=JSON.parse(await selected.text());if(data.version!==1||!data.settings||typeof data.settings!=='object'||Array.isArray(data.settings))throw Error();settings=normalize(data.settings);sync();status.textContent='已载入配置，点击保存后固定。';}catch{status.textContent='配置无效，请选择由本控制台导出的 JSON 文件。';}};
 apply();
 return {get:()=>({...settings}),update(values){settings=normalize({...settings,...values});sync();}};
}

export function installPreview() {
 const source=document.querySelector('#stylePreview, #workflowPreview');
 if(!source)return;
 const button=document.createElement('button');button.type='button';button.className='topbar-action preview-peek';button.textContent='画风预览';button.setAttribute('aria-expanded','false');button.setAttribute('aria-controls','stylePreviewPopover');
 document.querySelector('.preview-header')?.append(button);
 const popup=document.createElement('aside');popup.id='stylePreviewPopover';popup.className='style-preview-popover';popup.hidden=true;popup.setAttribute('aria-label','画风效果预览');
 popup.innerHTML='<button type="button" aria-label="关闭画风预览">×</button><img alt=""><p></p>';
 document.body.append(popup);let anchor=button,timer,pinned=false;
 function hide(){clearTimeout(timer);popup.hidden=true;pinned=false;button.setAttribute('aria-expanded','false');}
 function show(target,url=source.getAttribute('src'),caption=source.alt){
  clearTimeout(timer);anchor=target;
  const img=popup.querySelector('img');img.hidden=!url;
  if(url){img.src=url;img.alt=caption||'画风效果预览';}else img.removeAttribute('src');
  popup.querySelector('p').textContent=url?(caption||'画风效果预览'):'当前方案暂无预览';
  popup.hidden=false;button.setAttribute('aria-expanded','true');position();
 }
 function position(){if(popup.hidden)return;const r=anchor.getBoundingClientRect(),w=popup.offsetWidth,h=popup.offsetHeight;const left=r.right+12+w<innerWidth?r.right+12:Math.max(8,r.left-w-12);popup.style.left=Math.min(left,innerWidth-w-8)+'px';popup.style.top=Math.max(8,Math.min(r.top,innerHeight-h-8))+'px';}
 function delayedHide(){if(!pinned)timer=setTimeout(hide,180);}
 button.onpointerenter=e=>{if(e.pointerType==='mouse')show(button);};button.onpointerleave=delayedHide;
 button.onfocus=()=>show(button);button.onblur=()=>{if(!popup.contains(document.activeElement))delayedHide();};
 button.onclick=()=>{pinned=!pinned;if(pinned)show(button);else hide();};
 popup.onpointerenter=()=>clearTimeout(timer);popup.onpointerleave=delayedHide;
 popup.querySelector('button').onclick=()=>{hide();button.focus();hide();};
 popup.querySelector('img').onerror=()=>{popup.querySelector('img').hidden=true;popup.querySelector('p').textContent='预览暂时无法加载';};
 // Hover previews never select a style or alter the user's prompt.
 document.querySelectorAll('[data-style]').forEach(item=>{
  const open=()=>{const config=typeof STYLE_BOOT!=='undefined'?STYLE_BOOT[item.dataset.style]:null;show(item,config?.preview_thumb||config?.preview,config?.short?config.short+' · 效果预览':item.textContent+' · 效果预览');};
  item.addEventListener('pointerenter',e=>{if(e.pointerType==='mouse'){pinned=false;open();}});item.addEventListener('pointerleave',delayedHide);
  item.addEventListener('focus',open);item.addEventListener('blur',delayedHide);
 });
 new MutationObserver(()=>{if(!popup.hidden&&anchor===button)show(button);}).observe(source,{attributes:true,attributeFilter:['src','alt']});
 document.addEventListener('pointerdown',e=>{if(!popup.contains(e.target)&&e.target!==button&&!e.target.closest('[data-style]'))hide();});
 document.addEventListener('keydown',e=>{if(e.key==='Escape')hide();});
 addEventListener('resize',position);document.addEventListener('scroll',position,true);
}
