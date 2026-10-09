// This marker controls presentation only. It contains no identity or credential.
const ENTRY_KEY='jt-login-transition';
let entryRevision=0;
const appearance=()=>{try{return JSON.parse(localStorage.getItem('jt-singularity-appearance-v1')||'null')||{}}catch{return {}}};
const reduced=()=>{if(matchMedia('(prefers-reduced-motion: reduce)').matches)return true;try{if(localStorage.getItem('jt-singularity-paused')==='true')return true}catch{}const settings=appearance();return settings.speed===0||settings.opacity===0};
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const paints=()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));

export function initializeLoginScene(){
 if(document.getElementById('loginSceneFallback'))return;
 const settings=appearance();if(typeof settings.opacity==='number'&&Number.isFinite(settings.opacity))document.body.style.setProperty('--appearance-opacity',Math.min(1,Math.max(0,settings.opacity)));
 const backdrop=document.createElement('div');backdrop.id='loginSceneFallback';backdrop.setAttribute('aria-hidden','true');
 backdrop.innerHTML='<div class="login-scene-orbit"></div>';document.body.prepend(backdrop);
}
export function markLoginTransition(){try{sessionStorage.setItem(ENTRY_KEY,String(Date.now()))}catch{}}
export function consumeLoginTransition(){
 try{const stored=sessionStorage.getItem(ENTRY_KEY);sessionStorage.removeItem(ENTRY_KEY);const age=Date.now()-Number(stored);return stored!==null&&age>=0&&age<30*60*1000}catch{return false}
}
export function showLoginScene(){
 entryRevision++;document.body.dataset.loginScene='login';
 document.querySelector('.app-shell')?.classList.remove('account-shell-entering');
 const gate=document.getElementById('accountGate');if(gate){gate.classList.remove('account-gate-leaving');gate.inert=false}
}
export function prepareLoginEntry(){
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
 const finish=()=>{if(!unchanged())return;gate.hidden=true;gate.inert=false;shell.hidden=false;shell.inert=false;shell.classList.remove('account-shell-entering');document.body.dataset.loginScene='workbench'};
 if(reduced()){finish();return}
 // The static ring is already painted while WebGL compiles, so an unavailable
 // GPU never blocks entering the application or produces an empty white frame.
 await paints();
 const sceneDeadline=performance.now()+700;
 while(!['ready','fallback'].includes(document.body.dataset.singularity)&&performance.now()<sceneDeadline){await delay(40);if(!unchanged())return}
 if(!unchanged())return;
 document.body.dataset.loginScene='entering';gate.classList.add('account-gate-leaving');
 await delay(950);if(!unchanged())return;
 document.body.dataset.loginScene='through';
 await delay(370);if(!unchanged())return;
 gate.hidden=true;shell.hidden=false;shell.inert=false;shell.classList.add('account-shell-entering');document.body.dataset.loginScene='arriving';
 await paints();if(!unchanged())return;
 document.body.dataset.loginScene='revealing';
 await delay(720);finish();
}
export function revealWorkbenchImmediately(){
 entryRevision++;document.body.dataset.loginScene='workbench';
}
