// Result actions for the creator's result stream.
// Everything goes through endpoints and controls that already exist:
// /api/favorites (POST, the same call the old result panel makes), the owner-only
// /api/job-prompt/<id>, and the edit/video pages' own image upload inputs.
import {accountFetch} from './api.js';

async function json(response, fallback) {
 let data = null; try { data = await response.json(); } catch {}
 if (!response.ok && response.status !== 202) throw Error(data?.error || fallback + '（' + response.status + '）');
 return data;
}

const prompts = new Map();
export async function fetchPrompt(jobId) {
 if (!jobId) return '';
 if (!prompts.has(jobId)) prompts.set(jobId, accountFetch('/api/job-prompt/' + encodeURIComponent(jobId))
  .then(response => json(response, '提示词读取失败')).then(data => String(data?.prompt || ''))
  .catch(error => { prompts.delete(jobId); throw error; }));
 return prompts.get(jobId);
}

export async function addFavorite(jobId, index) {
 return json(await accountFetch('/api/favorites', {method:'POST', headers:{'Content-Type':'application/json'},
  body:JSON.stringify({job_id:jobId, image_index:index})}), '收藏失败');
}

const TYPES = ['image/png', 'image/jpeg', 'image/webp'];
async function fileFrom(urls, name) {
 let lastError = null;
 for (const url of urls.filter(Boolean)) {
  try {
   const response = await accountFetch(url);
   if (!response.ok) throw Error('图片读取失败（' + response.status + '）');
   const blob = await response.blob();
   const type = TYPES.includes(blob.type) ? blob.type : 'image/png';
   if (!blob.size || blob.size > 30 * 1024 * 1024) throw Error('图片超过 30MB，无法直接送去编辑');
   return new File([blob], name + '.' + type.split('/')[1].replace('jpeg', 'jpg'), {type});
  } catch (error) { lastError = error; }
 }
 throw lastError || Error('没有可用的图片');
}

function visible(node) { return !!node && node.getClientRects().length > 0; }
// The first image slot the destination page currently shows, waiting for it to render.
async function imageInput(shadow, timeout = 6000) {
 const end = performance.now() + timeout;
 while (performance.now() < end) {
  const inputs = [...shadow.querySelectorAll('input[type=file]')].filter(input => {
   const drop = input.closest('.drop');
   if (drop?.dataset.mediaType === 'video') return false;
   if (drop?.dataset.mediaType !== 'image' && !/image/.test(input.accept || '')) return false;
   return visible(drop || input.parentElement) && !input.disabled;
  });
  if (inputs.length) return inputs[0];
  await new Promise(resolve => setTimeout(resolve, 150));
 }
 return null;
}

// Open the image-edit (/realism) or video (/video) page and hand the image to its
// first image slot, exactly as if the person had picked that file.
export async function sendImageTo(path, {url, preview, name = 'jt-result'}) {
 const file = await fileFrom([url, preview], name);
 const router = window.jtApp?.router;
 if (!router) throw Error('页面还没准备好');
 await router.navigate(path, {push:true});
 const page = router.pages.get(path);
 const input = page && await imageInput(page.shadow);
 if (!input) throw Error(path === '/video' ? '当前视频工作流不接收图片，请先切换到图生视频类工作流' : '当前编辑工作流没有图片输入');
 const transfer = new DataTransfer();
 transfer.items.add(file);
 input.files = transfer.files;
 input.dispatchEvent(new Event('change', {bubbles:true}));
 (input.closest('.drop') || input.parentElement)?.scrollIntoView({block:'center', behavior:'smooth'});
 return file;
}

// A small transient notice in the shell (outside page shadow roots).
export function toast(message, bad = false) {
 let node = document.getElementById('jtToast');
 if (!node) { node = document.createElement('div'); node.id = 'jtToast'; node.setAttribute('role', 'status'); document.body.append(node); }
 node.textContent = message; node.dataset.bad = bad ? '1' : ''; node.hidden = false;
 clearTimeout(node._timer); node._timer = setTimeout(() => { node.hidden = true; }, 3200);
}

