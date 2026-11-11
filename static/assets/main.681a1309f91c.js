import "/static/assets/retired-upload-storage.04c0ee0da954.js";
import "/static/assets/accretion-layout.091d2d313371.js";
import {createRouter} from "/static/assets/router.cd67b2f26761.js";
import {initializeAccount} from "/static/assets/account.39eca9764438.js";
import {initializeLoginScene,revealWorkbenchFromLogin} from "/static/assets/login-scene.659131d536e8.js";
const manifest=JSON.parse(document.getElementById('appManifest').textContent);
window.jtApp={router:null,metrics:{renderers:0,firstFrame:null}};
initializeLoginScene();
// One visual-only scene starts behind the login gate. Private pages and their
// data requests still wait for the authenticated account response below.
requestAnimationFrame(()=>requestAnimationFrame(()=>import(manifest.singularity).catch(error=>{console.warn('Scene unavailable:',error.message);document.body.dataset.singularity='fallback'})));
const account=await initializeAccount();
const router=createRouter(manifest);
window.jtApp.router=router;
await router.navigate(location.pathname);
if(account.entryTransition)await revealWorkbenchFromLogin();
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
 const connection=navigator.connection||{};
 if(!connection.saveData&&!/2g/.test(connection.effectiveType||''))setTimeout(()=>{
  const preload=()=>Object.keys(manifest.pages).filter(path=>path!==location.pathname).forEach(path=>router.preload(path).catch(()=>{}));
  if('requestIdleCallback'in window)requestIdleCallback(preload);else preload();
 },4000);
}));
