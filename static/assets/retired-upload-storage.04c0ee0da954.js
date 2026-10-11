// Retire browser-held upload credentials before account or page initialization.
// Only enumerate key names: never load, log, or send the stored secret values.
const retiredKey='jt-personal-rh-key';
const retired=name=>name===retiredKey||(name.startsWith('jt-user:')&&name.endsWith(':'+retiredKey));
export function purgeRetiredUploadCredentials(){
 for(const name of ['localStorage','sessionStorage']){
  try{const storage=window[name];for(const key of Object.keys(storage))if(retired(key))storage.removeItem(key)}catch{}
 }
}
purgeRetiredUploadCredentials();
window.addEventListener('pageshow',purgeRetiredUploadCredentials);
window.addEventListener('storage',event=>{if(event.key&&retired(event.key))purgeRetiredUploadCredentials()});
