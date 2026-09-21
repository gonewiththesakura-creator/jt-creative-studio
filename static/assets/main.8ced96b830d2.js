import {createRouter} from "/static/assets/router.c2c2e271b875.js";
const manifest=JSON.parse(document.getElementById('appManifest').textContent);
const router=createRouter(manifest);
window.jtApp={router,metrics:{renderers:0,firstFrame:null}};
await router.navigate(location.pathname);
// Configuration loading may be slow; do not compete with it for first interaction.
const initial=router.pages.get(location.pathname);
if(initial)await new Promise(resolve=>{
 const ready=()=>!initial.shadow.querySelector('#genApiBtn:disabled, #workflowSelect:disabled, .config-loading');
 if(ready())return resolve();
 const observer=new MutationObserver(()=>{if(ready()){observer.disconnect();clearTimeout(timer);resolve()}});
 observer.observe(initial.shadow,{subtree:true,childList:true,attributes:true,attributeFilter:['disabled']});
 const timer=setTimeout(()=>{observer.disconnect();resolve()},3000);
});
// Two paint opportunities before importing any graphics modules.
requestAnimationFrame(()=>requestAnimationFrame(()=>{
 const start=()=>import(manifest.singularity).catch(error=>{console.warn('Scene unavailable:',error.message);document.body.dataset.singularity='fallback'});
 if('requestIdleCallback'in window)requestIdleCallback(start,{timeout:1600});else setTimeout(start,250);
 const connection=navigator.connection||{};
 if(!connection.saveData&&!/2g/.test(connection.effectiveType||''))setTimeout(()=>{
  const preload=()=>Object.keys(manifest.pages).filter(path=>path!==location.pathname).forEach(path=>router.preload(path).catch(()=>{}));
  if('requestIdleCallback'in window)requestIdleCallback(preload);else preload();
 },4000);
}));