// Shell lightbox (2026-11-12): a picture or a video opens above whatever page or library is on
// screen. A click on the backdrop or Escape closes it; a picture can go full screen. Pages inside
// shadow roots ask for it with a cancelable `jt:lightbox` window event carrying
// {items:[{kind:'image'|'video', src, full, label, jobId, index}], index}.
const LB_ICON = {
 heart:'<path d="M12 19.5s-7-4.3-7-9.3A3.9 3.9 0 0 1 12 8a3.9 3.9 0 0 1 7 2.2c0 5-7 9.3-7 9.3Z"/>',
 download:'<path d="M12 4v11M7.5 11 12 15.5 16.5 11M5 19.5h14"/>',
 expand:'<path d="M14 4.5h5.5V10M10 19.5H4.5V14M19.5 4.5 13.5 10.5M4.5 19.5l6-6"/>',
 x:'<path d="M6 6l12 12M18 6 6 18"/>',
};
const lbIcon = name => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${LB_ICON[name]}</svg>`;
let lightbox = null, lbItems = [], lbAt = 0, lbFocus = null;
function lbShow() {
 const item = lbItems[lbAt], stage = lightbox.querySelector('.lb-stage');
 stage.querySelector('video')?.pause();
 const media = document.createElement(item.kind === 'video' ? 'video' : 'img');
 if (item.kind === 'video') { media.controls = true; media.playsInline = true; media.autoplay = true; media.src = item.full || item.src; }
 else {
  media.alt = item.label || '作品'; media.src = item.src || item.full; media.title = '点击全屏';
  // The preview shows at once; the original replaces it when it has loaded.
  if (item.full && item.full !== media.src) { const original = new Image(); original.onload = () => { if (media.isConnected) media.src = item.full; }; original.src = item.full; }
 }
 stage.replaceChildren(media);
 lightbox.querySelector('.lb-note').textContent = [item.label, lbItems.length > 1 ? (lbAt + 1) + ' / ' + lbItems.length : ''].filter(Boolean).join(' · ');
 const download = lightbox.querySelector('[data-lb=download]'), fav = lightbox.querySelector('[data-lb=fav]');
 download.href = item.full || item.src;
 fav.hidden = !item.jobId; fav.disabled = false; fav.dataset.state = item.saved ? 'saved' : ''; fav.querySelector('span').textContent = item.saved ? '已收藏' : '收藏';
 lightbox.querySelectorAll('[data-lb=prev],[data-lb=next]').forEach(button => { button.hidden = lbItems.length < 2; });
}
export function closeLightbox() {
 if (!lightbox || lightbox.hidden) return;
 if (document.fullscreenElement === lightbox) document.exitFullscreen().catch(() => {});
 lightbox.querySelector('video')?.pause();
 lightbox.querySelector('.lb-stage').replaceChildren();
 lightbox.hidden = true;
 lbFocus?.focus?.(); lbFocus = null;
}
export function openLightbox({items = [], index = 0} = {}) {
 lbItems = items.filter(item => item && (item.src || item.full));
 if (!lbItems.length) return false;
 if (!lightbox) {
  lightbox = document.createElement('div');
  lightbox.id = 'jtLightbox'; lightbox.hidden = true; lightbox.tabIndex = -1;
  lightbox.setAttribute('role', 'dialog'); lightbox.setAttribute('aria-modal', 'true'); lightbox.setAttribute('aria-label', '查看作品');
  lightbox.innerHTML = `<p class="lb-note"></p><div class="lb-stage"></div>`
   + `<button type="button" class="lb-nav lb-prev" data-lb="prev" aria-label="上一个">‹</button><button type="button" class="lb-nav lb-next" data-lb="next" aria-label="下一个">›</button>`
   + `<div class="lb-bar"><button type="button" class="lb-btn" data-lb="fav">${lbIcon('heart')}<span>收藏</span></button>`
   + `<a class="lb-btn" data-lb="download" target="_blank" rel="noopener noreferrer" download>${lbIcon('download')}<span>下载原文件</span></a>`
   + `<button type="button" class="lb-btn" data-lb="full">${lbIcon('expand')}<span>全屏</span></button>`
   + `<button type="button" class="lb-btn" data-lb="close">${lbIcon('x')}<span>关闭</span></button></div>`;
  document.body.append(lightbox);
  const fullscreen = () => { if (document.fullscreenElement) document.exitFullscreen().catch(() => {}); else lightbox.requestFullscreen?.().catch(() => {}); };
  lightbox.addEventListener('click', event => {
   const action = event.target.closest('[data-lb]')?.dataset.lb;
   if (action === 'close') closeLightbox();
   else if (action === 'full') fullscreen();
   else if (action === 'prev' || action === 'next') { lbAt = (lbAt + (action === 'next' ? 1 : lbItems.length - 1)) % lbItems.length; lbShow(); }
   else if (action === 'fav') {
    const item = lbItems[lbAt], button = lightbox.querySelector('[data-lb=fav]');
    if (item.saved || button.disabled) return;
    button.disabled = true;
    addFavorite(item.jobId, item.index || 0).then(() => { item.saved = true; if (lbItems[lbAt] === item) { button.dataset.state = 'saved'; button.querySelector('span').textContent = '已收藏'; } toast('已收藏，可在「收藏」页查看'); },
     error => toast(error.message, true)).finally(() => { button.disabled = false; });
   }
   else if (action) return;
   else if (event.target.matches('.lb-stage img')) fullscreen();
   else if (!event.target.closest('video')) closeLightbox(); // the backdrop
  });
  // Capture on window: Escape closes the lightbox only, not the library underneath it.
  addEventListener('keydown', event => {
   if (lightbox.hidden) return;
   if (event.key === 'Escape') { event.preventDefault(); event.stopImmediatePropagation(); closeLightbox(); }
   else if (lbItems.length > 1 && (event.key === 'ArrowLeft' || event.key === 'ArrowRight')) {
    lbAt = (lbAt + (event.key === 'ArrowRight' ? 1 : lbItems.length - 1)) % lbItems.length; lbShow();
   }
  }, true);
  addEventListener('jt:route', closeLightbox);
 }
 lbAt = Math.max(0, Math.min(lbItems.length - 1, Number(index) || 0));
 lbFocus = document.activeElement?.shadowRoot?.activeElement || document.activeElement;
 lbShow();
 lightbox.hidden = false;
 lightbox.focus();
 return true;
}
addEventListener('jt:lightbox', event => { if (openLightbox(event.detail)) event.preventDefault(); });
