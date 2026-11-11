// Cache only this read-only catalog, in memory, for five minutes. Never cache POSTs.
let catalog=null,csrfToken='';
export function configureAccountRequests(token=''){csrfToken=token;catalog=null}
export async function accountFetch(input,options={}){
 const url=new URL(input instanceof Request?input.url:String(input),location.href);
 const method=(options.method||input.method||'GET').toUpperCase();
 if(url.origin===location.origin){
  options={...options,credentials:'same-origin'};
  if(csrfToken&&!['GET','HEAD','OPTIONS'].includes(method)){
   const headers=new Headers(options.headers||input.headers);headers.set('X-CSRF-Token',csrfToken);options.headers=headers;
  }
 }
 const response=await fetch(input,options);
 if(url.origin===location.origin&&url.pathname.startsWith('/api/')&&response.status===401){
  catalog=null;window.dispatchEvent(new CustomEvent('jt:auth-expired'));
 }
 // 2026-11-11: an accepted submission, cancel or retry can reserve or refund quota; let the
 // account surfaces refetch instead of showing the pre-submit numbers until a reload.
 if(url.origin===location.origin&&response.ok&&!['GET','HEAD','OPTIONS'].includes(method)&&
    /^\/api\/(?:[a-z-]*generate|video-queue|image-edit-queue)$/.test(url.pathname)){
  window.dispatchEvent(new CustomEvent('jt:quota-maybe-changed'));
 }
 return response;
}
export async function cachedFetch(input,options={}){
 const url=typeof input==='string'?new URL(input,location.href):null;
 if(!url||url.origin!==location.origin||url.pathname!=='/api/workflows'||url.search||
    (options.method||'GET').toUpperCase()!=='GET'||options.signal||options.headers||options.credentials)return accountFetch(input,options);
 if(!catalog||catalog.expires<Date.now()){
  const entry={expires:Date.now()+300000,promise:null};
  entry.promise=accountFetch(input,options).then(response=>{
   if(!response.ok&&catalog===entry)catalog=null;
   return response;
  }).catch(error=>{if(catalog===entry)catalog=null;throw error});catalog=entry;
 }
 return (await catalog.promise).clone();
}
