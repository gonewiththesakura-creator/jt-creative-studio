import {accountFetch,configureAccountRequests} from "/static/assets/api.1e898baa005a.js";
import {setStorageAccount} from "/static/assets/account-storage.0c5081b9ad66.js";
import {initializeMembershipAdmin} from "/static/assets/membership-admin.abf0e0dba296.js";
import {showLoginScene,markLoginTransition,consumeLoginTransition,prepareLoginEntry,revealWorkbenchImmediately} from "/static/assets/login-scene.659131d536e8.js";

const template=`<section class="account-gate" id="accountGate" aria-labelledby="accountGateTitle">
 <div class="account-gate-card"><span class="account-monogram" aria-hidden="true">JT</span><p class="account-eyebrow">YOUR CREATIVE SPACE</p><h1 id="accountGateTitle">欢迎来到 JT 灵感工作台</h1><p class="account-intro">一个激活码，就是你的专属创作账号。</p>
 <p id="accountGateStatus" role="status" aria-live="polite">正在安全连接…</p><form id="accountCodeLoginForm" class="account-login-form" hidden><label for="accountLoginCode">登录激活码</label><input id="accountLoginCode" name="code" type="password" autocomplete="current-password" autocapitalize="none" spellcheck="false" maxlength="160" required placeholder="输入管理员提供的激活码" aria-describedby="accountLoginHelp accountGateStatus"><button type="submit" class="account-primary" id="accountLogin">进入创作台</button><p id="accountLoginHelp" class="account-help">以后继续使用同一个激活码登录，套餐、历史与收藏都会保留。请妥善保管，不要分享。</p></form><button type="button" class="account-secondary" id="accountRetry" hidden>重新连接</button><button type="button" class="account-admin-login" id="accountAdminLogin" hidden>工作台管理员登录</button></div>
</section>
<dialog class="account-dialog" id="accountDialog" aria-labelledby="accountTitle"><div class="account-dialog-head"><div><p class="account-eyebrow">JT ACCOUNT</p><h2 id="accountTitle">我的账号</h2></div><button type="button" class="account-close" id="accountClose" aria-label="关闭账号面板">×</button></div>
 <p class="account-identity" id="accountIdentity"></p><section class="account-membership" aria-label="当前套餐"><div class="account-plan-line"><h3 id="accountPlan">暂未开通套餐</h3><span class="account-plan-badge" id="accountPlanStatus"></span></div><p id="accountExpiry"></p><dl class="account-quota" id="accountQuota"></dl><p id="accountVideoQueueHelp" class="account-help" hidden>视频排队只计算等待中的视频，不含生成中任务；每个账号单独计算。</p></section>
 <form id="accountRedeemForm"><label for="accountCode">兑换套餐续费码</label><p class="account-help">续费时填写管理员提供的一次性续费码。原来的登录激活码继续使用，历史与收藏保留。</p><div class="account-redeem-row"><input id="accountCode" name="code" autocomplete="off" autocapitalize="characters" spellcheck="false" maxlength="160" required placeholder="输入一次性续费码"><button type="submit" class="account-primary" id="accountRedeem">兑换套餐</button></div><p id="accountRedeemStatus" role="status" aria-live="polite"></p></form>
 <div class="account-dialog-footer"><button type="button" class="account-secondary" id="accountRefresh">刷新套餐</button><button type="button" class="account-secondary" id="accountLogout">退出登录</button></div>
</dialog>`;

