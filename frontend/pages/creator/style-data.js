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
