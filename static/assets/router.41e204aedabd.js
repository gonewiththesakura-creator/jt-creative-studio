import {createPageScope} from "/static/assets/page-scope.1f365ea92111.js";
import {accountFetch} from "/static/assets/api.e4581fedd51a.js";
export function createRouter(manifest){
 const pages=new Map(),preloads=new Map(),root=document.getElementById('pageRoot');
 let version=0,active=null;
 const normalize=path=>path==='/promptgen'?'/':path;
 // History and favourites are panels inside each page. The sidebar entry that is lit follows
 // what is on screen, and choosing a workspace always shows that workspace (2026-11-11).
 const LIBRARIES={histOpen:'histOverlay',favOpen:'favOverlay'};
 const overlays=page=>page.shadow.querySelectorAll('.library-overlay');
 const closeLibraries=()=>{for(const page of pages.values())overlays(page).forEach(overlay=>overlay.classList.remove('open'))};
 function syncLibrary(){
  const open=active&&[...overlays(active)].find(overlay=>overlay.classList.contains('open'))?.id||'';
  for(const [id,overlay] of Object.entries(LIBRARIES)){
   const button=document.getElementById(id),on=open===overlay;
   button.classList.toggle('active',on);button.setAttribute('aria-pressed',String(on));
  }
  document.body.dataset.library=open.replace('Overlay','');
  refreshCounts();
 }
 // Sidebar badges: the number of records behind each entry for the page on screen.
 const SCOPES={'/':'creator','/realism':'realism','/video':'video'};
 let countTimer=0,countsFor='';
 async function loadCounts(){
  const path=document.body.dataset.page,scope=SCOPES[path];if(!scope)return;
  try{
   const response=await accountFetch('/api/library-counts?scope='+scope);
   if(!response.ok||document.body.dataset.page!==path)return;
   const counts=await response.json();countsFor=path;
   for(const [id,value] of [['histCount',counts.history],['favCount',counts.favorites]]){
    const node=document.getElementById(id),number=Number(value)||0;
    node.textContent=number>999?'999+':String(number);node.hidden=!number;
   }
  }catch{}
 }
 function refreshCounts(){
  // Never show one page's numbers beside another page.
  if(countsFor!==document.body.dataset.page)for(const id of ['histCount','favCount'])document.getElementById(id).hidden=true;
  clearTimeout(countTimer);countTimer=setTimeout(loadCounts,500);
 }
 addEventListener('jt:library-maybe-changed',refreshCounts);
 async function preload(path){
  if(!preloads.has(path)){
   const item=manifest.pages[path];
   preloads.set(path,Promise.all([import(item.module),fetch(item.markup).then(r=>{
    if(!r.ok)throw Error('页面资源暂时无法加载');return r.text();
   }),fetch(item.css).then(r=>{if(!r.ok)throw Error('页面样式暂时无法加载');return r.text()})])
    .catch(error=>{preloads.delete(path);throw error}));
  }
  return preloads.get(path);
 }
 async function navigate(path,{push=false}={}){
  path=normalize(path);if(!manifest.pages[path])return;
  const ticket=++version,start=performance.now();
  document.getElementById('routeStatus').textContent='';
  try{
   if(!pages.has(path)){
    const [module,markup,css]=await preload(path);
    if(ticket!==version)return;
    const host=document.createElement('section');host.className='page-host';host.dataset.page=path;host.hidden=true;
    const shadow=host.attachShadow({mode:'open'}),style=document.createElement('style');style.textContent=css;
    const body=document.createElement('div');body.className='jt-page-body singularity';body.innerHTML=markup;
    shadow.append(style,body);root.append(host);
    const scope=createPageScope(shadow,body,path);
    try{scope.page=module.mount(scope)}catch(error){host.remove();throw error}
    pages.set(path,{host,shadow,body,scope});
    overlays(pages.get(path)).forEach(overlay=>new MutationObserver(syncLibrary).observe(overlay,{attributes:true,attributeFilter:['class']}));
    window.dispatchEvent(new CustomEvent('jt:page-mounted',{detail:{root:shadow,scope}}));
   }
   if(ticket!==version)return;
   if(active)active.scrollY=window.scrollY;
   closeLibraries();
   for(const [key,page] of pages){page.host.hidden=key!==path;page.host.inert=key!==path;}
   active=pages.get(path);
   if(push&&location.pathname!==path)history.pushState({},'',path);
   document.querySelectorAll('.topnav-link').forEach(a=>{const selected=a.pathname===path;a.classList.toggle('active',selected);if(selected)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current')});
   document.title=manifest.pages[path].title;
   window.scrollTo({top:active.scrollY||0,behavior:'instant'});
   document.body.dataset.page=path;syncLibrary();
   performance.mark('jt:page-ready');
   window.dispatchEvent(new CustomEvent('jt:route',{detail:{path,duration:performance.now()-start}}));
  }catch(error){
   if(ticket!==version)return;
   const status=document.getElementById('routeStatus');status.textContent=error.message+'，请重试。';
   const button=document.createElement('button');button.textContent='重新加载';button.onclick=()=>navigate(path,{push});status.append(button);
  }
 }
 document.querySelector('.topnav').addEventListener('click',event=>{
  const a=event.target.closest('a');if(!a||event.button||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
  event.preventDefault();navigate(a.pathname,{push:true});
 });
 addEventListener('popstate',()=>navigate(location.pathname));
 for(const [id,own] of Object.entries(LIBRARIES))document.getElementById(id).onclick=()=>{
  if(!active)return;
  overlays(active).forEach(overlay=>{if(overlay.id!==own)overlay.classList.remove('open')});
  active.shadow.getElementById(id)?.click();
 };
 document.querySelectorAll('.topnav-link').forEach(a=>a.addEventListener('pointerenter',()=>preload(a.pathname).catch(()=>{}),{once:true}));
 return {navigate,preload,pages};
}
