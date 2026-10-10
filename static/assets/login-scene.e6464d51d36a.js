import {readAppearance,applyAppearanceStyles} from "/static/assets/appearance.6cffb92f339e.js";

// This marker controls presentation only. It contains no identity or credential.
const ENTRY_KEY='jt-login-transition';
let entryRevision=0;
const reduced=()=>{if(matchMedia('(prefers-reduced-motion: reduce)').matches)return true;try{if(localStorage.getItem('jt-singularity-paused')==='true')return true}catch{}const settings=readAppearance();return settings.speed===0||settings.opacity===0};
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const paints=()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
const smooth=value=>{const t=Math.max(0,Math.min(1,value));return t*t*(3-2*t)};

export function initializeLoginScene(){
 if(document.getElementById('loginSceneFallback'))return;
 applyAppearanceStyles(readAppearance());
 const backdrop=document.createElement('div');backdrop.id='loginSceneFallback';backdrop.setAttribute('aria-hidden','true');
 // A quiet black backdrop stays in place until the real first frame is ready.
 // Never substitute an unrelated CSS ring while the shader is compiling.
 document.body.prepend(backdrop);
}
export function markLoginTransition(){try{sessionStorage.setItem(ENTRY_KEY,String(Date.now()))}catch{}}
export function consumeLoginTransition(){
 try{const stored=sessionStorage.getItem(ENTRY_KEY);sessionStorage.removeItem(ENTRY_KEY);const age=Date.now()-Number(stored);return stored!==null&&age>=0&&age<30*60*1000}catch{return false}
}
export function showLoginScene(){
 window.jtApp?.scene?.endEntry();
 document.getElementById('singularityCanvas')?.style.removeProperty('--entry-opacity');
 entryRevision++;document.body.dataset.loginScene='login';
 document.querySelector('.app-shell')?.classList.remove('account-shell-entering','account-shell-staged');
 const gate=document.getElementById('accountGate');if(gate){gate.classList.remove('account-gate-leaving');gate.inert=false}
}
export function prepareLoginEntry(){
 // Stop the heavy visual before private page modules mount. Their initial
 // layout can then settle without competing with fresh ray-marching frames.
 window.jtApp?.scene?.beginEntry();
 document.body.dataset.loginScene='waiting-entry';
 const gate=document.getElementById('accountGate');if(gate)gate.inert=true;
}
export async function revealWorkbenchFromLogin(){
 // Authentication may have expired while the route's resources were loading.
 // A new animation must never override a gate reopened by that later failure.
 if(document.body.dataset.loginScene!=='waiting-entry')return;
 const revision=++entryRevision,gate=document.getElementById('accountGate'),shell=document.querySelector('body > .app-shell');
 if(!gate||!shell)return;
 const unchanged=()=>revision===entryRevision;
 let canvas=document.getElementById('singularityCanvas');
 const finish=()=>{if(!unchanged())return;gate.hidden=true;gate.inert=false;shell.hidden=false;shell.inert=false;shell.classList.remove('account-shell-entering','account-shell-staged');document.body.dataset.loginScene='workbench';canvas?.style.removeProperty('--entry-opacity');window.jtApp?.scene?.endEntry()};
 if(reduced()){finish();return}
 // Route mounting finishes before travel starts. Give its style/layout work
 // two paints, then use only a frozen GPU texture during the transition.
 shell.classList.add('account-shell-staged');shell.hidden=false;
 await paints();
 const sceneDeadline=performance.now()+700;
 while(!['ready','fallback'].includes(document.body.dataset.singularity)&&performance.now()<sceneDeadline){await delay(40);if(!unchanged())return}
 if(!unchanged())return;
 canvas=document.getElementById('singularityCanvas');
 const scene=window.jtApp?.scene;
 const travel=scene?.beginEntry()===true&&await scene.waitForEntry();
 if(!unchanged())return;
 const opacity=scene?.getAppearance?.().opacity??readAppearance().opacity;
 document.body.dataset.loginScene='entering';gate.classList.add('account-gate-leaving');
 const start=performance.now();
 await new Promise(resolve=>{
  const frame=now=>{
   if(!unchanged()){resolve();return}
   const elapsed=now-start;
   let alpha=1;
   if(elapsed<1060){
    if(elapsed>=820)document.body.dataset.loginScene='through';
    alpha=1-smooth((elapsed-660)/400);
    if(travel)scene.paintEntry(Math.exp(3.1*smooth(elapsed/1060)));
   }else{
    if(!gate.hidden){gate.hidden=true;shell.classList.remove('account-shell-staged');shell.inert=false;shell.classList.add('account-shell-entering');document.body.dataset.loginScene='arriving';if(travel)scene.paintEntry(1)}
    alpha=smooth((elapsed-1140)/660);
    if(elapsed>=1140)document.body.dataset.loginScene='revealing';
   }
   canvas?.style.setProperty('--entry-opacity',String(opacity*alpha));
   if(elapsed>=1800){finish();resolve();return}
   requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
 });
}
export function revealWorkbenchImmediately(){
 document.querySelector('.app-shell')?.classList.remove('account-shell-staged');
 entryRevision++;document.body.dataset.loginScene='workbench';
}
