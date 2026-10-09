import {accountFetch,configureAccountRequests} from "/static/assets/api.1e898baa005a.js";
import {setStorageAccount} from "/static/assets/account-storage.0c5081b9ad66.js";
import {initializeMembershipAdmin} from "/static/assets/membership-admin.cd307a45430a.js";
import {showLoginScene,markLoginTransition,consumeLoginTransition,prepareLoginEntry,revealWorkbenchImmediately} from "/static/assets/login-scene.e879cf492548.js";

const template=`<section class="account-gate" id="accountGate" aria-labelledby="accountGateTitle">
 <div class="account-gate-card"><span class="account-monogram" aria-hidden="true">JT</span><p class="account-eyebrow">YOUR CREATIVE SPACE</p><h1 id="accountGateTitle">欢迎来到 JT 创作台</h1><p class="account-intro">登录你的账号，继续创作与管理专属作品。</p>
 <p id="accountGateStatus" role="status">正在安全连接…</p><button type="button" class="account-primary" id="accountLogin" hidden>登录 / 注册</button><button type="button" class="account-secondary" id="accountRetry" hidden>重新连接</button></div>
</section>
<dialog class="account-dialog" id="accountDialog" aria-labelledby="accountTitle"><div class="account-dialog-head"><div><p class="account-eyebrow">JT ACCOUNT</p><h2 id="accountTitle">我的账号</h2></div><button type="button" class="account-close" id="accountClose" aria-label="关闭账号面板">×</button></div>
 <p class="account-identity" id="accountIdentity"></p><section class="account-membership" aria-label="当前套餐"><div class="account-plan-line"><h3 id="accountPlan">暂未开通套餐</h3><span class="account-plan-badge" id="accountPlanStatus"></span></div><p id="accountExpiry"></p><dl class="account-quota" id="accountQuota"></dl></section>
 <form id="accountRedeemForm"><label for="accountCode">兑换套餐激活码</label><p class="account-help">线下购买后，填写管理员提供的激活码。</p><div class="account-redeem-row"><input id="accountCode" name="code" autocomplete="off" autocapitalize="characters" spellcheck="false" maxlength="160" required placeholder="输入激活码"><button type="submit" class="account-primary" id="accountRedeem">立即开通</button></div><p id="accountRedeemStatus" role="status" aria-live="polite"></p></form>
 <div class="account-dialog-footer"><button type="button" class="account-secondary" id="accountRefresh">刷新套餐</button><button type="button" class="account-secondary" id="accountLogout">退出登录</button></div>
</dialog>`;

