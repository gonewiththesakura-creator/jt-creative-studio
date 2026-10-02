export function mount({document,window,fetch,location}){
const histOverlay=document.getElementById("histOverlay");
const favOverlay=document.getElementById("favOverlay");
function renderPromptPresets(parent,input,workflowId){
  const key='jt-video-prompt-presets-v1:'+workflowId,box=document.createElement('details');
  box.className='prompt-presets';box.open=true;
  const heading=document.createElement('summary');heading.textContent='提示词预设';
  const slots=document.createElement('div');slots.className='prompt-preset-slots';
  const name=document.createElement('input');name.type='text';name.maxLength=24;name.placeholder='预设名称（可选）';name.setAttribute('aria-label','预设名称');
  const actions=document.createElement('div');actions.className='prompt-preset-actions';
  const note=document.createElement('div');note.className='note';note.setAttribute('aria-live','polite');
  let selected=0,stored=[];
  try{const value=JSON.parse(localStorage.getItem(key)||'[]');if(Array.isArray(value))stored=value}catch{}
  let presets=Array.from({length:6},(_,i)=>{const p=stored[i];return p&&typeof p.prompt==='string'?{name:String(p.name||'').slice(0,24),prompt:p.prompt}:null});
  const buttons=presets.map((_,i)=>{const b=document.createElement('button');b.type='button';b.onclick=()=>{selected=i;render();note.textContent=presets[i]?'已选择预设，点击“套用”填入提示词':'空位置，可保存当前提示词'};slots.append(b);return b});
  const apply=document.createElement('button'),save=document.createElement('button'),clear=document.createElement('button');
  for(const b of [apply,save,clear])b.type='button';
  apply.textContent='套用';save.textContent='保存当前';clear.textContent='清空';actions.append(apply,save,clear);
  const render=()=>{buttons.forEach((b,i)=>{b.textContent=presets[i]?.name||'预设 '+(i+1);b.title=presets[i]?.prompt||'空预设';b.setAttribute('aria-pressed',String(i===selected));b.classList.toggle('saved',Boolean(presets[i]))});name.value=presets[selected]?.name||'';apply.disabled=clear.disabled=!presets[selected]};
  const persist=(next,message)=>{try{localStorage.setItem(key,JSON.stringify(next));presets=next;render();note.textContent=message}catch{note.textContent='保存失败：浏览器存储不可用，请勿关闭当前提示词'}};
  save.onclick=()=>{if(!input.value.trim()){note.textContent='先填写提示词，再保存到预设';return}if(presets[selected]&&!confirm('覆盖这个位置已有的预设？'))return;const next=presets.slice();next[selected]={name:name.value.trim().slice(0,24),prompt:input.value};persist(next,'已保存至当前浏览器，刷新后仍保留')};
  apply.onclick=()=>{const p=presets[selected];if(!p)return;input.value=p.prompt;input.dispatchEvent(new Event('input',{bubbles:true}));note.textContent='已套用，可继续修改；尚未提交生成'};
  clear.onclick=()=>{if(!presets[selected]||!confirm('清空这个预设？当前提示词会保留。'))return;const next=presets.slice();next[selected]=null;persist(next,'已清空预设，当前提示词保留')};
  note.textContent='6 个位置 · 保存在当前浏览器 · 仅保存提示词';render();box.append(heading,slots,name,actions,note);input.after(box);
}

function renderLoraSettings(form, params, state) {
  const controls = params.filter(([, param]) => param.group === 'lora' && param.type === 'select');
  if (!controls.length) return;
  const details = document.createElement('details');
  details.className = 'lora-settings';
  const summary = document.createElement('summary');
  summary.textContent = 'LoRA 详细调整';
  const note = document.createElement('p');
  note.textContent = '按下列顺序依次加载。强度为 0 时不产生影响；收起面板仍会使用当前设置。';
  details.append(summary, note);
  state.loraParams ??= {};
  const resets = [];
  controls.forEach(([modelKey, modelParam]) => {
    const key = modelKey.replace(/_model$/, '_strength');
    const param = params.find(([name]) => name === key)[1];
    const row = document.createElement('div');
    row.className = 'lora-setting';
    const label = document.createElement('label');
    label.htmlFor = 'param_' + modelKey;
    label.textContent = modelParam.label;
    const select = document.createElement('select');
    select.id = 'param_' + modelKey;
    select.dataset.paramType = 'select';
    for (const option of modelParam.options) {
      const item = document.createElement('option');
      item.value = optionValue(option); item.textContent = optionLabel(option);
      select.append(item);
    }
    select.value = state.loraParams[modelKey] ?? modelParam.default;
    const inputs = document.createElement('div');
    inputs.className = 'lora-strength-inputs';
    const range = document.createElement('input');
    const number = document.createElement('input');
    range.type = 'range'; number.type = 'number';
    range.setAttribute('aria-label', param.label + '滑块');
    number.id = 'param_' + key;
    number.setAttribute('aria-label', param.label);
    number.dataset.paramType = 'float';
    number.required = true;
    for (const input of [range, number]) {
      input.min = param.min; input.max = param.max; input.step = param.step;
      input.value = state.loraParams[key] ?? param.default;
    }
    const remember = () => { state.loraParams[key] = number.value; };
    range.oninput = () => { number.value = range.value; remember(); };
    number.oninput = () => {
      if (number.value !== '' && number.validity.valid) range.value = number.value;
      remember();
    };
    const updateEnabled = () => { range.disabled = number.disabled = select.value === 'none'; };
    select.onchange = () => { state.loraParams[modelKey] = select.value; updateEnabled(); };
    updateEnabled();
    resets.push(() => { select.value = modelParam.default; select.onchange(); range.value = number.value = param.default; remember(); });
    inputs.append(range, number); row.append(label, select, inputs); details.append(row);
  });
  const reset = document.createElement('button');
  reset.type = 'button'; reset.className = 'lora-reset';
  reset.textContent = '恢复默认设置';
  reset.onclick = () => resets.forEach(apply => apply());
  details.append(reset); form.append(details);
}

/*
Copyright (c) 2014-2025 Chen, Yi-Cyuan

MIT License

Permission is hereby granted, free of charge, to any person obtaining
a copy of this software and associated documentation files (the
"Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so, subject to
the following conditions:

The above copyright notice and this permission notice shall be
included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

*/
/**
 * [js-sha256]{@link https://github.com/emn178/js-sha256}
 *
 * @version 0.11.1
 * @author Chen, Yi-Cyuan [emn178@gmail.com]
 * @copyright Chen, Yi-Cyuan 2014-2025
 * @license MIT
 */
!function(){"use strict";function t(t,i){i?(d[0]=d[16]=d[1]=d[2]=d[3]=d[4]=d[5]=d[6]=d[7]=d[8]=d[9]=d[10]=d[11]=d[12]=d[13]=d[14]=d[15]=0,this.blocks=d):this.blocks=[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],t?(this.h0=3238371032,this.h1=914150663,this.h2=812702999,this.h3=4144912697,this.h4=4290775857,this.h5=1750603025,this.h6=1694076839,this.h7=3204075428):(this.h0=1779033703,this.h1=3144134277,this.h2=1013904242,this.h3=2773480762,this.h4=1359893119,this.h5=2600822924,this.h6=528734635,this.h7=1541459225),this.block=this.start=this.bytes=this.hBytes=0,this.finalized=this.hashed=!1,this.first=!0,this.is224=t}function i(i,r,s){var e,n=typeof i;if("string"===n){var o,a=[],u=i.length,c=0;for(e=0;e<u;++e)(o=i.charCodeAt(e))<128?a[c++]=o:o<2048?(a[c++]=192|o>>>6,a[c++]=128|63&o):o<55296||o>=57344?(a[c++]=224|o>>>12,a[c++]=128|o>>>6&63,a[c++]=128|63&o):(o=65536+((1023&o)<<10|1023&i.charCodeAt(++e)),a[c++]=240|o>>>18,a[c++]=128|o>>>12&63,a[c++]=128|o>>>6&63,a[c++]=128|63&o);i=a}else{if("object"!==n)throw new Error(h);if(null===i)throw new Error(h);if(f&&i.constructor===ArrayBuffer)i=new Uint8Array(i);else if(!(Array.isArray(i)||f&&ArrayBuffer.isView(i)))throw new Error(h)}i.length>64&&(i=new t(r,!0).update(i).array());var y=[],p=[];for(e=0;e<64;++e){var l=i[e]||0;y[e]=92^l,p[e]=54^l}t.call(this,r,s),this.update(p),this.oKeyPad=y,this.inner=!0,this.sharedMemory=s}var h="input is invalid type",r="object"==typeof window,s=r?window:{};s.JS_SHA256_NO_WINDOW&&(r=!1);var e=!r&&"object"==typeof self,n=!s.JS_SHA256_NO_NODE_JS&&"object"==typeof process&&process.versions&&process.versions.node&&"renderer"!=process.type;n?s=global:e&&(s=self);var o=!s.JS_SHA256_NO_COMMON_JS&&"object"==typeof module&&module.exports,a="function"==typeof define&&define.amd,f=!s.JS_SHA256_NO_ARRAY_BUFFER&&"undefined"!=typeof ArrayBuffer,u="0123456789abcdef".split(""),c=[-2147483648,8388608,32768,128],y=[24,16,8,0],p=[1116352408,1899447441,3049323471,3921009573,961987163,1508970993,2453635748,2870763221,3624381080,310598401,607225278,1426881987,1925078388,2162078206,2614888103,3248222580,3835390401,4022224774,264347078,604807628,770255983,1249150122,1555081692,1996064986,2554220882,2821834349,2952996808,3210313671,3336571891,3584528711,113926993,338241895,666307205,773529912,1294757372,1396182291,1695183700,1986661051,2177026350,2456956037,2730485921,2820302411,3259730800,3345764771,3516065817,3600352804,4094571909,275423344,430227734,506948616,659060556,883997877,958139571,1322822218,1537002063,1747873779,1955562222,2024104815,2227730452,2361852424,2428436474,2756734187,3204031479,3329325298],l=["hex","array","digest","arrayBuffer"],d=[];!s.JS_SHA256_NO_NODE_JS&&Array.isArray||(Array.isArray=function(t){return"[object Array]"===Object.prototype.toString.call(t)}),!f||!s.JS_SHA256_NO_ARRAY_BUFFER_IS_VIEW&&ArrayBuffer.isView||(ArrayBuffer.isView=function(t){return"object"==typeof t&&t.buffer&&t.buffer.constructor===ArrayBuffer});var A=function(i,h){return function(r){return new t(h,!0).update(r)[i]()}},w=function(i){var h=A("hex",i);n&&(h=b(h,i)),h.create=function(){return new t(i)},h.update=function(t){return h.create().update(t)};for(var r=0;r<l.length;++r){var s=l[r];h[s]=A(s,i)}return h},b=function(t,i){var r,e=require("crypto"),n=require("buffer").Buffer,o=i?"sha224":"sha256";r=n.from&&!s.JS_SHA256_NO_BUFFER_FROM?n.from:function(t){return new n(t)};return function(i){if("string"==typeof i)return e.createHash(o).update(i,"utf8").digest("hex");if(null===i||void 0===i)throw new Error(h);return i.constructor===ArrayBuffer&&(i=new Uint8Array(i)),Array.isArray(i)||ArrayBuffer.isView(i)||i.constructor===n?e.createHash(o).update(r(i)).digest("hex"):t(i)}},_=function(t,h){return function(r,s){return new i(r,h,!0).update(s)[t]()}},v=function(t){var h=_("hex",t);h.create=function(h){return new i(h,t)},h.update=function(t,i){return h.create(t).update(i)};for(var r=0;r<l.length;++r){var s=l[r];h[s]=_(s,t)}return h};t.prototype.update=function(t){if(!this.finalized){var i,r=typeof t;if("string"!==r){if("object"!==r)throw new Error(h);if(null===t)throw new Error(h);if(f&&t.constructor===ArrayBuffer)t=new Uint8Array(t);else if(!(Array.isArray(t)||f&&ArrayBuffer.isView(t)))throw new Error(h);i=!0}for(var s,e,n=0,o=t.length,a=this.blocks;n<o;){if(this.hashed&&(this.hashed=!1,a[0]=this.block,this.block=a[16]=a[1]=a[2]=a[3]=a[4]=a[5]=a[6]=a[7]=a[8]=a[9]=a[10]=a[11]=a[12]=a[13]=a[14]=a[15]=0),i)for(e=this.start;n<o&&e<64;++n)a[e>>>2]|=t[n]<<y[3&e++];else for(e=this.start;n<o&&e<64;++n)(s=t.charCodeAt(n))<128?a[e>>>2]|=s<<y[3&e++]:s<2048?(a[e>>>2]|=(192|s>>>6)<<y[3&e++],a[e>>>2]|=(128|63&s)<<y[3&e++]):s<55296||s>=57344?(a[e>>>2]|=(224|s>>>12)<<y[3&e++],a[e>>>2]|=(128|s>>>6&63)<<y[3&e++],a[e>>>2]|=(128|63&s)<<y[3&e++]):(s=65536+((1023&s)<<10|1023&t.charCodeAt(++n)),a[e>>>2]|=(240|s>>>18)<<y[3&e++],a[e>>>2]|=(128|s>>>12&63)<<y[3&e++],a[e>>>2]|=(128|s>>>6&63)<<y[3&e++],a[e>>>2]|=(128|63&s)<<y[3&e++]);this.lastByteIndex=e,this.bytes+=e-this.start,e>=64?(this.block=a[16],this.start=e-64,this.hash(),this.hashed=!0):this.start=e}return this.bytes>4294967295&&(this.hBytes+=this.bytes/4294967296<<0,this.bytes=this.bytes%4294967296),this}},t.prototype.finalize=function(){if(!this.finalized){this.finalized=!0;var t=this.blocks,i=this.lastByteIndex;t[16]=this.block,t[i>>>2]|=c[3&i],this.block=t[16],i>=56&&(this.hashed||this.hash(),t[0]=this.block,t[16]=t[1]=t[2]=t[3]=t[4]=t[5]=t[6]=t[7]=t[8]=t[9]=t[10]=t[11]=t[12]=t[13]=t[14]=t[15]=0),t[14]=this.hBytes<<3|this.bytes>>>29,t[15]=this.bytes<<3,this.hash()}},t.prototype.hash=function(){var t,i,h,r,s,e,n,o,a,f=this.h0,u=this.h1,c=this.h2,y=this.h3,l=this.h4,d=this.h5,A=this.h6,w=this.h7,b=this.blocks;for(t=16;t<64;++t)i=((s=b[t-15])>>>7|s<<25)^(s>>>18|s<<14)^s>>>3,h=((s=b[t-2])>>>17|s<<15)^(s>>>19|s<<13)^s>>>10,b[t]=b[t-16]+i+b[t-7]+h<<0;for(a=u&c,t=0;t<64;t+=4)this.first?(this.is224?(e=300032,w=(s=b[0]-1413257819)-150054599<<0,y=s+24177077<<0):(e=704751109,w=(s=b[0]-210244248)-1521486534<<0,y=s+143694565<<0),this.first=!1):(i=(f>>>2|f<<30)^(f>>>13|f<<19)^(f>>>22|f<<10),r=(e=f&u)^f&c^a,w=y+(s=w+(h=(l>>>6|l<<26)^(l>>>11|l<<21)^(l>>>25|l<<7))+(l&d^~l&A)+p[t]+b[t])<<0,y=s+(i+r)<<0),i=(y>>>2|y<<30)^(y>>>13|y<<19)^(y>>>22|y<<10),r=(n=y&f)^y&u^e,A=c+(s=A+(h=(w>>>6|w<<26)^(w>>>11|w<<21)^(w>>>25|w<<7))+(w&l^~w&d)+p[t+1]+b[t+1])<<0,i=((c=s+(i+r)<<0)>>>2|c<<30)^(c>>>13|c<<19)^(c>>>22|c<<10),r=(o=c&y)^c&f^n,d=u+(s=d+(h=(A>>>6|A<<26)^(A>>>11|A<<21)^(A>>>25|A<<7))+(A&w^~A&l)+p[t+2]+b[t+2])<<0,i=((u=s+(i+r)<<0)>>>2|u<<30)^(u>>>13|u<<19)^(u>>>22|u<<10),r=(a=u&c)^u&y^o,l=f+(s=l+(h=(d>>>6|d<<26)^(d>>>11|d<<21)^(d>>>25|d<<7))+(d&A^~d&w)+p[t+3]+b[t+3])<<0,f=s+(i+r)<<0,this.chromeBugWorkAround=!0;this.h0=this.h0+f<<0,this.h1=this.h1+u<<0,this.h2=this.h2+c<<0,this.h3=this.h3+y<<0,this.h4=this.h4+l<<0,this.h5=this.h5+d<<0,this.h6=this.h6+A<<0,this.h7=this.h7+w<<0},t.prototype.hex=function(){this.finalize();var t=this.h0,i=this.h1,h=this.h2,r=this.h3,s=this.h4,e=this.h5,n=this.h6,o=this.h7,a=u[t>>>28&15]+u[t>>>24&15]+u[t>>>20&15]+u[t>>>16&15]+u[t>>>12&15]+u[t>>>8&15]+u[t>>>4&15]+u[15&t]+u[i>>>28&15]+u[i>>>24&15]+u[i>>>20&15]+u[i>>>16&15]+u[i>>>12&15]+u[i>>>8&15]+u[i>>>4&15]+u[15&i]+u[h>>>28&15]+u[h>>>24&15]+u[h>>>20&15]+u[h>>>16&15]+u[h>>>12&15]+u[h>>>8&15]+u[h>>>4&15]+u[15&h]+u[r>>>28&15]+u[r>>>24&15]+u[r>>>20&15]+u[r>>>16&15]+u[r>>>12&15]+u[r>>>8&15]+u[r>>>4&15]+u[15&r]+u[s>>>28&15]+u[s>>>24&15]+u[s>>>20&15]+u[s>>>16&15]+u[s>>>12&15]+u[s>>>8&15]+u[s>>>4&15]+u[15&s]+u[e>>>28&15]+u[e>>>24&15]+u[e>>>20&15]+u[e>>>16&15]+u[e>>>12&15]+u[e>>>8&15]+u[e>>>4&15]+u[15&e]+u[n>>>28&15]+u[n>>>24&15]+u[n>>>20&15]+u[n>>>16&15]+u[n>>>12&15]+u[n>>>8&15]+u[n>>>4&15]+u[15&n];return this.is224||(a+=u[o>>>28&15]+u[o>>>24&15]+u[o>>>20&15]+u[o>>>16&15]+u[o>>>12&15]+u[o>>>8&15]+u[o>>>4&15]+u[15&o]),a},t.prototype.toString=t.prototype.hex,t.prototype.digest=function(){this.finalize();var t=this.h0,i=this.h1,h=this.h2,r=this.h3,s=this.h4,e=this.h5,n=this.h6,o=this.h7,a=[t>>>24&255,t>>>16&255,t>>>8&255,255&t,i>>>24&255,i>>>16&255,i>>>8&255,255&i,h>>>24&255,h>>>16&255,h>>>8&255,255&h,r>>>24&255,r>>>16&255,r>>>8&255,255&r,s>>>24&255,s>>>16&255,s>>>8&255,255&s,e>>>24&255,e>>>16&255,e>>>8&255,255&e,n>>>24&255,n>>>16&255,n>>>8&255,255&n];return this.is224||a.push(o>>>24&255,o>>>16&255,o>>>8&255,255&o),a},t.prototype.array=t.prototype.digest,t.prototype.arrayBuffer=function(){this.finalize();var t=new ArrayBuffer(this.is224?28:32),i=new DataView(t);return i.setUint32(0,this.h0),i.setUint32(4,this.h1),i.setUint32(8,this.h2),i.setUint32(12,this.h3),i.setUint32(16,this.h4),i.setUint32(20,this.h5),i.setUint32(24,this.h6),this.is224||i.setUint32(28,this.h7),t},(i.prototype=new t).finalize=function(){if(t.prototype.finalize.call(this),this.inner){this.inner=!1;var i=this.array();t.call(this,this.is224,this.sharedMemory),this.update(this.oKeyPad),this.update(i),t.prototype.finalize.call(this)}};var B=w();B.sha256=B,B.sha224=w(!0),B.sha256.hmac=v(),B.sha224.hmac=v(!0),o?module.exports=B:(s.sha256=B.sha256,s.sha224=B.sha224,a&&define(function(){return B}))}();
const personalRhStorage='jt-personal-rh-key';
let personalRhKey=sessionStorage.getItem(personalRhStorage)||localStorage.getItem(personalRhStorage)||'';
const directMediaCache=new WeakMap();
let directTransfers=0;const directWaiters=[];
function initPersonalUpload(){
  // Retired library identifiers are no longer used by this page.
  localStorage.removeItem('jt-media-library');
  const settings=document.createElement('details');settings.className='personal-upload';settings.id='personalUpload';
  settings.innerHTML='<summary>个人直传 <span></span></summary><p>填写与工作台生成账户相同的 API Key。</p><form><input type="password" aria-label="个人上传 API Key" placeholder="填写个人上传 API Key" autocomplete="off" spellcheck="false"><label><input type="checkbox">记住此浏览器（仅在自己的电脑勾选）</label><div><button type="submit">保存</button><button type="button" data-clear>清除</button></div><p class="personal-upload-note" role="status"></p></form>';
  document.querySelector('.pane-heading').after(settings);
  const input=settings.querySelector('input[type=password]'),remember=settings.querySelector('input[type=checkbox]'),note=settings.querySelector('.personal-upload-note');
  remember.checked=!!localStorage.getItem(personalRhStorage);
  const update=()=>{settings.querySelector('summary span').textContent=personalRhKey?'已设置':'未设置';input.value='';input.placeholder=personalRhKey?'已设置，填写可更换 Key':'填写个人上传 API Key'};
  settings.querySelector('form').onsubmit=e=>{e.preventDefault();const value=input.value.trim()||personalRhKey;if(!/^[A-Za-z0-9_-]{16,128}$/.test(value)){note.textContent='请填写有效的个人上传 API Key';return}personalRhKey=value;localStorage.removeItem(personalRhStorage);sessionStorage.removeItem(personalRhStorage);(remember.checked?localStorage:sessionStorage).setItem(personalRhStorage,value);note.textContent=remember.checked?'已保存到此浏览器，上传时自动校验账户':'已保存到当前标签页，关闭标签页后清除';update()};
  settings.querySelector('[data-clear]').onclick=()=>{personalRhKey='';localStorage.removeItem(personalRhStorage);sessionStorage.removeItem(personalRhStorage);note.textContent='个人 Key 已清除';update()};update();
}
function personalKeyRequired(){
  if(personalRhKey)return personalRhKey;
  const settings=document.getElementById('personalUpload');settings.open=true;settings.querySelector('input[type=password]').focus();
  throw new Error('请先在“个人直传”中填写并保存 Key，再点击继续上传');
}
function directUploadBinary(file,key,onProgress){return new Promise((resolve,reject)=>{
  const xhr=new XMLHttpRequest();xhr.open('POST','https://www.runninghub.ai/openapi/v2/media/upload/binary');xhr.timeout=180000;xhr.setRequestHeader('Authorization','Bearer '+key);
  xhr.upload.onprogress=e=>{if(e.lengthComputable)onProgress(Math.min(99,Math.floor(e.loaded/e.total*100)))};
  xhr.onerror=()=>reject(new Error('直传网络中断，请点击继续上传重试'));
  xhr.ontimeout=()=>reject(new Error('云端接收超时，请点击继续上传重试'));
  xhr.onload=()=>{let result={};try{result=JSON.parse(xhr.responseText)}catch{}
    if(xhr.status<200||xhr.status>=300||![0,200].includes(result.code)){const error=new Error([401,403].includes(xhr.status)?'云端服务拒绝此 Key，请检查账户或更换 Key':'云端暂未接收成功（'+String(result.code??xhr.status)+'），请重试');error.status=xhr.status;reject(error);return}
    const name=result.data?.filename||result.data?.fileName;if(typeof name!=='string'||!/^(api|openapi)\/[A-Za-z0-9._/-]+$/.test(name)||name.split('/').some(part=>!part||part==='.'||part==='..')){reject(new Error('云端未返回有效的文件标识'));return}onProgress(100);resolve(name)
  };
  const form=new FormData();form.append('file',file,file.name);xhr.send(form);
})}
async function sendDirectMediaFile(url,file,onProgress){
  const key=personalKeyRequired(),q=new URL(url,location.origin).searchParams;
  const post=(action,body)=>api('/api/upload-direct-'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(20000)});
  const {challenge}=await post('start',{workflow:q.get('workflow'),input_key:q.get('input_key'),filename:file.name,size:file.size});
  const proof=name=>globalThis.sha256.hmac(key,challenge+'\n'+name);
  await post('verify',{challenge,proof:proof('')});
  const fingerprint=globalThis.sha256(key);let cached=directMediaCache.get(file);
  if(!cached||cached.fingerprint!==fingerprint){
    const pending=(async()=>{
      if(directTransfers>=2)await new Promise(resolve=>directWaiters.push(resolve));else directTransfers++;
      try{return await directUploadBinary(file,key,onProgress)}finally{const next=directWaiters.shift();if(next)next();else directTransfers--}
    })();
    cached={fingerprint,pending};directMediaCache.set(file,cached);
    pending.catch(()=>{if(directMediaCache.get(file)===cached)directMediaCache.delete(file)});
  }
  const provider_name=await cached.pending;onProgress(100);
  // On a registration failure the provider result stays cached; retry never
  // uploads the same File again. Only this small signed receipt hits our server.
  return post('register',{challenge,proof:proof(provider_name),provider_name});
}
initPersonalUpload();

