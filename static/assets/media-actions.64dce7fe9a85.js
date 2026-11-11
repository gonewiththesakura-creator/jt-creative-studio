// Result actions for the creator's result stream.
// Everything goes through endpoints and controls that already exist:
// /api/favorites (POST, the same call the old result panel makes), the owner-only
// /api/job-prompt/<id>, and the edit/video pages' own image upload inputs.
import {accountFetch} from "/static/assets/api.39c989b27101.js";

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
