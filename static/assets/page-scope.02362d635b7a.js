import {cachedFetch} from "/static/assets/api.0424bfb40c97.js";
export function createPageScope(root,body,path){
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
  const value=Reflect.get(target,key,target);return typeof value==='function'?value.bind(target):value;
 }});
 return {document:documentProxy,window:windowProxy,fetch:cachedFetch,
  location:new URL(path+location.search,location.origin)};
}