function publicMessage(value){return String(value||'').replace(/https?:\/\/[^\s]*runninghub[^\s]*/gi,'云端服务').replace(/runninghub/gi,'云端服务')}
const api=async(path,opt={})=>{const r=await fetch(path,opt);let d={};try{d=await r.json()}catch{}if(!r.ok){const error=new Error(publicMessage(d.error)||('HTTP '+r.status));error.data=d;error.status=r.status;throw error}return d};
let WFS=[],cur=null,genRunning=false,renderVersion=0;const pendingVideoSubmitKey='jt-pending-video-submit',mediaStateByWorkflow=new Map(),MAX_VIDEO_UPLOAD_BYTES=60*1024*1024;
function ensureMediaState(workflowId){if(!mediaStateByWorkflow.has(workflowId))mediaStateByWorkflow.set(workflowId,{tokens:{},names:{},uploadIds:{},previewUrls:{},files:{},uploading:{}});return mediaStateByWorkflow.get(workflowId)}
function selectVideoWorkflow(workflow){if(cur&&cur.id!==workflow.id)revokeWorkflowMediaPreviews(cur.id);cur=workflow;renderVersion++;renderForm();renderSwitch()}
async function recoverTasks(){return refreshVideoQueue()}
async function init(){const box=document.getElementById('wfSwitch'),form=document.getElementById('wfForm'),btn=document.getElementById('genBtn');box.innerHTML='<div class="config-loading">正在加载视频工作流…</div>';form.innerHTML='<div class="config-loading">加载完成后可设置提示词和素材</div>';btn.disabled=true;try{const a=await api('/api/workflows');WFS=a.filter(w=>w.kind==='video');if(!WFS.length)throw new Error('没有可用的视频工作流');box.replaceChildren();const grouped={};WFS.forEach(w=>(grouped[w.section||'其他']??=[]).push(w));Object.entries(grouped).forEach(([section,items])=>{const group=document.createElement('div'),heading=document.createElement('div');group.className='workflow-section';heading.className='workflow-section-title';heading.textContent=section;group.appendChild(heading);items.forEach(w=>{const b=document.createElement('button'),name=document.createElement('b');b.type='button';b.dataset.wf=w.id;name.textContent=w.name;b.appendChild(name);b.onclick=()=>selectVideoWorkflow(w);group.appendChild(b)});box.appendChild(group)});selectVideoWorkflow(WFS[0]);btn.disabled=false}catch(e){cur=null;box.innerHTML='<div class="config-error"><b>视频配置加载失败</b><span></span><button type="button">重新加载</button></div>';box.querySelector('span').textContent=e.message;box.querySelector('button').onclick=retryWorkflows;form.innerHTML='<div class="config-error"><span>请确认服务连接后重试，现有任务和素材不会被提交。</span></div>'}}function retryWorkflows(){init()}
function renderSwitch(){document.querySelectorAll('#wfSwitch button').forEach(b=>b.classList.toggle('active',b.dataset.wf===cur.id))}
function isVideoType(t){return t==='video'}
const videoThumbnails=new WeakMap();let thumbnailChain=Promise.resolve();
function prepareVideoThumbnail(file){
  if(typeof File==='undefined'||!(file instanceof File))return Promise.resolve(null);
  if(videoThumbnails.has(file))return videoThumbnails.get(file);
  const pending=thumbnailChain.then(()=>new Promise(resolve=>{
    const video=document.createElement('video'),url=URL.createObjectURL(file);let finished=false;
    const finish=value=>{if(finished)return;finished=true;clearTimeout(timer);video.onloadeddata=null;video.onerror=null;video.removeAttribute('src');video.load();URL.revokeObjectURL(url);resolve(value)};
    const timer=setTimeout(()=>finish(null),6000);video.muted=true;video.playsInline=true;video.preload='auto';
    video.onerror=()=>finish(null);video.onloadeddata=()=>{try{if(!video.videoWidth||!video.videoHeight)return finish(null);const canvas=document.createElement('canvas'),scale=Math.min(160/video.videoWidth,90/video.videoHeight,1);canvas.width=Math.max(1,Math.round(video.videoWidth*scale));canvas.height=Math.max(1,Math.round(video.videoHeight*scale));canvas.getContext('2d').drawImage(video,0,0,canvas.width,canvas.height);canvas.toBlob(blob=>{if(!blob||blob.size>32768)return finish(null);const reader=new FileReader();reader.onload=()=>finish(String(reader.result).split(',')[1]);reader.onerror=()=>finish(null);reader.readAsDataURL(blob)},'image/jpeg',.6)}catch{finish(null)}};video.src=url;
  })).catch(()=>null);videoThumbnails.set(file,pending);thumbnailChain=pending.then(()=>{});return pending;
}
function persistTaskThumbnails(jobId,files,workflow){
  for(const [key,file] of Object.entries(files))if(isVideoType(workflow.rh_media?.[key]?.type))prepareVideoThumbnail(file).then(async data=>{if(!data)return;try{await api('/api/video-thumbnail',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:jobId,key,data})});refreshVideoQueue()}catch{/* Optional preview never blocks a paid task. */}});
}
function pasteReferenceImage(event){
  if(!cur||document.body.closest('.page-host')?.hidden||document.getElementById('queueEditor'))return;
  const file=Array.from(event.clipboardData?.items||[]).find(item=>item.kind==='file'&&item.type.startsWith('image/'))?.getAsFile();if(!file)return;
  const drops=Array.from(document.querySelectorAll('.drop')).filter(drop=>!isVideoType(cur.rh_media?.[drop.dataset.mediaKey]?.type));
  const focused=document.activeElement?.closest?.('.drop');const target=drops.includes(focused)?focused:drops.length===1?drops[0]:null;
  if(!target){if(drops.length){event.preventDefault();document.getElementById('genStatus').textContent='有多个参考图位置，请先点击对应上传框的“粘贴到这里”再按 Ctrl＋V'}return}
  event.preventDefault();const key=target.dataset.mediaKey,m=cur.rh_media[key],ext={'image/png':'.png','image/jpeg':'.jpg','image/webp':'.webp'}[file.type];
  const named=ext&&!/\.(png|jpe?g|webp)$/i.test(file.name)?new File([file],'剪贴板-'+Date.now()+ext,{type:file.type}):file;
  uploadMedia(key,m,named,target,cur,renderVersion,ensureMediaState(cur.id));
}
function mediaAccept(type){return isVideoType(type)?'.mp4,.mov,.avi,.webm,.mkv,video/mp4,video/quicktime,video/x-msvideo,video/webm,video/x-matroska':'.png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp'}
function validateSelectedMedia(file,m){const suffix=(String(file?.name||'').match(/\.[^.]+$/)||[''])[0].toLowerCase(),allowed=isVideoType(m.type)?['.mp4','.mov','.avi','.webm','.mkv']:['.png','.jpg','.jpeg','.webp'];if(!allowed.includes(suffix))return isVideoType(m.type)?'请选择 MP4、MOV、WebM、AVI 或 MKV 视频':'请选择 JPG、PNG 或 WebP 图片；HEIC 请先导出为 JPG';if(!Number.isFinite(file.size)||file.size>MAX_VIDEO_UPLOAD_BYTES)return'文件超过60MB限制';if(file.size===0)return'文件为空，请重新选择';return''}
function revokeLocalMediaPreview(key,state){const value=state.previewUrls[key];if(value)URL.revokeObjectURL(value);delete state.previewUrls[key]}
function revokeWorkflowMediaPreviews(workflowId){const state=mediaStateByWorkflow.get(workflowId);if(!state)return;Object.keys(state.previewUrls).forEach(key=>revokeLocalMediaPreview(key,state))}
function replaceLocalMediaPreview(key,m,file,drop,state){revokeLocalMediaPreview(key,state);const existing=drop.querySelector('.local-media-preview');if(existing)drop.removeChild(existing);const media=document.createElement(isVideoType(m.type)?'video':'img');media.className='local-media-preview';media.src=URL.createObjectURL(file);state.previewUrls[key]=media.src;state.files[key]=file;const remove=drop.querySelector('.media-remove');if(remove)remove.hidden=false;if(isVideoType(m.type)){prepareVideoThumbnail(file);media.controls=true;media.playsInline=true;media.preload='metadata';detectSourceDuration(media,key,file,drop,state)}else media.alt='已选择的'+String(m.label||'图片');media.onerror=()=>{const note=drop.querySelector('.fn');if(note)note.textContent+=' · 当前浏览器无法预览此编码，可尝试 MP4/H.264 或 JPG'};drop.append(media)}
function detectSourceDuration(media,key,file,drop,state){
  if(cur?.id!=='h3_edit_n'||key!=='source_video')return;
  const workflow=cur,version=renderVersion,previous=state.durationSelection;
  if(previous?.file!==file)state.durationSelection={file,value:null,note:'正在读取视频时长…',manual:false};
  const selection=state.durationSelection;
  const active=()=>cur===workflow&&renderVersion===version&&state.files[key]===file&&state.durationSelection===selection;
  const show=()=>{if(!active())return;const input=document.getElementById('param_duration'),note=document.getElementById('durationAutoNote');if(input&&selection.value!==null)input.value=selection.value;if(note)note.textContent=selection.note};
  const failed=()=>{if(!active()||selection.manual)return;selection.note='无法读取视频时长，请手动填写';show()};
  const timer=setTimeout(failed,10000);
  media.addEventListener('loadedmetadata',()=>{clearTimeout(timer);if(!active()||selection.manual)return;const seconds=media.duration;if(!Number.isFinite(seconds)||seconds<=0){failed();return}const p=workflow.rh_params.duration,min=Number(p.min),max=p.max===undefined?Infinity:Number(p.max),step=Number(p.step)||1;const rounded=min+Math.round((seconds-min)/step)*step;selection.value=Math.max(min,Math.min(max,rounded));selection.note='检测到 '+seconds.toFixed(2)+' 秒，已填入 '+selection.value+' 秒'+(seconds<min?'（最短 '+min+' 秒）':seconds>max?'（最长 '+max+' 秒）':'（按整秒取近似值）')+'；可手动修改';show()},{once:true});
  media.addEventListener('error',()=>{clearTimeout(timer);failed()},{once:true});
}
function paramDefault(key,p){const selected=cur?.id==='h3_edit_n'&&key==='duration'?ensureMediaState(cur.id).durationSelection:null;return selected?.value??(Object.prototype.hasOwnProperty.call(p,'default')?p.default:(cur.params_defaults||{})[key])}
function optionValue(option){return typeof option==='object'?String(option.value??option.name??''):String(option)}
function optionLabel(option){const aliases={'minimax-n1':'dog','minimax-n2':'un','minimax-n3':'fig','minimax-n4':'v4','minimax-n5':'aio','minimax-n6':'hp'};return typeof option==='object'?String(option.label??option.name??option.value??''):(aliases[String(option)]??String(option))}
function renderForm(){const f=document.getElementById('wfForm'),workflow=cur,version=renderVersion,state=ensureMediaState(workflow.id);f.replaceChildren();const intro=document.createElement('div'),title=document.createElement('b'),desc=document.createElement('span');intro.className='note';title.textContent=workflow.name;desc.textContent=workflow.desc;intro.append(title,document.createElement('br'),desc);f.appendChild(intro);
  const media=Object.entries(workflow.rh_media||{});
  media.forEach(([key,m])=>{const lab=document.createElement('label');lab.textContent=m.label+(m.required?'（必传）':'（可选）');f.appendChild(lab);
    const drop=document.createElement('div'),copy=document.createElement('span'),fn=document.createElement('div'),inp=document.createElement('input');drop.className='drop';drop.tabIndex=0;drop.setAttribute('role','button');drop.setAttribute('aria-label','选择或拖入'+String(m.label||'素材'));drop.dataset.mediaKey=key;drop.dataset.mediaType=isVideoType(m.type)?'video':'image';copy.className='upload-heading';const icon=document.createElement('span'),formats=document.createElement('span');icon.className='upload-kind-icon';icon.setAttribute('aria-hidden','true');icon.textContent=isVideoType(m.type)?'▶':'▧';copy.textContent=isVideoType(m.type)?'上传'+String(m.label||'视频'):'上传'+String(m.label||'参考图');formats.className='upload-formats';formats.textContent=isVideoType(m.type)?'点击或拖入视频 · MP4 / MOV / WebM 等':'点击或拖入图片 · JPG / PNG / WebP';fn.className='fn';fn.setAttribute('aria-live','polite');inp.type='file';inp.hidden=true;inp.accept=mediaAccept(m.type);drop.append(icon,copy,formats,fn,inp);if(state.tokens[key]){drop.classList.add('has-file');fn.textContent='✓ '+state.names[key]+' 已上传'}const accept=file=>{if(!file)return;const error=validateSelectedMedia(file,m);if(error){fn.textContent='✗ '+error;return}uploadMedia(key,m,file,drop,workflow,version,state)};drop.onclick=event=>{if(event.target!==inp)inp.click()};drop.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();inp.click()}};drop.ondragover=event=>{event.preventDefault();drop.classList.add('is-dragging')};drop.ondragleave=()=>drop.classList.remove('is-dragging');drop.ondrop=event=>{event.preventDefault();drop.classList.remove('is-dragging');accept(event.dataTransfer?.files?.[0])};inp.onchange=()=>{accept(inp.files[0]);inp.value=''};
    if(state.files[key]){replaceLocalMediaPreview(key,m,state.files[key],drop,state);if(!state.tokens[key])fn.textContent=state.files[key].name+' · 尚未上传成功，请重新选择重试'}if(state.uploading[key])fn.textContent='上传中…';
    const trigger=document.createElement('button'),remove=document.createElement('button');trigger.type=remove.type='button';trigger.className='upload-trigger';trigger.append(icon,copy);drop.prepend(trigger);trigger.onclick=event=>{event.stopPropagation();inp.click()};remove.className='media-remove';remove.title='删除已选择素材';remove.setAttribute('aria-label','删除'+String(m.label||'素材'));remove.hidden=!state.files[key]&&!state.tokens[key];remove.onclick=event=>{event.stopPropagation();state.uploadIds[key]=(state.uploadIds[key]||0)+1;delete state.tokens[key];delete state.names[key];delete state.files[key];delete state.uploading[key];revokeLocalMediaPreview(key,state);drop.querySelector('.local-media-preview')?.remove();drop.querySelector('.upload-retry')?.remove();drop.classList.remove('has-file');fn.textContent='';remove.hidden=true;if(key==='source_video'){delete state.durationSelection;const note=document.getElementById('durationAutoNote');if(note)note.textContent='选择视频后自动读取时长，可手动修改'}};drop.append(remove);
    drop.onclick=event=>{if(event.target!==inp&&!event.target.closest('video,button'))inp.click()};drop.onkeydown=event=>{if(event.target===drop&&(event.key==='Enter'||event.key===' ')){event.preventDefault();inp.click()}};f.appendChild(drop)});
  const params=Object.entries(cur.rh_params||{});
  f.querySelectorAll('.drop').forEach(drop=>{if(isVideoType(workflow.rh_media[drop.dataset.mediaKey].type))return;const hint=document.createElement('button');hint.type='button';hint.className='paste-target';hint.textContent='粘贴到这里（Ctrl＋V）';hint.onclick=event=>{event.stopPropagation();drop.focus()};drop.append(hint)});
  params.filter(([,p])=>p.group!=='lora').forEach(([key,p])=>{const lab=document.createElement('label');lab.textContent=p.label+(p.required?'（必填）':'');f.appendChild(lab);let inp;
    if(p.type==='text'||p.type==='textarea'||key==='prompt'||key==='negative'){inp=document.createElement('textarea');if(cur.prompt_placeholder&&key==='prompt')inp.placeholder=cur.prompt_placeholder;if(key==='prompt'&&cur.prompt_hint){const h=document.createElement('div');h.className='note';h.style.color='#c26a4a';h.textContent=cur.prompt_hint;f.appendChild(h)}}
    else if(p.type==='boolean'){inp=document.createElement('input');inp.type='checkbox'}
    else if(p.type==='select'){inp=document.createElement('select');(p.options||[]).forEach(option=>{const item=document.createElement('option');item.value=optionValue(option);item.textContent=optionLabel(option);inp.appendChild(item)})}
    else{inp=document.createElement('input');inp.type=(p.type==='number'||p.type==='int'||p.vtype==='int'||p.vtype==='float')?'number':'text';if(p.min!==undefined)inp.min=p.min;if(p.max!==undefined)inp.max=p.max;if(p.step!==undefined)inp.step=p.step;else if(p.type==='int'||p.vtype==='int')inp.step='1'}
    inp.id='param_'+key;inp.dataset.paramType=p.vtype||p.type||'text';const d=paramDefault(key,p);if(d!==undefined){if(inp.type==='checkbox')inp.checked=d===true;else inp.value=d}f.appendChild(inp);if(workflow.id==='h3_edit_n'&&key==='duration'){const note=document.createElement('div');note.id='durationAutoNote';note.className='note';note.setAttribute('aria-live','polite');note.textContent=state.durationSelection?.note||'选择视频后自动读取时长，可手动修改';f.appendChild(note);inp.addEventListener('input',()=>{if(state.durationSelection){state.durationSelection.manual=true;state.durationSelection.value=inp.value;state.durationSelection.note='已手动设置时长';note.textContent=state.durationSelection.note}})}});
  const promptInput=f.querySelector('#param_prompt');if(promptInput)renderPromptPresets(f,promptInput,workflow.id);
  renderLoraSettings(f,params,state);
  (cur.fixed_features||[]).forEach(text=>{const note=document.createElement('div');note.className='note unavailable';note.textContent=text;f.appendChild(note)})}
