// Cache only this read-only catalog, in memory, for five minutes. Never cache POSTs.
let catalog=null;
export async function cachedFetch(input,options={}){
 const url=typeof input==='string'?new URL(input,location.href):null;
 if(!url||url.origin!==location.origin||url.pathname!=='/api/workflows'||url.search||
    (options.method||'GET').toUpperCase()!=='GET'||options.signal||options.headers||options.credentials)return fetch(input,options);
 if(!catalog||catalog.expires<Date.now()){
  const entry={expires:Date.now()+300000,promise:null};
  entry.promise=fetch(input,options).then(response=>{
   if(!response.ok&&catalog===entry)catalog=null;
   return response;
  }).catch(error=>{if(catalog===entry)catalog=null;throw error});catalog=entry;
 }
 return (await catalog.promise).clone();
}
