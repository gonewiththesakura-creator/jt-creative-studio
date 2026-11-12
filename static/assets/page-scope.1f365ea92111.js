import {cachedFetch} from "/static/assets/api.e4581fedd51a.js";
import {accountStorage} from "/static/assets/account-storage.0c5081b9ad66.js";
export function createPageScope(root,body,path){
 const localStorage=accountStorage(window.localStorage),sessionStorage=accountStorage(window.sessionStorage);
 const documentProxy=new Proxy(document,{get(target,key){
  if(key==='body')return body;
  if(key==='getElementById')return id=>root.getElementById(id);
  if(key==='querySelector'||key==='querySelectorAll')return root[key].bind(root);
  if(key==='activeElement')return root.activeElement;
  if(key==='addEventListener'||key==='removeEventListener')return (type,...args)=>
    (type==='visibilitychange'?document:root)[key](type,...args);
  const value=Reflect.get(target,key,target);return typeof value==='function'?value.bind(target):value;
 }});
 const windowProxy=new Proxy(window,{get(target,key){
  if(key==='document')return documentProxy;
  if(key==='localStorage')return localStorage;
  if(key==='sessionStorage')return sessionStorage;
  if(key==='fetch')return cachedFetch;
  const value=Reflect.get(target,key,target);return typeof value==='function'?value.bind(target):value;
 }});
 return {document:documentProxy,window:windowProxy,fetch:cachedFetch,localStorage,sessionStorage,
  location:new URL(path+location.search,location.origin)};
}
