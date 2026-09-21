import {createPageScope} from "/static/assets/page-scope.02362d635b7a.js";
export function createRouter(manifest){
 const pages=new Map(),preloads=new Map(),root=document.getElementById('pageRoot');
 let version=0,active=null;
 const normalize=path=>path==='/promptgen'?'/':path;
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
    window.dispatchEvent(new CustomEvent('jt:page-mounted',{detail:{root:shadow,scope}}));
   }
   if(ticket!==version)return;
   if(active)active.scrollY=window.scrollY;
   for(const [key,page] of pages){page.host.hidden=key!==path;page.host.inert=key!==path;}
   active=pages.get(path);
   if(push&&location.pathname!==path)history.pushState({},'',path);
   document.querySelectorAll('.topnav-link').forEach(a=>{const selected=a.pathname===path;a.classList.toggle('active',selected);if(selected)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current')});
   document.title=manifest.pages[path].title;
   window.scrollTo({top:active.scrollY||0,behavior:'instant'});
   document.body.dataset.page=path;
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
 for(const id of ['histOpen','favOpen'])document.getElementById(id).onclick=()=>active?.shadow.getElementById(id)?.click();
 document.querySelectorAll('.topnav-link').forEach(a=>a.addEventListener('pointerenter',()=>preload(a.pathname).catch(()=>{}),{once:true}));
 return {navigate,preload,pages};
}