export async function initializeAccount(){
 const root=document.createElement('div');root.id='accountRoot';root.innerHTML=template;document.body.append(root);
 const el=id=>document.getElementById(id),shell=document.querySelector('body > .app-shell'),dialog=el('accountDialog');
 const accountButton=document.createElement('button');accountButton.id='accountOpen';accountButton.type='button';accountButton.className='topbar-action';accountButton.textContent='我的账号';accountButton.hidden=true;document.querySelector('.topbar-tools').append(accountButton);
 let mountedAccount=null,initialResolve,ready=false,requesting=false,adminUI=null;
 const initial=new Promise(resolve=>initialResolve=resolve);
 const gate=(message,{login=false,retry=false}={})=>{
  showLoginScene();
  shell.hidden=true;shell.inert=true;el('accountGate').hidden=false;el('accountGateStatus').textContent=message;
  el('accountLogin').hidden=!login;el('accountRetry').hidden=!retry;accountButton.hidden=true;if(dialog.open)dialog.close();if(adminUI?.dialog.open)adminUI.dialog.close();
 };
 function login(){
  markLoginTransition();
  const destination=new URL('/api/auth/login',location.origin);destination.searchParams.set('return_to',location.pathname+location.search);location.assign(destination.href);
 }
 const finiteText=value=>Number.isFinite(Number(value))&&value!==null?String(value):'—';
 function render(data){
  const user=data.user||{},membership=data.membership||{},plan=membership.plan||{},name=user.display_name||user.name||user.username||user.email||'我的账号';
  accountButton.textContent=name.length>14?name.slice(0,14)+'…':name;accountButton.title='管理账号与套餐';
  el('accountIdentity').textContent=name+(user.email&&user.email!==name?' · '+user.email:'');
  el('accountPlan').textContent=membership.plan_name||plan.name||membership.name||'暂未开通套餐';
  el('accountPlanStatus').textContent=membership.active?'使用中':membership.plan_name||plan.name?'已到期':'未开通';
  const expires=membership.expires_at;
  const date=expires?new Date(typeof expires==='number'?expires*1000:expires):null;
  el('accountExpiry').textContent=date&&!Number.isNaN(date.valueOf())?'有效期至 '+date.toLocaleString('zh-CN',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}):'兑换激活码后即可使用套餐权益';
  const quotas=[['图片剩余额度',membership.image_remaining??membership.image_available],['视频剩余额度',membership.video_remaining??membership.video_available],['同时运行任务',membership.max_concurrency??plan.max_concurrent]];
  el('accountQuota').replaceChildren(...quotas.map(([label,value])=>{const item=document.createElement('div'),dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=label;dd.textContent=finiteText(value);item.append(dt,dd);return item}));
 }
 async function refresh({gateOnError=true}={}){
  if(requesting)return;requesting=true;el('accountRetry').disabled=true;el('accountRefresh').disabled=true;
  try{
   const response=await fetch('/api/auth/me',{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(15000)});
   if(!response.ok)throw Error('账号服务暂时无法连接，请重试。');
   const data=await response.json();
   if(data.enabled===false){window.jtAccountEnabled=false;setStorageAccount(null);configureAccountRequests();revealWorkbenchImmediately();el('accountGate').hidden=true;shell.hidden=false;shell.inert=false;ready=true;initialResolve(data);return}
   if(data.authenticated!==true||!data.user?.id){gate('登录后可使用你的套餐、任务与收藏。',{login:true});return}
   // A different identity requires a clean document, so old timers and media cannot survive an account switch.
   if(mountedAccount!==null&&mountedAccount!==String(data.user.id)){location.reload();return}
   mountedAccount=String(data.user.id);window.jtAccountEnabled=true;setStorageAccount(data.user.id);configureAccountRequests(data.csrf_token||'');render(data);accountButton.hidden=false;
   const entryTransition=!ready&&consumeLoginTransition();
   if(entryTransition){prepareLoginEntry();el('accountGateStatus').textContent='登录成功，正在进入创作空间…';el('accountLogin').hidden=true;el('accountRetry').hidden=true}
   else{revealWorkbenchImmediately();el('accountGate').hidden=true;shell.hidden=false;shell.inert=false}
   if(data.user.is_admin&&!adminUI)adminUI=initializeMembershipAdmin();
   if(adminUI){adminUI.trigger.hidden=!data.user.is_admin;if(!data.user.is_admin&&adminUI.dialog.open)adminUI.dialog.close()}
   if(!ready){ready=true;initialResolve({...data,entryTransition})}
  }catch(error){
   if(gateOnError)gate('暂时无法验证登录状态，请检查网络后重试。',{retry:true});else el('accountRedeemStatus').textContent='套餐信息暂时无法刷新，请稍后重试。';
  }finally{requesting=false;el('accountRetry').disabled=false;el('accountRefresh').disabled=false}
 }
 el('accountLogin').onclick=login;el('accountRetry').onclick=()=>refresh();
 accountButton.onclick=()=>{el('accountRedeemStatus').textContent='';dialog.showModal();refresh({gateOnError:false})};
 el('accountClose').onclick=()=>dialog.close();dialog.addEventListener('click',event=>{if(event.target===dialog){const rect=dialog.getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)dialog.close()}});
 el('accountRefresh').onclick=()=>refresh({gateOnError:false});
 el('accountRedeemForm').onsubmit=async event=>{
  event.preventDefault();const button=el('accountRedeem'),code=el('accountCode').value.trim(),status=el('accountRedeemStatus');if(button.disabled||!code)return;
  button.disabled=true;status.textContent='正在核验激活码…';
  try{const response=await accountFetch('/api/membership/redeem',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code}),signal:AbortSignal.timeout(20000)});const result=await response.json();if(!response.ok)throw Error(result.error||'开通未完成，请稍后重试');el('accountCode').value='';status.textContent='套餐已开通。';await refresh({gateOnError:false})}
  catch(error){status.textContent=error.name==='TimeoutError'?'核验暂未完成，请刷新套餐确认开通结果后再试。':error.message}
  finally{button.disabled=false}
 };
 el('accountLogout').onclick=async()=>{
  const button=el('accountLogout');if(button.disabled)return;button.disabled=true;
  try{
   const response=await accountFetch('/api/auth/logout',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',signal:AbortSignal.timeout(15000)});
   if(!response.ok&&response.status!==401)throw Error('退出未完成，请重试');
   if(response.ok){
    const result=await response.json().catch(()=>({}));
    try{const target=new URL(result.logout_url);if(target.protocol==='https:'&&target.host==='auth.dreamapi.club'&&target.pathname==='/api/logout'&&!target.username&&!target.password){location.assign(target.href);return}}catch{}
   }
   location.reload();
  }
  catch(error){el('accountRedeemStatus').textContent=error.message;button.disabled=false}
 };
 window.addEventListener('jt:auth-expired',()=>gate('登录已过期，请重新登录后继续。',{login:true}));
 // Recheck when returning to a background tab, including after another tab logs out.
 document.addEventListener('visibilitychange',()=>{if(!document.hidden&&ready)refresh()});
 window.addEventListener('pageshow',event=>{if(event.persisted)refresh()});
 gate('正在安全连接…');refresh();return initial;
}