function sendMediaFile(url,file,onProgress){return new Promise((resolve,reject)=>{const request=new XMLHttpRequest();request.open('POST',url);request.timeout=600000;request.setRequestHeader('Content-Type','application/octet-stream');request.upload.onprogress=event=>{if(event.lengthComputable)onProgress(Math.round(event.loaded/event.total*100))};request.onload=()=>{let data={};try{data=JSON.parse(request.responseText)}catch{}if(request.status>=200&&request.status<300&&data.uploadToken)resolve(data);else reject(new Error(data.error||'上传服务返回错误（'+request.status+'）'))};request.onerror=()=>reject(new Error('网络连接中断，请重新选择文件重试'));request.ontimeout=()=>reject(new Error('上传超时，请检查网络或压缩文件后重试'));request.send(file)})}
async function uploadMedia(key,m,file,drop,workflow,version,state){const fnEl=drop.querySelector('.fn'),error=validateSelectedMedia(file,m);if(error){fnEl.textContent='✗ '+error;return}const uploadId=(state.uploadIds[key]||0)+1;state.uploadIds[key]=uploadId;state.uploading[key]=true;drop.querySelector('.upload-retry')?.remove();delete state.tokens[key];delete state.names[key];replaceLocalMediaPreview(key,m,file,drop,state);fnEl.textContent='上传中…';drop.classList.remove('has-file');try{const query=new URLSearchParams({workflow:workflow.id,input_key:key,filename:file.name});const r=await sendResumableMediaFile('/api/upload?'+query,file,percent=>{if(state.uploadIds[key]!==uploadId)return;const activeDrop=currentMediaDrop(workflow.id,key,version,drop);if(activeDrop)activeDrop.querySelector('.fn').textContent=percent<100?'上传中 '+percent+'%':'文件已传完，云端接收中…'});if(state.uploadIds[key]!==uploadId)return;state.tokens[key]=r.uploadToken;state.names[key]=file.name;const activeDrop=currentMediaDrop(workflow.id,key,version,drop);if(activeDrop){activeDrop.classList.add('has-file');activeDrop.querySelector('.fn').textContent='✓ '+file.name+' 已上传'}}catch(e){if(state.uploadIds[key]!==uploadId)return;delete state.tokens[key];delete state.names[key];const activeDrop=currentMediaDrop(workflow.id,key,version,drop);if(activeDrop){activeDrop.classList.remove('has-file');activeDrop.querySelector('.fn').textContent='✗ 上传暂未完成：'+publicMessage(e.message);const retry=document.createElement('button');retry.type='button';retry.className='upload-retry';retry.textContent='继续上传';retry.onclick=event=>{event.stopPropagation();uploadMedia(key,m,file,activeDrop,workflow,renderVersion,state)};activeDrop.append(retry)}}finally{if(state.uploadIds[key]===uploadId)delete state.uploading[key]}}
function currentMediaDrop(workflowId,key,version,original){if(cur?.id!==workflowId)return null;if(version===renderVersion&&original.isConnected)return original;return Array.from(document.querySelectorAll('.drop')).find(item=>item.dataset.mediaKey===key)||null}
async function sendResumableMediaFile(url,file,onProgress){
  return sendDirectMediaFile(url,file,onProgress);
}
function readParamValue(el){if(el.type==='checkbox')return el.checked;if(el.value==='')return'';if(el.dataset.paramType==='int')return Number.parseInt(el.value,10);if(el.dataset.paramType==='float'||el.dataset.paramType==='number')return Number(el.value);return el.value}
function collectParams(){const p={};Object.keys(cur.rh_params||{}).forEach(k=>{const el=document.getElementById('param_'+k);if(el){if(cur.rh_params[k].group==='lora'&&!el.disabled&&!el.checkValidity()){const drawer=el.closest('details');if(drawer)drawer.open=true;el.reportValidity();throw new Error('请检查 '+cur.rh_params[k].label)}const value=readParamValue(el);if(value!=='')p[k]=value}});return p}
function safeMediaUrl(value){if(!value||!String(value).trim())return'';try{const u=new URL(String(value),location.origin);return ['http:','https:'].includes(u.protocol)&&!u.username&&!u.password?u.href:''}catch{return''}}
function hasRealSeed(j){const value=j?.params?.seed??j?.seed;return typeof value==='number'&&Number.isFinite(value)}
function seedSegment(j){const value=j?.params?.seed??j?.seed;return hasRealSeed(j)?('种子：'+value+' · '):''}
function resultMediaKind(im,url){const type=String(im.file_type||im.fileType||im.outputType||im.output_type||im.type||'').trim().toLowerCase().split(';')[0].replace(/^\./,''),path=new URL(url||location.origin).pathname;if(type==='application/zip'||type==='zip'||/\.zip$/i.test(path))return'file';if(type.startsWith('video/')||['video','mp4','mov','webm','avi','mkv'].includes(type)||/\.(mp4|mov|webm|avi|mkv)$/i.test(path))return'video';if(type.startsWith('image/')||['image','png','jpg','jpeg','webp','gif','avif'].includes(type)||/\.(png|jpe?g|webp|gif|avif)$/i.test(path))return'image';return'file'}
const galleryItems=[],clearedGalleryJobs=new Set(),clearedTaskJobs=new Set();let galleryIndex=-1;
function registerGalleryJob(j,select=true){if(!select&&(j.gallery_cleared||clearedGalleryJobs.has(j.id)))return;let added=false;(j.images||[]).forEach((im,i)=>{const key=j.id+':'+i;if(!galleryItems.some(x=>x.key===key)){galleryItems.push({key,j,im,i});added=true}});if(select){const index=galleryItems.findIndex(x=>x.j.id===j.id);if(index>=0)galleryIndex=index}else if(galleryIndex<0&&galleryItems.length)galleryIndex=0;if(galleryIndex>=0&&(select||added))renderMediaGallery()}
function removeGalleryJobs(ids){
  if(!ids.size)return;ids.forEach(id=>clearedGalleryJobs.add(id));hideGalleryHint();const selected=galleryItems[galleryIndex]?.key;
  for(let i=galleryItems.length-1;i>=0;i--)if(ids.has(galleryItems[i].j.id))galleryItems.splice(i,1);
  document.getElementById('galleryThumbs').replaceChildren();galleryIndex=galleryItems.findIndex(item=>item.key===selected);
  if(galleryItems.length){if(galleryIndex<0)galleryIndex=0;renderMediaGallery()}else{galleryIndex=-1;const main=document.getElementById('galleryMain');main.querySelectorAll('video').forEach(video=>{video.pause();video.removeAttribute('src');video.load()});main.replaceChildren();delete main.dataset.key;document.getElementById('mediaGallery').hidden=true;for(const t of tasks.values())t.card.classList.remove('is-selected')}
}
let videoClearBusy=false;
async function clearVideoView(scope,button){
  if(videoClearBusy)return;videoClearBusy=true;const controls=document.querySelectorAll('.video-clear');controls.forEach(el=>el.disabled=true);const label=button.textContent,status=document.getElementById('genStatus');button.textContent='清除中…';
  try{const result=await api('/api/video-clear',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scope}),signal:AbortSignal.timeout(20000)});if(!result.ok||!Array.isArray(result.cleared_ids))throw new Error('清除结果未确认');const ids=new Set(result.cleared_ids);removeGalleryJobs(ids);if(scope!=='gallery'){closeTaskDetails();ids.forEach(id=>{clearedTaskJobs.add(id);removeTaskCard(id)});historyVersion++;if(histOverlay.classList.contains('open'))await history()}await refreshVideoQueue();document.getElementById('videoEmpty').classList.toggle('hidden',tasks.size>0||galleryItems.length>0);status.textContent='已清除 '+ids.size+' 个'+({history:'历史任务',errors:'错误任务',gallery:'播放器列表任务'}[scope]);button.title=status.textContent}
  catch(e){status.textContent='清除失败：'+e.message;button.title=status.textContent}
  finally{videoClearBusy=false;button.textContent=label;controls.forEach(el=>el.disabled=false)}
}
function installVideoClearControls(){
  const make=(id,label,scope)=>{const button=document.createElement('button');button.id=id;button.type='button';button.className='video-clear';button.textContent=label;button.title=scope==='gallery'?'清空播放器列表，历史与收藏保留':'清除已结束的记录，正在生成和排队的任务保留';button.onclick=()=>clearVideoView(scope,button);return button};
  const header=document.querySelector('#histOverlay .library-header');header.insertBefore(make('clearVideoHistory','清除历史','history'),header.querySelector('.close'));
  document.querySelector('.task-panel-head').append(make('clearVideoErrors','清除错误','errors'));
  const toolbar=document.createElement('div');toolbar.className='gallery-list-tools';const label=document.createElement('span');label.textContent='播放列表';toolbar.append(label,make('clearVideoGallery','清空列表','gallery'));const thumbs=document.getElementById('galleryThumbs');thumbs.parentElement.insertBefore(toolbar,thumbs);
}
function selectGalleryItem(index){if(!galleryItems.length)return;galleryIndex=(index+galleryItems.length)%galleryItems.length;renderMediaGallery(true)}
// Keep the source thumbnail stable; a newly decoded result frame may be black.
function resultThumbnail(item){const url=safeMediaUrl(item.im.url);return resultMediaKind(item.im,url)==='image'?(safeMediaUrl(item.im.preview_url)||url):''}
function jobConfigurationText(job){
  const params=job?.params||job?.selection_snapshot?.params||{},lines=['提示词：'+(job?.prompt||params.prompt||'未记录')];
  let recorded=false;
  for(let slot=1;slot<=3;slot++){const model=params['lora_'+slot+'_model'],strength=params['lora_'+slot+'_strength'];if(model===undefined)continue;recorded=true;lines.push('LoRA '+slot+'：'+(model==='none'?'不加载':optionLabel(model)+(strength===undefined?' · 强度未记录':' · 强度 '+strength)+(strength===0?'（已关闭）':'')))}
  if(!recorded)lines.push('LoRA：此任务未记录配置');
  return lines.join('\n');
}
let galleryHint=null,galleryHintOwner=null,galleryHintTimer=null,galleryHintOpenTimer=null;
function hideGalleryHint(){clearTimeout(galleryHintOpenTimer);clearTimeout(galleryHintTimer);if(galleryHint)galleryHint.hidden=true;galleryHintOwner=null}
function deferGalleryHintHide(){clearTimeout(galleryHintOpenTimer);clearTimeout(galleryHintTimer);galleryHintTimer=setTimeout(()=>{if(!galleryHint?.matches(':hover')&&!galleryHint?.contains(document.activeElement)&&!galleryHintOwner?.matches(':hover'))hideGalleryHint()},300)}
function showGalleryHint(button,entry){
  clearTimeout(galleryHintOpenTimer);clearTimeout(galleryHintTimer);
  if(!galleryHint){galleryHint=document.createElement('div');galleryHint.id='galleryJobHint';galleryHint.className='gallery-job-hint';galleryHint.tabIndex=0;galleryHint.setAttribute('role','region');galleryHint.setAttribute('aria-label','视频提示词与 LoRA 详情');galleryHint.onpointerenter=()=>clearTimeout(galleryHintTimer);galleryHint.onpointerleave=deferGalleryHintHide;galleryHint.onfocus=()=>clearTimeout(galleryHintTimer);galleryHint.onblur=deferGalleryHintHide;galleryHint.onkeydown=e=>{if(e.key==='Escape'){hideGalleryHint();button.focus()}};document.body.append(galleryHint)}
  galleryHintOwner=button;galleryHint.textContent=jobConfigurationText({...tasks.get(entry.j.id)?.job,...entry.j});galleryHint.hidden=false;
  const rect=button.getBoundingClientRect(),height=galleryHint.offsetHeight;
  galleryHint.style.left=Math.max(8,Math.min(rect.left,window.innerWidth-galleryHint.offsetWidth-8))+'px';
  galleryHint.style.top=Math.max(8,rect.top>=height+16?rect.top-height-8:Math.min(rect.bottom+8,window.innerHeight-height-8))+'px';
  button.setAttribute('aria-describedby',galleryHint.id);
}
function renderGalleryThumbs(){
  const thumbs=document.getElementById('galleryThumbs');
  galleryItems.forEach((entry,index)=>{
    let b=thumbs.children[index];
    if(!b){b=document.createElement('button');b.type='button';b.onclick=()=>{hideGalleryHint();selectGalleryItem(index)};b.onpointerenter=e=>{if(e.pointerType==='touch')return;if(galleryHintOwner===b&&!galleryHint.hidden){clearTimeout(galleryHintTimer);return}hideGalleryHint();galleryHintOpenTimer=setTimeout(()=>{if(b.isConnected&&b.matches(':hover'))showGalleryHint(b,entry)},2000)};b.onpointerleave=deferGalleryHintHide;b.onfocus=()=>showGalleryHint(b,entry);b.onblur=deferGalleryHintHide;b.onkeydown=e=>{if(e.key==='Escape')hideGalleryHint()};thumbs.append(b)}
    b.className='gallery-thumb'+(index===galleryIndex?' active':'');
    const src=resultThumbnail(entry)||tasks.get(entry.j.id)?.sourceThumbnail||'',kind=resultMediaKind(entry.im,safeMediaUrl(entry.im.url)),signature=src+'|'+kind;
    if(b.dataset.preview!==signature){b.dataset.preview=signature;b.replaceChildren();if(src){const img=document.createElement('img');img.src=src;img.loading='lazy';img.decoding='async';img.alt=resultThumbnail(entry)?'生成结果':'原视频参考缩略图';b.append(img)}else{const span=document.createElement('span');span.textContent=kind==='video'?'▶':'▧';b.append(span)}}
    b.setAttribute('aria-label','播放结果 '+(index+1));b.setAttribute('aria-pressed',String(index===galleryIndex));
  });
  for(const id of ['galleryPrev','galleryNext'])document.getElementById(id).disabled=galleryItems.length<2;
}
function renderMediaGallery(autoplay=false){
  const main=document.getElementById('galleryMain');if(!main||galleryIndex<0)return;const item=galleryItems[galleryIndex];
  // Polling only appends thumbnails; keep the selected player and its playback position.
  if(main.dataset.key!==item.key){main.dataset.key=item.key;main.replaceChildren();const url=safeMediaUrl(item.im.url),kind=resultMediaKind(item.im,url),note=document.createElement('div');note.className='gallery-meta';note.textContent=seedSegment(item.j)+String(item.im.stage_label||item.im.file||'结果');main.append(note);
    const viewport=document.createElement('div');viewport.className='gallery-viewport';main.append(viewport);
    if(kind==='file'){const file=document.createElement('div');file.className='file-result';file.textContent='结果文件已生成，可直接下载';viewport.append(file)}else{const media=document.createElement(kind==='video'?'video':'img');if(kind==='video'){media.controls=true;media.playsInline=true;media.preload='metadata';}else media.alt='生成结果';media.src=kind==='video'?url:(safeMediaUrl(item.im.preview_url)||url);viewport.append(media)}
    const actions=document.createElement('div'),download=document.createElement('a'),favorite=document.createElement('button');actions.className='gallery-actions';download.className='dl';download.href=url;download.target='_blank';download.rel='noopener noreferrer';download.textContent='⬇ 下载原文件';favorite.className='dl';favorite.textContent='♥ 收藏';favorite.disabled=kind==='file';favorite.onclick=()=>saveGalleryFavorite(item,favorite);actions.append(favorite,download);main.append(actions);
  }renderGalleryThumbs();for(const t of tasks.values())t.card.classList.toggle('is-selected',t.job?.id===item.j.id);document.getElementById('mediaGallery').hidden=false;document.getElementById('videoEmpty').classList.add('hidden');
  if(autoplay){const player=main.querySelector('video');if(player)player.play().catch(()=>{if(main.contains(player)){player.muted=true;player.play().catch(()=>{})}})}
}
function addResult(j){registerGalleryJob(j)}
const tasks=new Map(); // job_id -> {card, timeEl, metaEl, spinEl, timer, startTs, wfName}
function closeTaskDetails(){for(const t of tasks.values()){t.clearDetailsTimers?.();if(t.info.matches(':popover-open'))t.info.hidePopover()}}
window.addEventListener('resize',closeTaskDetails);
window.addEventListener('resize',hideGalleryHint);
document.getElementById('galleryThumbs').addEventListener('scroll',hideGalleryHint,{passive:true});
document.querySelector('.preview-stage').addEventListener('scroll',hideGalleryHint,{passive:true});
document.querySelector('.preview-stage').addEventListener('scroll',()=>requestAnimationFrame(()=>{for(const t of tasks.values())if(t.info.matches(':popover-open'))t.positionDetails?.()}),{passive:true});
function fmtTime(s){s=Math.floor(s);const m=String(Math.floor(s/60)).padStart(2,'0'),ss=String(s%60).padStart(2,'0');return m+':'+ss}
function refreshTaskCount(){const n=tasks.size;document.getElementById('taskCount').textContent=n+' 个任务（最多2个并发）'}
function taskStatusText(j){const s=j.provider_status||j.status;if(j.status==='done')return '✓ 完成';if(j.status==='error')return '✗ 失败';if(s==='SUBMITTING')return '排队中…';if(s==='RUNNING')return '生成中…';return s||'处理中…'}
function videoCoinText(j){if(j.rh_coins!==null&&j.rh_coins!==undefined&&j.rh_coins!=='')return'RH币：'+String(j.rh_coins);return(j.status==='done'||j.status==='error')?'RH币：未返回':'RH币：统计中'}
function taskStatusClass(j){if(j.status==='done')return 'done';if(j.status==='error')return 'err';return ''}
function taskGroup(key){
  const list=document.getElementById('taskList');let group=list.querySelector('[data-group="'+key+'"]');if(group)return group;
  group=document.createElement(key==='done'?'details':'section');group.dataset.group=key;group.className='task-group';const heading=document.createElement(key==='done'?'summary':'h3'),grid=document.createElement('div');grid.className='task-grid';group.append(heading,grid);
  const next=key==='active'?list.querySelector('[data-group=done],[data-group=other]'):key==='done'?list.querySelector('[data-group=other]'):null;list.insertBefore(group,next);return group;
}
function addTaskCard(jobId,wfName){
  if(tasks.has(jobId))return tasks.get(jobId);const card=document.createElement('div'),tile=document.createElement('button'),thumb=document.createElement('span'),badge=document.createElement('span'),info=document.createElement('div'),name=document.createElement('div'),meta=document.createElement('div'),time=document.createElement('div'),view=document.createElement('button'),files=document.createElement('div'),actions=document.createElement('div');card.className='task-card';card.dataset.jobId=jobId;card.dataset.status='pending';tile.className='task-tile';tile.type='button';tile.setAttribute('aria-label',wfName+' · 同步队列中');thumb.className='task-picture';thumb.textContent='▧';badge.className='task-badge';badge.textContent='同步队列中';info.className='task-details';info.setAttribute('popover','auto');name.className='task-name';name.textContent=wfName;meta.className='task-meta';meta.textContent='已提交，正在同步任务状态';files.className='queue-files';actions.className='queue-actions';actions.hidden=true;time.className='task-time';view.className='task-view';view.type='button';view.textContent='播放结果';view.hidden=true;info.append(name,files,meta,time,actions,view);tile.append(thumb,badge);card.append(tile,info);const group=taskGroup('active');group.lastChild.append(card);group.hidden=false;group.firstChild.textContent='进行中 · '+group.lastChild.children.length;document.getElementById('videoEmpty').classList.add('hidden');const t={card,tile,thumb,badge,info,timeEl:time,metaEl:meta,viewEl:view,filesEl:files,actionsEl:actions,wfName,pendingSince:Date.now(),job:{id:jobId,status:'pending'}};tasks.set(jobId,t);
  let openTimer,closeTimer;
  const clearTimers=()=>{clearTimeout(openTimer);clearTimeout(closeTimer)},position=()=>{const rect=tile.getBoundingClientRect();info.style.left=Math.max(8,Math.min(rect.left,window.innerWidth-info.offsetWidth-8))+'px';const below=window.innerHeight-rect.bottom-14,above=rect.top-14,useBelow=below>=Math.min(info.scrollHeight+32,420)||below>=above;info.style.maxHeight=Math.max(80,useBelow?below:above)+'px';info.style.top=(useBelow?rect.bottom+6:Math.max(8,rect.top-info.offsetHeight-6))+'px'},show=()=>{clearTimers();if(!card.isConnected)return;if(!info.matches(':popover-open'))info.showPopover();position()},hide=()=>{clearTimers();closeTimer=setTimeout(()=>{if(!info.matches(':hover')&&!info.contains(document.activeElement)&&info.matches(':popover-open'))info.hidePopover()},180)};
  tile.onpointerenter=e=>{if(e.pointerType==='touch')return;clearTimers();if(info.matches(':popover-open'))position();else openTimer=setTimeout(()=>{if(tile.matches(':hover'))show()},2000)};tile.onpointerleave=hide;tile.onfocus=show;tile.onclick=()=>{show();if(t.job?.status==='done')view.click()};info.onpointerenter=clearTimers;info.onpointerleave=hide;info.onfocusout=hide;
  t.clearDetailsTimers=clearTimers;t.positionDetails=position;
  for(const [action,label] of [['top','置顶插队'],['up','上移'],['down','下移'],['edit','编辑参数']]){const b=document.createElement('button');b.type='button';b.textContent=label;b.dataset.action=action;b.onclick=()=>{info.hidePopover();return action==='edit'?openQueueEditor(t.job):queueAction(t.job,action)};actions.append(b)}
  const remove=document.createElement('button');remove.type='button';remove.className='task-remove';remove.hidden=true;remove.title='取消任务';remove.setAttribute('aria-label','取消任务');remove.onclick=event=>{event.stopPropagation();if(!t.job||t.busy||t.job.cancel_requested)return;clearTimers();info.hidePopover();queueAction(t.job,t.job.status==='queued'?'cancel':'cancel_running')};card.append(remove);t.removeEl=remove;
  const redo=document.createElement('button'),quickRedo=document.createElement('button');redo.type=quickRedo.type='button';redo.className='task-redo dl';redo.textContent='重做一次';quickRedo.className='task-redo-quick';quickRedo.textContent='↻';quickRedo.title='重做一次（复用素材与配置，更换随机种子）';quickRedo.setAttribute('aria-label','重做一次');redo.hidden=quickRedo.hidden=true;const repeat=event=>{event.stopPropagation();info.hidePopover();redoCompletedTask(t)};redo.onclick=quickRedo.onclick=repeat;info.append(redo);card.append(quickRedo);t.redoEl=redo;t.redoQuickEl=quickRedo;return t;
}
function updateTaskThumbnail(t){const entry=galleryItems.find(x=>x.j.id===t.job?.id),result=entry&&resultThumbnail(entry),src=result||t.sourceThumbnail||'',signature=src+'|'+t.job?.status;if(t.thumbSignature===signature)return;t.thumbSignature=signature;t.thumb.replaceChildren();if(src){const img=document.createElement('img');img.src=src;img.loading='lazy';img.decoding='async';img.alt=result?'生成结果缩略图':'原视频首帧';img.onerror=()=>img.remove();t.thumb.append(img);if(!result){const hint=document.createElement('small');hint.textContent='原视频';t.thumb.append(hint)}}else t.thumb.textContent=t.job?.status==='done'?'▶':'▧'}
const resultLoads=new Map();let resultLoadChain=Promise.resolve();
function loadCompletedTask(j){if(resultLoads.has(j.id))return resultLoads.get(j.id);const pending=resultLoadChain.then(async()=>{const full=await api('/api/job/'+encodeURIComponent(j.id),{signal:AbortSignal.timeout(20000)});if(!(full.images||[]).length)throw new Error('结果同步中');registerGalleryJob(full,false);const t=tasks.get(j.id);if(t)updateTaskThumbnail(t);return full}).catch(e=>{resultLoads.delete(j.id);const t=tasks.get(j.id);if(t)t.metaEl.textContent+=' · 结果同步中，将自动重试';return null});resultLoads.set(j.id,pending);resultLoadChain=pending.then(()=>{});return pending}
function groupTaskCards(rows){for(const [key,title,statuses] of [['active','进行中',['pending','queued','running','recovering']],['done','已完成',['done']],['other','未完成 · 失败 / 已取消',['error','cancelled']]]){const group=taskGroup(key),items=rows.filter(j=>key==='other'?!['pending','queued','running','recovering','done'].includes(j.status):statuses.includes(j.status));group.hidden=!items.length;group.firstChild.textContent=title+' · '+items.length;const grid=group.lastChild;items.forEach((j,index)=>{const card=tasks.get(j.id).card;if(grid.children[index]!==card)grid.insertBefore(card,grid.children[index]||null)})}if(rows.length)document.getElementById('videoEmpty').classList.add('hidden')}
function removeTaskCard(jobId){const t=tasks.get(jobId);if(!t)return;if(t.timer)clearInterval(t.timer);t.clearDetailsTimers?.();t.card.remove();tasks.delete(jobId);refreshTaskCount()}
function renderTaskResult(j){registerGalleryJob(j);renderMediaGallery(true);document.querySelector('.preview-stage').scrollTo({top:0,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'})}
async function pollTask(jobId){return refreshVideoQueue()}
let queueTimer=null,queueFetching=false,queueRefreshAgain=false;
async function refreshVideoQueue(){
  clearTimeout(queueTimer);if(queueFetching){queueRefreshAgain=true;return}queueFetching=true;
  try{const state=await api('/api/video-queue'),rows=(state.jobs||[]).filter(j=>!['done','error','cancelled'].includes(j.status)||(!j.task_cleared&&!clearedTaskJobs.has(j.id))),ids=new Set(rows.map(j=>j.id)),list=document.getElementById('taskList');
    for(const [id,t] of tasks)if(!ids.has(id)&&(!t.pendingSince||Date.now()-t.pendingSince>60000))removeTaskCard(id);
    removeGalleryJobs(new Set(rows.filter(j=>j.gallery_cleared&&!clearedGalleryJobs.has(j.id)).map(j=>j.id)));
    rows.forEach((j,index)=>{const t=addTaskCard(j.id,j.wf_name||'视频任务');delete t.pendingSince;t.job=j;
      if(!t.configEl){t.configEl=document.createElement('div');t.configEl.className='task-configuration';t.info.insertBefore(t.configEl,t.metaEl)}t.configEl.textContent=jobConfigurationText(j);
      const mediaSignature=JSON.stringify([j.media,j.thumbnails]);if(t.mediaSignature!==mediaSignature){t.mediaSignature=mediaSignature;t.sourceThumbnail=Object.values(j.thumbnails||{}).find(src=>typeof src==='string'&&src.startsWith('/api/video-thumbnail/'));t.filesEl.replaceChildren();for(const [key,name] of Object.entries(j.media||{})){const item=document.createElement('div'),w=WFS.find(w=>w.id===j.workflow);item.className='queue-media';item.textContent=(w?.rh_media?.[key]?.label||'素材')+'：'+name;t.filesEl.append(item)}if(!Object.keys(j.media||{}).length)t.filesEl.textContent='无需上传素材'}
      t.metaEl.textContent=j.queue_hold?'提交超时，未收到云端任务号；暂占 1 个名额，正在自动核对，不会重复提交':j.provider_status==='SUBMIT_UNCONFIRMED_IDLE'?'旧任务结果未知；已核对并释放名额，不影响后续排队，未自动重提':j.status==='queued'?'等待第 '+j.position+' 位 · 尚未提交上游':j.status==='cancelled'?'已取消排队 · 未提交上游':j.status==='error'?(j.provider_status==='QUEUE_EXPIRED'?'素材已过期，请重新上传':j.error||'任务失败'):taskStatusText(j)+' · '+videoCoinText(j);
      t.card.dataset.status=j.status;t.badge.textContent=j.queue_hold?'核对中 · 占位':j.provider_status==='SUBMIT_UNCONFIRMED_IDLE'?'结果未知 · 已释放':j.status==='queued'?'排队 · 第 '+j.position+' 位':j.status==='done'?'✓ 已完成':j.status==='cancelled'?'已取消':j.status==='error'?'✕ 失败':'◉ 生成中';t.tile.setAttribute('aria-label',t.wfName+' · '+t.badge.textContent+' · 任务详情');t.timeEl.textContent=j.elapsed?'用时 '+fmtTime(j.elapsed):'';t.actionsEl.hidden=!j.editable;t.viewEl.hidden=j.status!=='done';updateTaskThumbnail(t);
      if(j.status==='cancelled'&&j.cancel_confirmed)t.metaEl.textContent='云端已确认停止，已释放并发名额';
      if(j.cancel_requested&&j.cancellable){t.badge.textContent='取消中 · 核对停止';t.metaEl.textContent=j.cancel_note||'等待云端确认取消；确认前仍占用并发名额'}
      t.actionsEl.hidden=!j.editable&&!j.cancellable;
      t.removeEl.hidden=!j.editable&&!j.cancellable;t.removeEl.disabled=!!t.busy||!!j.cancel_requested;t.removeEl.title=j.cancel_requested?'正在取消':j.status==='queued'?'取消排队':'取消生成';t.removeEl.setAttribute('aria-label',t.removeEl.title);
      t.redoEl.hidden=t.redoQuickEl.hidden=j.status!=='done';t.redoEl.disabled=t.redoQuickEl.disabled=!!t.redoBusy;
      t.actionsEl.querySelectorAll('button').forEach(b=>{const cancel=b.dataset.action==='cancel_running';b.hidden=cancel?!j.cancellable:!j.editable;if(cancel)b.textContent=j.cancel_requested?'取消中…':'取消生成';b.disabled=t.busy||(cancel&&j.cancel_requested)||(['top','up'].includes(b.dataset.action)&&j.position===1)||(b.dataset.action==='down'&&j.position===state.waiting)});
      t.viewEl.onclick=async()=>{t.info.hidePopover();t.viewEl.disabled=true;try{const full=await loadCompletedTask(j);if(full)renderTaskResult(full)}finally{t.viewEl.disabled=false}};
      if(j.status==='done'&&!j.gallery_cleared&&!clearedGalleryJobs.has(j.id))loadCompletedTask(j);
    });groupTaskCards([...rows,...Array.from(tasks.values()).filter(t=>t.pendingSince).map(t=>t.job)]);document.getElementById('taskCount').textContent='执行 '+state.running+'/'+state.limit+' · 等待 '+state.waiting+'（最多2个并发）'+(state.draining?' · 维护中，暂缓启动':'');
  }catch(e){document.getElementById('taskCount').textContent='队列连接中断，自动重试：'+e.message}
  finally{queueFetching=false;queueTimer=setTimeout(refreshVideoQueue,queueRefreshAgain?0:document.hidden?15000:4000);queueRefreshAgain=false}
}
async function queueAction(job,action,extra={}){
  if(!job)return;const t=tasks.get(job.id);if(t?.busy)return;t.busy=true;t.actionsEl.querySelectorAll('button').forEach(b=>b.disabled=true);
  try{await api('/api/video-queue',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:job.id,revision:job.queue_revision,action,...extra})});return true}
  catch(e){document.getElementById('genStatus').textContent='队列操作失败：'+e.message;return false}
  finally{t.busy=false;await refreshVideoQueue()}
}
async function redoCompletedTask(t){
  if(t.redoBusy||t.job?.status!=='done')return;t.redoBusy=true;t.redoEl.disabled=t.redoQuickEl.disabled=true;
  const pendingKey='jt-pending-video-redo-'+t.job.id,status=document.getElementById('genStatus');let client_request_id=localStorage.getItem(pendingKey);if(!client_request_id){client_request_id='redo-'+Date.now()+'-'+Math.random().toString(36).slice(2);localStorage.setItem(pendingKey,client_request_id)}status.textContent='正在提交重做…';
  try{const result=await api('/api/video-generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({redo_job_id:t.job.id,client_request_id}),signal:AbortSignal.timeout(20000)});if(!result.job_id)throw new Error('提交结果未确认');localStorage.removeItem(pendingKey);status.textContent='✓ 已加入队列 · 重做任务 '+result.job_id;await refreshVideoQueue()}
  catch(e){const rejected=e.status>=400&&e.status<500;if(rejected)localStorage.removeItem(pendingKey);status.textContent='重做未完成：'+e.message+(rejected?'':'；再次点击会核对同一次提交')}
  finally{t.redoBusy=false;t.redoEl.disabled=t.redoQuickEl.disabled=false}
}
function openQueueEditor(job){
  if(!job?.editable||document.getElementById('queueEditor'))return;const w=WFS.find(w=>w.id===job.workflow);if(!w)return;
  const dialog=document.createElement('dialog'),form=document.createElement('form'),title=document.createElement('h3'),note=document.createElement('p'),actions=document.createElement('div'),save=document.createElement('button'),cancel=document.createElement('button'),fields=new Map();dialog.id='queueEditor';dialog.className='queue-editor';form.className='form';title.textContent='编辑等待任务';note.textContent='素材：'+(Object.values(job.media||{}).join('、')||'无')+'。保存前若任务已开始，会拒绝修改；更换素材请取消后重新提交。';form.append(title,note);
  for(const [key,p] of Object.entries(w.rh_params||{})){const label=document.createElement('label');label.textContent=p.label||key;let input;
    if(p.type==='select'){input=document.createElement('select');for(const option of p.options||[]){const el=document.createElement('option');el.value=optionValue(option);el.textContent=optionLabel(option);input.append(el)}}
    else if(p.type==='boolean'){input=document.createElement('input');input.type='checkbox'}
    else{input=document.createElement(['text','textarea'].includes(p.type)||['prompt','negative'].includes(key)?'textarea':'input');if(input.tagName==='INPUT'){input.type='text';input.inputMode='decimal'}}
    input.dataset.paramType=p.vtype||p.type||'text';input.name=key;if(input.type==='checkbox')input.checked=job.params?.[key]===true;else input.value=job.params?.[key]??p.default??'';label.append(input);form.append(label);fields.set(key,input);
  }
  save.type='submit';save.textContent='保存修改';cancel.type='button';cancel.textContent='返回';cancel.onclick=()=>dialog.close();actions.className='queue-actions';actions.append(save,cancel);form.append(actions);dialog.append(form);document.body.append(dialog);dialog.addEventListener('close',()=>dialog.remove(),{once:true});
  form.onsubmit=async e=>{e.preventDefault();save.disabled=true;const params={};for(const [key,input] of fields){if(input.type==='checkbox')params[key]=input.checked;else if(input.value!=='')params[key]=input.value}if(await queueAction(job,'edit',{params}))dialog.close();else{save.disabled=false;note.textContent='保存失败，原任务未被此操作修改。请关闭编辑窗，核对最新队列状态后重试。'}};dialog.showModal();
}
async function generate(){if(genRunning)return;if(!cur)return;const workflow=cur,state=ensureMediaState(workflow.id);if(Object.values(state.uploading).some(Boolean)){document.getElementById('genStatus').textContent='素材仍在上传，请完成后再生成';return}genRunning=true;const btn=document.getElementById('genBtn');btn.disabled=true;btn.classList.add('is-loading');const st=document.getElementById('genStatus');st.textContent='正在提交…';document.getElementById('genResult').innerHTML='';let pending={};try{pending=JSON.parse(localStorage.getItem(pendingVideoSubmitKey)||'{}')}catch{}const client_request_id=pending.workflow===workflow.id&&pending.id?pending.id:'video-'+Date.now()+'-'+Math.random().toString(36).slice(2);localStorage.setItem(pendingVideoSubmitKey,JSON.stringify({workflow:workflow.id,id:client_request_id}));try{const prompt=(document.getElementById('param_prompt')?.value||'').trim();if(!prompt)throw new Error('提示词不能为空');const required=Object.entries(workflow.rh_media||{}).filter(([,m])=>m.required).map(([k])=>k);const missing=required.filter(k=>!state.tokens[k]);if(missing.length)throw new Error('缺少必传素材：'+missing.join(', '));const submittedFiles={...state.files};const body={workflow:workflow.id,prompt:prompt,negative_prompt:(document.getElementById('param_negative')?.value||'').trim(),media:{...state.tokens},params:collectParams(),client_request_id};const r=await api('/api/video-generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});localStorage.removeItem(pendingVideoSubmitKey);if(!r.job_id)throw new Error(r.error||'提交失败');addTaskCard(r.job_id,workflow.name);persistTaskThumbnails(r.job_id,submittedFiles,workflow);st.textContent='✓ 已提交，任务 '+r.job_id+' 在下方队列中';pollTask(r.job_id)}catch(e){const definitiveRejection=e.status>=400&&e.status<500;if(definitiveRejection)localStorage.removeItem(pendingVideoSubmitKey);st.textContent='✗ '+e.message+(definitiveRejection?'':'；网络不明时再次点击会复用请求号')}finally{genRunning=false;btn.classList.remove('is-loading');btn.disabled=false}}
let historyVersion=0;
function sourceThumbnail(job){return safeMediaUrl(Object.values(job.thumbnails||{}).find(src=>typeof src==='string'&&src.startsWith('/api/video-thumbnail/')))}
function configurationDetails(job,className='favorite-details'){const details=document.createElement('details'),summary=document.createElement('summary'),text=document.createElement('div');details.className=className;summary.textContent='提示词与 LoRA 配置';text.className='library-configuration';text.textContent=jobConfigurationText(job);details.append(summary,text);if(className==='history-details'&&!job.params){let loaded=false;details.ontoggle=async()=>{if(!details.open||loaded)return;loaded=true;text.textContent='加载详情…';try{text.textContent=jobConfigurationText(await api('/api/job/'+encodeURIComponent(job.id)))}catch(e){loaded=false;text.textContent='详情读取失败：'+e.message}}}return details}
async function history(){
  const l=document.getElementById('histList'),version=++historyVersion;let cursor=null,busy=false,seen=new Set();l.replaceChildren();
  const more=document.createElement('button');more.className='dl';more.textContent='加载中…';l.append(more);
  const load=async()=>{if(busy)return;busy=true;more.disabled=true;more.textContent='加载中…';try{
    const query=new URLSearchParams({scope:'video',limit:'20'});if(cursor)query.set('before',JSON.stringify(cursor));
    const rows=await api('/api/jobs?'+query);if(version!==historyVersion)return;
    for(const j of rows){if(seen.has(j.id))continue;seen.add(j.id);const d=document.createElement('div'),title=document.createElement('b'),note=document.createElement('div'),button=document.createElement('button'),preview=document.createElement('div'),content=document.createElement('div'),filename=document.createElement('div');d.className='job history-card';preview.className='history-thumbnail';const src=sourceThumbnail(j);if(src){const img=document.createElement('img');img.src=src;img.loading='lazy';img.decoding='async';img.alt='原视频首帧';preview.append(img)}else preview.textContent='暂无首帧';content.className='history-summary';title.textContent=j.wf_name||WFS.find(w=>w.id===j.workflow)?.name||'视频';note.className='note';note.textContent=({done:'已完成',error:'失败',cancelled:'已取消',queued:'排队中',running:'生成中',recovering:'核对中'}[j.status]||j.status)+' · '+new Date(j.created*1000).toLocaleString()+' · '+videoCoinText(j);filename.className='note';filename.textContent=j.media?.source_video||Object.values(j.media||{}).join(' · ');button.className='dl';button.textContent='播放结果';button.disabled=j.status!=='done';button.onclick=async()=>{button.disabled=true;try{const full=await api('/api/job/'+encodeURIComponent(j.id));if(!(full.images||[]).length)throw new Error('暂无可播放结果');histOverlay.classList.remove('open');renderTaskResult(full)}catch(e){note.textContent='读取结果失败：'+e.message}finally{button.disabled=false}};content.append(title,note,filename,button);d.append(preview,content,configurationDetails(j,'history-details'));l.insertBefore(d,more)}
    if(rows.length){const last=rows[rows.length-1];cursor=[last.created,last.id]}
    more.hidden=rows.length<20;more.textContent='加载更早记录';
    if(!seen.size){const empty=document.createElement('p');empty.className='note';empty.textContent='当前浏览器会话暂无视频历史；更换浏览器或清除 Cookie 后不会显示原会话记录。';l.insertBefore(empty,more)}
  }catch(e){more.hidden=false;more.textContent='加载失败，点击重试：'+e.message}finally{busy=false;more.disabled=false}};more.onclick=load;await load();
}
async function saveGalleryFavorite(item,button){
  button.disabled=true;button.textContent='正在收藏…';
  try{const f=await api('/api/favorites',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:item.j.id,image_index:item.i}),signal:AbortSignal.timeout(20000)});button.textContent=f.archive_status==='saving'?'已加入收藏 · 后台保存中':'✓ 已收藏';if(f.archive_status==='saving')watchFavorite(f.id,button)}catch(e){button.disabled=false;button.textContent='收藏未确认，点击重试';button.title=e.message}
}
function watchFavorite(id,button){setTimeout(async()=>{if(!button.isConnected)return;try{const rows=await api('/api/favorites'),f=rows.find(x=>x.id===id);if(!f){button.disabled=false;button.textContent='请打开收藏核对';return}if(f.archive_status==='saving')return watchFavorite(id,button);button.textContent=f.archive_status==='error'?'保存失败，点击重试':'✓ 已收藏';button.disabled=f.archive_status!=='error';button.title=f.archive_error||''}catch{button.disabled=false;button.textContent='状态未确认，点击重试'}},4000)}
let favoriteTimer=null,favoriteVersion=0;
async function favorites(){
  clearTimeout(favoriteTimer);const l=document.getElementById('favList'),version=++favoriteVersion;if(!l.querySelector('.favorite-card'))l.textContent='加载中…';
  try{const rows=(await api('/api/favorites')).filter(f=>f.style_id==='video'||String(f.favorite_media_type||'').startsWith('video/'));if(version!==favoriteVersion)return;const existing=new Map(Array.from(l.querySelectorAll('.favorite-card')).map(d=>[d.dataset.favoriteId,d]));if(!existing.size)l.replaceChildren();
    for(const f of rows){let d=existing.get(f.id);existing.delete(f.id);if(!d){d=document.createElement('div');d.className='job favorite-card';d.dataset.favoriteId=f.id;const promptNode=document.createElement('div');promptNode.className='note favorite-prompt';promptNode.textContent=f.prompt||f.selection_snapshot?.params?.prompt||'视频收藏';const holder=document.createElement('div');holder.className='favorite-media';d.append(promptNode,holder,configurationDetails(f));l.append(d)}
      const holder=d.querySelector('.favorite-media'),signature=(f.archive_status||'ready')+'|'+f.image_url;
      if(holder.dataset.state===signature)continue;holder.dataset.state=signature;holder.replaceChildren();
      if(f.archive_status==='saving'||f.archive_status==='error'){const status=document.createElement('div');status.className='note';status.textContent=f.archive_status==='saving'?'后台保存中，完成后可播放和下载':publicMessage(f.archive_error)||'保存失败';holder.append(status);if(f.archive_status==='error'){const retry=document.createElement('button');retry.className='dl';retry.textContent='重试保存';retry.onclick=async()=>{await saveGalleryFavorite({j:{id:f.job_id},i:f.image_index},retry);favorites()};holder.append(retry)}}
      else{const isVideo=String(f.favorite_media_type||'').startsWith('video/'),media=document.createElement(isVideo?'video':'img');media.src=safeMediaUrl(f.image_url);if(isVideo){media.controls=true;media.playsInline=true;media.preload='metadata';const poster=sourceThumbnail(f);if(poster)media.poster=poster;const error=document.createElement('div'),retry=document.createElement('button');error.className='favorite-playback-error note';error.hidden=true;error.textContent='视频读取失败，请重试';retry.type='button';retry.className='dl';retry.textContent='重新加载视频';retry.onclick=()=>{error.hidden=true;media.load();media.play().catch(()=>{})};error.append(retry);media.onerror=()=>error.hidden=false;holder.append(media,error)}else{media.loading='lazy';holder.append(media)}const link=document.createElement('a');link.className='dl';link.href=safeMediaUrl(f.image_url);link.target='_blank';link.rel='noopener noreferrer';link.textContent='下载';holder.append(link)}
    }
    existing.forEach(d=>d.remove());if(!rows.length)l.textContent='当前浏览器会话暂无视频收藏';l.querySelector('.favorite-list-error')?.remove();
    if(rows.some(f=>f.archive_status==='saving'))favoriteTimer=setTimeout(()=>{if(favOverlay.classList.contains('open'))favorites()},5000);
  }catch(e){if(version!==favoriteVersion)return;let error=l.querySelector('.favorite-list-error');if(!error){if(!l.querySelector('.favorite-card'))l.replaceChildren();error=document.createElement('div');error.className='favorite-list-error note';l.append(error)}error.textContent='收藏加载失败：'+e.message;const retry=document.createElement('button');retry.className='dl';retry.textContent='重新加载';retry.onclick=favorites;error.append(retry)}
}
window.addEventListener('pagehide',()=>mediaStateByWorkflow.forEach((_,workflowId)=>revokeWorkflowMediaPreviews(workflowId)));window.addEventListener('paste',pasteReferenceImage);document.getElementById('genBtn').onclick=generate;document.getElementById('galleryPrev').onclick=()=>selectGalleryItem(galleryIndex-1);document.getElementById('galleryNext').onclick=()=>selectGalleryItem(galleryIndex+1);document.getElementById('histOpen').onclick=()=>{histOverlay.querySelector('.library-scroll').scrollTop=0;histOverlay.classList.add('open');history()};document.getElementById('favOpen').onclick=()=>{favOverlay.querySelector('.library-scroll').scrollTop=0;favOverlay.classList.add('open');favorites()};document.querySelectorAll('.library-overlay .close').forEach(b=>b.onclick=()=>b.closest('.library-overlay').classList.remove('open'));installVideoClearControls();init().then(()=>recoverTasks());
const CREATOR_ROUTES=['/','/realism','/video'];function scheduleRoutePrefetch(){}scheduleRoutePrefetch();
return {styleBoot:null};
}