export async function initializeAccount(){
 const root=document.createElement('div');root.id='accountRoot';root.innerHTML=template;document.body.append(root);
 const el=id=>document.getElementById(id),shell=document.querySelector('body > .app-shell'),dialog=el('accountDialog');
 const accountButton=document.createElement('button');accountButton.id='accountOpen';accountButton.type='button';accountButton.className='topbar-action';accountButton.textContent='我的账号';accountButton.hidden=true;document.querySelector('.topbar-tools').append(accountButton);
 let mountedAccount=null,initialResolve,ready=false,requesting=false,loggingIn=false,loginMethod='oidc',adminAvailable=false,adminUI=null,mediaIdentityExpired=false;
 const adminTabs=new Set(['plans','codes','renewals','users','reservations']);
 const initial=new Promise(resolve=>initialResolve=resolve);
 const gate=(message,{login=false,retry=false}={})=>{
  if(login){window.dispatchEvent(new CustomEvent('jt:media-clear'));mediaIdentityExpired=mountedAccount!==null}
  showLoginScene();
  shell.hidden=true;shell.inert=true;el('accountGate').hidden=false;el('accountGateStatus').textContent=message;
  const codeLogin=loginMethod==='access_code';
  el('accountCodeLoginForm').hidden=!login;el('accountLoginCode').hidden=!codeLogin;el('accountLoginCode').required=codeLogin;root.querySelector('label[for=accountLoginCode]').hidden=!codeLogin;el('accountLoginHelp').hidden=!codeLogin;el('accountLogin').textContent=codeLogin?'进入创作台':'登录创作台';el('accountAdminLogin').hidden=!login||!adminAvailable||!codeLogin;el('accountRetry').hidden=!retry;accountButton.hidden=true;if(dialog.open)dialog.close();if(adminUI?.dialog.open)adminUI.dialog.close();
 };
 function login(adminTab){
  markLoginTransition();
  const returnTo=new URL(location.href);returnTo.searchParams.delete('admin');if(adminTabs.has(adminTab))returnTo.searchParams.set('admin',adminTab);
  const destination=new URL('/api/auth/login',location.origin);destination.searchParams.set('return_to',returnTo.pathname+returnTo.search);location.assign(destination.href);
 }
 const finiteText=value=>Number.isFinite(Number(value))&&value!==null?String(value):'—';
 function render(data){
  const user=data.user||{},membership=data.membership||{},plan=membership.plan||{},name=user.display_name||user.name||user.username||user.email||'我的账号';
  accountButton.textContent=user.is_admin?'我的账号':name.length>14?name.slice(0,14)+'…':name;accountButton.title='查看我的账号与套餐';
  el('accountIdentity').textContent=name+(user.email&&user.email!==name?' · '+user.email:'');
  el('accountPlan').textContent=membership.plan_name||plan.name||membership.name||'暂未开通套餐';
  el('accountPlanStatus').textContent=membership.active?'使用中':membership.plan_name||plan.name?'已到期':'未开通';
  const expires=membership.expires_at;
  const date=expires?new Date(typeof expires==='number'?expires*1000:expires):null;
  el('accountExpiry').textContent=date&&!Number.isNaN(date.valueOf())?'有效期至 '+date.toLocaleString('zh-CN',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}):'兑换续费码后即可使用套餐权益';
  const quotas=[['图片剩余额度',membership.image_remaining??membership.image_available],['视频剩余额度',membership.video_remaining??membership.video_available],['同时运行任务',membership.max_concurrency??plan.max_concurrent],['视频排队上限',plan.max_video_queued??(membership.plan?100:null)]];
  el('accountQuota').replaceChildren(...quotas.map(([label,value])=>{const item=document.createElement('div'),dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=label;dd.textContent=finiteText(value);item.append(dt,dd);return item}));
  el('accountVideoQueueHelp').hidden=!membership.plan;
 }
 async function refresh({gateOnError=true}={}){
  if(requesting)return;requesting=true;el('accountRetry').disabled=true;el('accountRefresh').disabled=true;
  try{
   const response=await fetch('/api/auth/me',{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(15000)});
   if(!response.ok)throw Error('账号服务暂时无法连接，请重试。');
   const data=await response.json();
   if(data.enabled===false){window.jtAccountEnabled=false;setStorageAccount(null);configureAccountRequests();revealWorkbenchImmediately();el('accountGate').hidden=true;shell.hidden=false;shell.inert=false;ready=true;initialResolve(data);return}
   loginMethod=data.login_method==='access_code'?'access_code':'oidc';adminAvailable=data.admin_login_available===true;
   root.querySelector('.account-intro').textContent=loginMethod==='access_code'?'一个激活码，就是你的专属创作账号。':'登录你的账号，继续创作与管理专属作品。';
   if(data.authenticated!==true||!data.user?.id){gate(loginMethod==='access_code'?'线下开通后，使用激活码登录即可开始创作。':'登录后可使用你的套餐、任务与收藏。',{login:true});return}
   // A different identity requires a clean document, so old timers and media cannot survive an account switch.
   if(mountedAccount!==null&&mountedAccount!==String(data.user.id)){window.dispatchEvent(new CustomEvent('jt:media-clear'));location.reload();return}
   const restoreMedia=mediaIdentityExpired;mediaIdentityExpired=false;
   mountedAccount=String(data.user.id);window.jtAccountEnabled=true;setStorageAccount(data.user.id);configureAccountRequests(data.csrf_token||'');render(data);accountButton.hidden=false;
   const wantsEntry=consumeLoginTransition(),entryTransition=!ready&&wantsEntry;
   if(entryTransition){prepareLoginEntry();el('accountGateStatus').textContent='登录成功，正在进入创作空间…';el('accountCodeLoginForm').hidden=true;el('accountAdminLogin').hidden=true;el('accountRetry').hidden=true}
   else{revealWorkbenchImmediately();el('accountGate').hidden=true;shell.hidden=false;shell.inert=false}
   // The same account signed back in: keep unsubmitted drafts and refetch the private images cleared on expiry.
   if(restoreMedia)window.dispatchEvent(new CustomEvent('jt:media-restore'));
   if(data.user.is_admin&&!adminUI)adminUI=initializeMembershipAdmin({verify:login});
   if(adminUI)adminUI.setVerification(data.admin_verification_required===true,data.admin_verification_expires_at,!!data.user.is_admin);
   const returnTo=new URL(location.href),adminTab=returnTo.searchParams.get('admin');
   if(returnTo.searchParams.has('admin')){returnTo.searchParams.delete('admin');history.replaceState(history.state,'',returnTo.pathname+returnTo.search+returnTo.hash);if(data.user.is_admin&&adminTabs.has(adminTab))adminUI.open(adminTab)}
   if(!ready){ready=true;initialResolve({...data,entryTransition})}
  }catch(error){
   if(gateOnError)gate('暂时无法验证登录状态，请检查网络后重试。',{retry:true});else el('accountRedeemStatus').textContent='套餐信息暂时无法刷新，请稍后重试。';
  }finally{requesting=false;el('accountRetry').disabled=false;el('accountRefresh').disabled=false}
 }
 el('accountAdminLogin').onclick=()=>login('plans');el('accountRetry').onclick=()=>refresh();
 el('accountCodeLoginForm').onsubmit=async event=>{
  event.preventDefault();if(loginMethod!=='access_code'){login();return}const input=el('accountLoginCode'),button=el('accountLogin'),code=input.value.trim();if(loggingIn||requesting||!code)return;
  loggingIn=true;button.disabled=true;input.disabled=true;el('accountAdminLogin').disabled=true;el('accountGateStatus').textContent='正在核验激活码…';
  try{
   // The server binds this anonymous login to the request Origin. The code is never persisted by the app.
   const response=await fetch('/api/auth/code-login',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({code}),signal:AbortSignal.timeout(20000)});
   const result=await response.json().catch(()=>({}));
   if(!response.ok)throw Error(result.error||'激活码无法登录，请核对后重试。');
   input.value='';markLoginTransition();await refresh();
  }catch(error){el('accountGateStatus').textContent=error.name==='TimeoutError'?'连接暂未完成，请重新连接后确认登录状态。':error.message;el('accountRetry').hidden=false}
  finally{loggingIn=false;button.disabled=false;input.disabled=false;el('accountAdminLogin').disabled=false}
 };
 accountButton.onclick=()=>{el('accountRedeemStatus').textContent='';dialog.showModal();refresh({gateOnError:false})};
 el('accountClose').onclick=()=>dialog.close();dialog.addEventListener('click',event=>{if(event.target===dialog){const rect=dialog.getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)dialog.close()}});
 el('accountRefresh').onclick=()=>refresh({gateOnError:false});
 el('accountRedeemForm').onsubmit=async event=>{
  event.preventDefault();const button=el('accountRedeem'),code=el('accountCode').value.trim(),status=el('accountRedeemStatus');if(button.disabled||!code)return;
  button.disabled=true;status.textContent='正在核验续费码…';
  try{const response=await accountFetch('/api/membership/redeem',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code}),signal:AbortSignal.timeout(20000)});const result=await response.json();if(!response.ok)throw Error(result.error||'开通未完成，请稍后重试');el('accountCode').value='';status.textContent='套餐已开通。';await refresh({gateOnError:false})}
  catch(error){status.textContent=error.name==='TimeoutError'?'核验暂未完成，请刷新套餐确认开通结果后再试。':error.message}
  finally{button.disabled=false}
 };
 el('accountLogout').onclick=async()=>{
  const button=el('accountLogout');if(button.disabled)return;button.disabled=true;
  try{
   const response=await accountFetch('/api/auth/logout',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',signal:AbortSignal.timeout(15000)});
   if(!response.ok&&response.status!==401)throw Error('退出未完成，请重试');
   window.dispatchEvent(new CustomEvent('jt:media-clear'));
   if(response.ok){
    const result=await response.json().catch(()=>({}));
    try{const target=new URL(result.logout_url);if(target.protocol==='https:'&&target.host==='auth.dreamapi.club'&&target.pathname==='/api/logout'&&!target.username&&!target.password){location.assign(target.href);return}}catch{}
   }
   location.reload();
  }
  catch(error){el('accountRedeemStatus').textContent=error.message;button.disabled=false}
 };
 window.addEventListener('jt:auth-expired',()=>gate('登录已过期，请重新登录后继续。',{login:true}));
 window.addEventListener('jt:admin-verification-required',()=>adminUI?.setVerification(true));
 // Recheck when returning to a background tab, including after another tab logs out.
 document.addEventListener('visibilitychange',()=>{if(!document.hidden&&ready)refresh()});
 window.addEventListener('pageshow',event=>{if(event.persisted)refresh()});
 gate('正在安全连接…');refresh();return initial;
}
