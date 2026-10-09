// Account data never shares a browser namespace with another signed-in user.
// Display preferences used by the global background remain outside page scopes.
let accountId=null;
export function setStorageAccount(id){accountId=id==null?null:String(id)}
export function accountStorage(storage){
 if(accountId===null)return storage;
 const prefix='jt-user:'+encodeURIComponent(accountId)+':';
 const keys=()=>Object.keys(storage).filter(key=>key.startsWith(prefix));
 return {
  get length(){return keys().length},
  key(index){return keys()[index]?.slice(prefix.length)??null},
  getItem(key){return storage.getItem(prefix+key)},
  setItem(key,value){storage.setItem(prefix+key,String(value))},
  removeItem(key){storage.removeItem(prefix+key)},
  clear(){keys().forEach(key=>storage.removeItem(key))},
 };
}
