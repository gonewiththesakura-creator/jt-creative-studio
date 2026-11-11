// ACCRETION layout for the shell pages: the scene fills the window and the
// creation pane becomes a command dock at the bottom. Layout only. It moves a
// few existing nodes and adds chips that reveal existing sections; business
// code keeps its own elements, ids and handlers. Values change only through the
// same input/change events a person would fire, or a click on an existing button.
import {accountFetch} from './api.js';
import {addFavorite, fetchPrompt, sendImageTo, toast} from './media-actions.js';

const PATHS = {
 shuffle:'<path d="M4 7h3.2c4.3 0 5.3 10 9.6 10H20"/><path d="M4 17h3.2c1.6 0 2.7-1.4 3.6-3.2M13.2 10.2C14.1 8.4 15.2 7 16.8 7H20"/><path d="m17.5 4.5 2.5 2.5-2.5 2.5M17.5 14.5l2.5 2.5-2.5 2.5"/>',
 chevron:'<path d="m7 10 5 5 5-5"/>',
 sliders:'<path d="M5 7h9M18 7h1M5 17h3M12 17h7"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
 user:'<circle cx="12" cy="8.5" r="3.6"/><path d="M5 19.5c1.3-3.3 3.9-5 7-5s5.7 1.7 7 5"/>',
 layers:'<path d="m12 4 8 4-8 4-8-4 8-4Z"/><path d="m4 12 8 4 8-4M4 16l8 4 8-4"/>',
 bolt:'<path d="M13 3 5 13.5h6L10 21l8-10.5h-6L13 3Z"/>',
 cloud:'<path d="M7.5 18.5h9.2a3.8 3.8 0 0 0 .6-7.6 5.5 5.5 0 0 0-10.6-.9A4.3 4.3 0 0 0 7.5 18.5Z"/>',
 cpu:'<rect x="6.5" y="6.5" width="11" height="11" rx="2"/><path d="M10 3v3.5M14 3v3.5M10 17.5V21M14 17.5V21M3 10h3.5M3 14h3.5M17.5 10H21M17.5 14H21"/>',
 api:'<path d="M8 8 4 12l4 4M16 8l4 4-4 4M13.5 5l-3 14"/>',
 copy:'<rect x="8.5" y="8.5" width="11" height="11" rx="2.4"/><path d="M15.5 8.5V6.4A1.9 1.9 0 0 0 13.6 4.5H6.4a1.9 1.9 0 0 0-1.9 1.9v7.2a1.9 1.9 0 0 0 1.9 1.9h2.1"/>',
 import:'<path d="M12 4v10M8 10l4 4 4-4"/><path d="M5 15v3.5A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5V15"/>',
 x:'<path d="M6 6l12 12M18 6 6 18"/>',
 download:'<path d="M12 4v11M7.5 11 12 15.5 16.5 11M5 19.5h14"/>',
 refresh:'<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3L19.5 9"/><path d="M19.5 4.5V9H15"/>',
 alert:'<path d="M12 4 3 19.5h18L12 4Z"/><path d="M12 10v4.5M12 17v.2"/>',
 expand:'<path d="M14 4.5h5.5V10M10 19.5H4.5V14M19.5 4.5 13.5 10.5M4.5 19.5l6-6"/>',
 lock:'<rect x="5.5" y="10.5" width="13" height="9" rx="2"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/>',
 unlock:'<rect x="5.5" y="10.5" width="13" height="9" rx="2"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 6.8-1.2"/>',
 search:'<circle cx="11" cy="11" r="6"/><path d="m20 20-4.5-4.5"/>',
 image:'<rect x="4" y="5" width="16" height="14" rx="2.5"/><circle cx="9.5" cy="10" r="1.6"/><path d="m4.5 17 4.5-4.5 3.5 3.5 2.5-2.5 4.5 4.5"/>',
 heart:'<path d="M12 19.5s-7-4.3-7-9.3A3.9 3.9 0 0 1 12 8a3.9 3.9 0 0 1 7 2.2c0 5-7 9.3-7 9.3Z"/>',
 edit:'<path d="m4.5 19.5 4-1 10-10a2.1 2.1 0 0 0-3-3l-10 10-1 4Z"/><path d="m13.5 7 3 3"/>',
 video:'<rect x="3.5" y="6" width="12" height="12" rx="2.5"/><path d="m15.5 10.5 5-2.5v8l-5-2.5"/>',
 clock:'<circle cx="12" cy="12" r="8"/><path d="M12 7.5V12l3 2"/>',
};
const icon = name => `<svg class="acc-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${PATHS[name]}</svg>`;
const RATIOS = [['1:1',1024,1024],['3:4',896,1184],['2:3',832,1248],['9:16',768,1360],['16:9',1360,768]];
const ENGINES = [['cloud','云端','ComfyUI 云端工作站，适合批量出图','cloud'],['local','本地','本机 ComfyUI，不占云端排队','cpu'],['api','API','GPT Image，每次 1 张','api']];
const ENGINE_NAME = Object.fromEntries(ENGINES.map(([key, name]) => [key, name]));
const ENGINE_ICON = Object.fromEntries(ENGINES.map(([key,,, ic]) => [key, ic]));
const FINISHED = new Set(['done', 'completed', 'success', 'error', 'failed', 'cancelled', 'canceled']);

function el(tag, className, html) {
 const node = document.createElement(tag);
 if (className) node.className = className;
 if (html !== undefined) node.innerHTML = html;
 return node;
}
function fire(input, value) {
 input.value = String(value);
 input.dispatchEvent(new Event('input', {bubbles:true}));
 input.dispatchEvent(new Event('change', {bubbles:true}));
}
// Observers below watch the dock; writing an unchanged value would re-trigger them forever.
function text(node, value) { if (node.textContent !== value) node.textContent = value; }
function attr(node, name, value) { if (node.getAttribute(name) !== value) node.setAttribute(name, value); }
function html(node, value) { if (node._accHtml !== value) { node._accHtml = value; node.innerHTML = value; } }
function remember(key, value) { try { if (value === undefined) return localStorage.getItem(key); localStorage.setItem(key, value); } catch { return null; } }
const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));

// The dock grows upward to show one group at a time. Escape closes it; so does
// a click outside the dock unless the page keeps its panel open while working.
function dock(root, pane, {initial = '', onChange = () => {}, closeOnOutside = true} = {}) {
 const set = group => { pane.dataset.accOpen = group || ''; root.querySelectorAll('.acc-chip[data-group]').forEach(chip => chip.setAttribute('aria-expanded', String(chip.dataset.group === group))); onChange(group); };
 set(initial);
 if (closeOnOutside) root.addEventListener('pointerdown', event => { if (pane.dataset.accOpen && !event.composedPath().includes(pane) && !event.target.closest?.('.api-popover')) set(''); });
 root.addEventListener('keydown', event => { if (event.key === 'Escape' && pane.dataset.accOpen) { const chip = root.querySelector(`.acc-chip[data-group="${pane.dataset.accOpen}"]`); set(''); chip?.focus(); } });
 return {set, toggle: group => set(pane.dataset.accOpen === group ? '' : group)};
}
// Results and hero sit between the shell topbar and the closed dock; both heights change with width.
function measure(body, pane) {
 const topbar = document.querySelector('body > .app-shell > .shell-top'), footer = pane.querySelector('.creation-footer');
 const update = () => {
  if (!footer.offsetHeight) return;
  body.style.setProperty('--acc-top', (topbar?.offsetHeight || 56) + 'px');
  body.style.setProperty('--acc-dock', Math.round(footer.offsetHeight + (innerWidth <= 760 ? 8 : 24)) + 'px');
 };
 const observer = new ResizeObserver(update);
 observer.observe(footer);
 if (topbar) observer.observe(topbar);
 update();
}
function chip(group, markup, label) {
 const button = el('button', 'acc-chip', markup);
 button.type = 'button';
 if (group) { button.dataset.group = group; button.setAttribute('aria-expanded', 'false'); }
 if (label) button.setAttribute('aria-label', label);
 return button;
}
function iconButton(name, label, onclick) {
 const button = el('button', 'acc-icon-button', icon(name));
 button.type = 'button'; button.title = label; button.setAttribute('aria-label', label);
 if (onclick) button.onclick = onclick;
 return button;
}
// The page draws one preview per style; style cards reuse the shipped preview thumbnails.
const styleThumb = id => `/static/previews/style-${String(id).replace(/_/g, '-')}.thumb.webp`;
const backendOf = job => { const value = String(job.generation_backend || '').toLowerCase(); return value.includes('api') ? 'api' : value.includes('local') ? 'local' : 'cloud'; };
const createdMs = job => { const value = Number(job.created) || 0; return value > 1e12 ? value : value * 1000; };
function clock(ms) {
 if (!ms) return '';
 const date = new Date(ms), now = new Date(), pad = n => String(n).padStart(2, '0');
 const time = pad(date.getHours()) + ':' + pad(date.getMinutes());
 return date.toDateString() === now.toDateString() ? '今天 ' + time : (date.getMonth() + 1) + '月' + date.getDate() + '日 ' + time;
}

function creator(root, body) {
 const $ = id => root.getElementById(id);
 const pane = root.querySelector('.creation-pane'), scroll = pane.querySelector('.creation-scroll'), footer = pane.querySelector('.creation-footer');
 body.classList.add('acc', 'acc-creator');
 // Tag the existing sections so the dock can reveal one group at a time.
 const groupOf = {styleSwitch:'style', coldVariantSwitch:'style', modeSwitch:'person', drawers:'person'};
 let current = 'meta';
 for (const node of [...scroll.children]) {
  if (node.classList.contains('section-label')) current = {画风:'style', 人物模式:'person', 提示词:'prompt', 生成参数:'params'}[node.textContent.trim()] || current;
  const group = groupOf[node.id] || (node.classList.contains('actions') ? 'person' : node.classList.contains('pane-heading') ? 'meta' : current);
  node.dataset.accGroup = group;
 }
 // Every group opens as a sheet with its own title row.
 const heads = {};
 const sheetHead = (group, title, note = '') => {
  const head = el('div', 'acc-sheet-head', `<h3>${title}</h3>${note ? `<span class="acc-sheet-note">${note}</span>` : ''}<span class="acc-grow"></span>`);
  head.dataset.accGroup = group;
  head.append(iconButton('x', '关闭', () => controls.set('')));
  heads[group] = head;
  return head;
 };
 const styleHead = sheetHead('style', '画风');
 styleHead.querySelector('h3').after($('coldVariantSwitch'));
 const personHead = sheetHead('person', '人物设定');
 personHead.querySelector('h3').after($('modeSwitch'));
 const actions = scroll.querySelector('.actions');
 const done = el('button', 'acc-done', '完成'); done.type = 'button'; done.onclick = () => controls.set('');
 personHead.querySelector('.acc-close, .acc-icon-button').replaceWith(actions, done);
 sheetHead('size', '画面尺寸', '<span class="acc-size-note"></span>');
 sheetHead('engine', '生成通道', '结果按通道分开归档，可在右上角筛选');
 sheetHead('params', '生成参数');
 scroll.prepend(...Object.values(heads));

 // Style: the switch becomes a card grid; thumbnails load the first time the sheet opens.
 const styleSwitch = $('styleSwitch');
 for (const button of styleSwitch.querySelectorAll('button[data-style]')) {
  if (button.querySelector('.acc-style-art')) continue;
  const name = button.textContent.trim();
  button.textContent = '';
  const art = el('img', 'acc-style-art'); art.alt = ''; art.decoding = 'async'; art.dataset.src = styleThumb(button.dataset.style);
  art.onerror = () => { art.hidden = true; };
  const label = el('span', 'acc-style-name'); label.textContent = name;
  button.append(art, label);
 }
 const loadStyleArt = () => styleSwitch.querySelectorAll('img[data-src]').forEach(img => { img.src = img.dataset.src; img.removeAttribute('data-src'); });

 // Person: a three-column picker drawn from the page's own drawers. The drawers re-render on every
 // change, so the picker never holds them; it reads them and drives their selects, locks and rerolls.
 const person = el('div', 'acc-person');
 person.dataset.accGroup = 'person';
 person.innerHTML = `<div class="acc-p-col acc-p-secs"></div><div class="acc-p-col acc-p-fields"></div><div class="acc-p-col acc-p-optcol"><label class="acc-p-search">${icon('search')}<input type="search" autocomplete="off" aria-label="搜索选项"></label><div class="acc-p-opts"></div></div>`;
 $('drawers').before(person);
 const search = person.querySelector('input');
 let section = 0, fieldIndex = -1, filter = '';
 const isNone = option => option.value === '0' || option.value === '' || /^无（/.test(option.textContent.trim());
 function sections() {
  return [...root.querySelectorAll('#drawers > .drawer')].map(drawer => ({
   name: drawer.querySelector('.drawer-head span')?.textContent.trim() || '',
   items: [...drawer.querySelectorAll('.item')].map(item => {
    const select = item.querySelector('select.picker');
    if (!select) return null;
    const chosen = [...select.selectedOptions].filter(option => !isNone(option));
    return {item, select, name: item.querySelector('.item-name')?.textContent.trim() || select.getAttribute('aria-label') || '',
     chosen, value: chosen.map(option => option.textContent.trim()).join('、'),
     locked: /🔒/.test(item.querySelector('.lock')?.textContent || ''), off: select.disabled || item.hidden};
   }).filter(entry => entry && !entry.off),
  })).filter(group => group.items.length);
 }
 function choose(field, value) {
  const {select} = field;
  if (!select.multiple) { fire(select, value); return; }
  const options = [...select.options];
  if (value === '0' || value === '') options.forEach(option => { option.selected = isNone(option); });
  else {
   const target = options.find(option => option.value === value);
   if (target) target.selected = !target.selected;
   const any = options.some(option => option.selected && !isNone(option));
   options.forEach(option => { if (isNone(option)) option.selected = !any; });
  }
  select.dispatchEvent(new Event('input', {bubbles:true}));
  select.dispatchEvent(new Event('change', {bubbles:true}));
 }
 function renderPerson(groups = sections()) {
  if (!groups.length) return;
  section = Math.min(section, groups.length - 1);
  const items = groups[section].items;
  if (fieldIndex < 0 || fieldIndex >= items.length) fieldIndex = 0;
  const field = items[fieldIndex];
  html(person.children[0], groups.map((group, i) => {
   const count = group.items.filter(entry => entry.chosen.length).length;
   return `<button type="button" class="acc-p-sec${i === section ? ' on' : ''}" data-sec="${i}">${esc(group.name)}${count ? `<i class="acc-badge">${count}</i>` : ''}</button>`;
  }).join(''));
  html(person.children[1], items.map((entry, i) => `<div class="acc-p-field${i === fieldIndex ? ' on' : ''}" data-field="${i}" role="button" tabindex="0"><div><small>${esc(entry.name)}</small><b class="${entry.chosen.length ? 'set' : ''}" title="${esc(entry.value)}">${esc(entry.value || '未选择')}</b></div>`
   + `<button type="button" class="acc-lk${entry.locked ? ' on' : ''}" data-lock="${i}" title="${entry.locked ? '已锁定，随机时保留' : '锁定后随机不会改动'}">${icon(entry.locked ? 'lock' : 'unlock')}</button>`
   + `<button type="button" class="acc-lk" data-reroll="${i}" title="随机这一项">${icon('refresh')}</button></div>`).join(''));
  const options = [...field.select.options].filter(option => !isNone(option));
  attr(search, 'placeholder', `搜索「${field.name}」，共 ${options.length} 项`);
  const needle = filter.trim().toLowerCase();
  const box = person.querySelector('.acc-p-opts'), top = box.scrollTop;
  html(box, `<button type="button" class="acc-p-opt${field.chosen.length ? '' : ' on'}" data-opt="0">不添加</button>`
   + options.filter(option => !needle || option.textContent.toLowerCase().includes(needle))
     .map(option => `<button type="button" class="acc-p-opt${option.selected ? ' on' : ''}" data-opt="${esc(option.value)}">${esc(option.textContent.trim())}</button>`).join(''));
  box.scrollTop = top;
 }
 person.addEventListener('click', event => {
  const target = event.target.closest('[data-sec],[data-lock],[data-reroll],[data-opt],[data-field]');
  if (!target) return;
  const groups = sections(), items = groups[section]?.items || [];
  if (target.dataset.sec !== undefined) { section = Number(target.dataset.sec); fieldIndex = 0; filter = search.value = ''; }
  else if (target.dataset.lock !== undefined) items[Number(target.dataset.lock)]?.item.querySelector('.lock')?.click();
  else if (target.dataset.reroll !== undefined) items[Number(target.dataset.reroll)]?.item.querySelector('.reroll')?.click();
  else if (target.dataset.opt !== undefined) { const field = items[fieldIndex]; if (field) choose(field, target.dataset.opt); }
  else if (target.dataset.field !== undefined) { fieldIndex = Number(target.dataset.field); filter = search.value = ''; }
  requestAnimationFrame(() => renderPerson());
 });
 person.addEventListener('keydown', event => { if ((event.key === 'Enter' || event.key === ' ') && event.target.matches('.acc-p-field')) { event.preventDefault(); event.target.click(); } });
 search.addEventListener('input', () => { filter = search.value; renderPerson(); });

 // Size and count get their own groups; their labels keep the original inputs.
 const settings = scroll.querySelector('.settings');
 const sizeBox = el('section', 'acc-size settings'), countBox = el('section', 'acc-count');
 sizeBox.dataset.accGroup = 'size'; countBox.dataset.accGroup = 'count';
 const ratioRow = el('div', 'acc-tiles acc-ratios');
 const ratioIcon = (w, h) => { const r = w / h, iw = r >= 1 ? 30 : Math.round(30 * r), ih = r >= 1 ? Math.round(30 / r) : 30; return `<span class="acc-ratio-box"><i style="width:${iw}px;height:${ih}px"></i></span>`; };
 for (const [name, width, height] of RATIOS) {
  const option = el('button', 'acc-tile', `${ratioIcon(width, height)}<b>${name}</b><small>${width}×${height}</small>`);
  option.type = 'button'; option.dataset.w = width; option.dataset.h = height;
  option.onclick = () => { sizeBox.dataset.custom = ''; fire($('genW'), width); fire($('genH'), height); refresh(); };
  ratioRow.append(option);
 }
 const customTile = el('button', 'acc-tile acc-custom-tile', `${ratioIcon(4, 5)}<b>自定义</b><small class="acc-custom-dims"></small>`);
 customTile.type = 'button'; customTile.onclick = () => { sizeBox.dataset.custom = '1'; refresh(); };
 ratioRow.append(customTile);
 // API: the popover's own ratio radios, shown as tiles.
 const apiRatios = [...root.querySelectorAll('input[name=apiRatio]')];
 const apiRow = el('div', 'acc-tiles acc-api-ratios');
 for (const radio of apiRatios) {
  const [w, h] = radio.value.split(':').map(Number);
  const option = el('button', 'acc-tile', `${ratioIcon(w || 1, h || 1)}<b>${esc(radio.value)}</b>`);
  option.type = 'button'; option.dataset.ratio = radio.value;
  option.onclick = () => { radio.checked = true; radio.dispatchEvent(new Event('input', {bubbles:true})); radio.dispatchEvent(new Event('change', {bubbles:true})); refresh(); };
  apiRow.append(option);
 }
 const customRow = el('div', 'acc-custom');
 customRow.append($('genW').closest('label'), $('genH').closest('label'));
 sizeBox.append(ratioRow, apiRow, customRow);
 countBox.append($('genBatch').closest('label'));
 settings.dataset.accGroup = 'params';
 settings.before(sizeBox, countBox);
 // Manual negative prompt lives with the other parameters, as in the prototype.
 const negative = $('manualNegative'), negativeBox = el('section', 'acc-negative prompt');
 negativeBox.dataset.accGroup = 'params';
 negativeBox.append(negative.previousElementSibling, negative);
 settings.before(negativeBox);

 // Composer head: mode switch, import-to-manual, copy and shuffle.
 const cHead = el('div', 'acc-c-head');
 const importButton = $('importGeneratedPrompt');
 // The result panels are hidden; their status lines (progress, submit errors) show here instead.
 const status = el('span', 'acc-status');
 status.setAttribute('role', 'status');
 cHead.append($('promptModePanel'), importButton, status,
  iconButton('copy', '复制当前提示词', () => $('copyPrompt').click()),
  iconButton('shuffle', '随机一组选项', () => $('randomAll').click()));
 if (!importButton.querySelector('.acc-ic')) importButton.insertAdjacentHTML('afterbegin', icon('import'));
 $('promptText').readOnly = true;
 // Composer body: the chosen options as removable tokens, or the manual prompt.
 const cBody = el('div', 'acc-c-body');
 const tokens = el('div', 'acc-tokens');
 cBody.append(tokens, $('manualPromptPanel'), $('promptPanel'));
 tokens.addEventListener('click', event => {
  const button = event.target.closest('[data-clear]');
  if (!button) return;
  const [s, i] = button.dataset.clear.split(':').map(Number);
  const field = sections()[s]?.items[i];
  if (field) choose(field, '0');
 });
 // Composer foot: style, person, size, count, channel, params, then launch.
 const chips = el('div', 'acc-chips');
 const styleChip = chip('style', '<img class="acc-chip-art" alt=""><span class="acc-style-label"></span>' + icon('chevron'), '画风');
 const personChip = chip('person', icon('user') + '<span class="acc-person-label"></span><small class="acc-person-count"></small>', '人物与选项');
 const sizeChip = chip('size', '<i class="acc-ratio"></i><span class="acc-size-name"></span><small class="acc-size-text acc-mono"></small>', '画面尺寸');
 const stepper = el('div', 'acc-stepper', '<button type="button" data-step="-1" aria-label="减少一张">−</button><b class="acc-mono"></b><button type="button" data-step="1" aria-label="增加一张">+</button>');
 stepper.addEventListener('click', event => {
  const button = event.target.closest('[data-step]');
  if (!button || button.disabled) return;
  const batch = $('genBatch'), min = Number(batch.min) || 1, max = Number(batch.max) || 4;
  fire(batch, Math.max(min, Math.min(max, (Number(batch.value) || 1) + Number(button.dataset.step))));
  refresh();
 });
 const engineChip = chip('engine', '<span class="acc-engine-icon"></span><span class="acc-engine-text"></span>', '生成通道');
 const paramsChip = chip('params', icon('sliders') + '<span>参数</span><small class="acc-params-text"></small>', '更多参数');
 chips.append(styleChip, personChip, sizeChip, stepper, engineChip, paramsChip);
 const meta = el('span', 'acc-dock-meta');
 const row = el('div', 'acc-row');
 const launch = el('div', 'acc-launch');
 launch.append(footer.querySelector('.generation-actions'), footer.querySelector('.api-popover-anchor'));
 row.append(chips, meta, launch);
 footer.prepend(cHead, cBody, row);
 // Channel group: choose which generate button is the launch button.
 const engineBox = el('section', 'acc-engine');
 engineBox.dataset.accGroup = 'engine';
 const engineList = el('div', 'acc-list');
 for (const [key, name, note, ic] of ENGINES) {
  const option = el('button', 'acc-option acc-wide', `${icon(ic)}<span><b>${name}</b><small>${note}</small></span>`);
  option.type = 'button'; option.dataset.engine = key;
  option.onclick = () => { body.dataset.accEngine = key; remember('jt-accretion-engine', key); refresh(); controls.set(''); };
  engineList.append(option);
 }
 engineBox.append(engineList);
 scroll.append(engineBox);
 const saved = remember('jt-accretion-engine');
 body.dataset.accEngine = ENGINES.some(([key]) => key === saved) ? saved : 'cloud';
 for (const [id, name] of [['genCloudBtn','云端'],['genLocalBtn','本地']]) $(id).setAttribute('aria-label', '生成 · ' + name);

 const controls = dock(root, pane, {onChange: group => { if (group === 'style') loadStyleArt(); if (group === 'person') renderPerson(); }});
 measure(body, pane);
 chips.addEventListener('click', event => { const button = event.target.closest('.acc-chip[data-group]'); if (button) controls.toggle(button.dataset.group); });
 launch.addEventListener('click', event => { if (event.target.closest('.generate,#genApiBtn')) controls.set(''); });

 function refresh() {
  const style = root.querySelector('#styleSwitch button.active');
  const styleName = style?.querySelector('.acc-style-name')?.textContent.trim() || style?.textContent.trim() || '画风';
  text(styleChip.querySelector('.acc-style-label'), styleName);
  const art = $('stylePreview')?.getAttribute('src');
  const img = styleChip.querySelector('img');
  if (art && img.getAttribute('src') !== art) img.src = art;
  if (img.hidden !== !art) img.hidden = !art;
  const mode = root.querySelector('#modeSwitch button.active');
  text(personChip.querySelector('.acc-person-label'), mode?.textContent.trim() || '人物');
  const groups = sections();
  const chosen = groups.flatMap((group, s) => group.items.map((entry, i) => ({...entry, key: s + ':' + i}))).filter(entry => entry.chosen.length);
  text(personChip.querySelector('.acc-person-count'), chosen.length ? '已选 ' + chosen.length : '');
  const engine = body.dataset.accEngine, api = engine === 'api';
  body.dataset.accApi = api ? '1' : '';
  const width = Number($('genW').value), height = Number($('genH').value);
  const preset = RATIOS.find(([, w, h]) => w === width && h === height);
  const custom = !preset || sizeBox.dataset.custom === '1';
  const apiRatio = apiRatios.find(radio => radio.checked)?.value || '';
  text(sizeChip.querySelector('.acc-size-name'), api ? (apiRatio || '比例') : custom ? '自定义' : preset[0]);
  text(sizeChip.querySelector('.acc-size-text'), api ? '' : width + '×' + height);
  const [aw, ah] = api ? apiRatio.split(':') : [width, height];
  const ratio = sizeChip.querySelector('.acc-ratio'), aspect = aw && ah ? aw + ' / ' + ah : '';
  if (ratio.style.aspectRatio !== aspect) ratio.style.aspectRatio = aspect;
  ratioRow.querySelectorAll('.acc-tile[data-w]').forEach(option => attr(option, 'aria-pressed', String(!custom && Number(option.dataset.w) === width && Number(option.dataset.h) === height)));
  attr(customTile, 'aria-pressed', String(custom));
  text(customTile.querySelector('.acc-custom-dims'), width + '×' + height);
  attr(sizeBox, 'data-mode', api ? 'api' : custom ? 'custom' : 'preset');
  apiRow.querySelectorAll('.acc-tile').forEach(option => attr(option, 'aria-pressed', String(option.dataset.ratio === apiRatio)));
  text(heads.size.querySelector('.acc-size-note'), api ? 'API 通道按比例出图' : '云端与本地通道可自定义宽高');
  const count = api ? 1 : Number($('genBatch').value) || 1;
  text(stepper.querySelector('b'), '×' + count);
  stepper.querySelectorAll('button').forEach(button => { const off = api || (button.dataset.step === '-1' ? count <= 1 : count >= (Number($('genBatch').max) || 4)); if (button.disabled !== off) button.disabled = off; });
  attr(stepper, 'title', api ? 'API 通道每次 1 张' : '生成数量');
  html(engineChip.querySelector('.acc-engine-icon'), icon(ENGINE_ICON[engine]));
  text(engineChip.querySelector('.acc-engine-text'), ENGINE_NAME[engine]);
  engineList.querySelectorAll('.acc-option').forEach(option => attr(option, 'aria-pressed', String(option.dataset.engine === engine)));
  const hd = $('genHd'), quality = $('apiQuality');
  const paramNote = api ? (quality && quality.value && quality.value !== 'auto' ? quality.value : '') : (hd && hd.value !== '0' ? (hd.selectedOptions[0]?.textContent.split(' ')[0] || '') : '');
  text(paramsChip.querySelector('.acc-params-text'), paramNote);
  text(meta, api ? '每次 1 张' : '本次 ' + count + ' 张');
  const line = $({cloud:'genCloudStatus', local:'genLocalStatus', api:'genApiStatus'}[engine])?.textContent.trim() || '';
  text(status, line);
  attr(status, 'data-bad', String(/^✗|失败|错误/.test(line)));
  // Tokens: the style, then every chosen option; manual mode shows the prompt box instead.
  const manual = root.querySelector('input[name=promptModeRadio]:checked')?.value === 'manual';
  body.dataset.accManual = manual ? '1' : '';
  html(tokens, `<span class="acc-token acc-tk-style"><span>画风</span><b>${esc(styleName)}</b></span>`
   + chosen.map(entry => `<span class="acc-token"><span>${esc(entry.name)}</span><b title="${esc(entry.value)}">${esc(entry.value)}</b><button type="button" data-clear="${entry.key}" title="移除" aria-label="移除 ${esc(entry.name)}">${icon('x')}</button></span>`).join('')
   + (chosen.length ? '' : '<span class="acc-token-hint">从「人物」里挑选项，提示词会按选项自动组合</span>'));
  if (pane.dataset.accOpen === 'person') renderPerson(groups);
 }
 root.addEventListener('click', () => requestAnimationFrame(refresh));
 root.addEventListener('change', refresh);
 root.addEventListener('input', refresh);
 new MutationObserver(refresh).observe(scroll, {subtree:true, attributes:true, attributeFilter:['class','src']});
 new MutationObserver(() => requestAnimationFrame(refresh)).observe($('drawers'), {childList:true, subtree:true});
 new MutationObserver(refresh).observe(root.querySelector('.preview-stage'), {subtree:true, attributes:true, attributeFilter:['src']});
 const statusWatch = new MutationObserver(refresh);
 for (const id of ['genCloudStatus', 'genLocalStatus', 'genApiStatus']) if ($(id)) statusWatch.observe($(id), {childList:true, characterData:true, subtree:true});
 refresh();
 feed(root, body, {reuse, engineButton});

 function engineButton(engine) { return $(engine === 'api' ? 'genApiBtn' : engine === 'local' ? 'genLocalBtn' : 'genCloudBtn'); }
 // Reuse a past batch's parameters through the same controls a person would use.
 function reuse(job, prompt) {
  const click = selector => { const button = root.querySelector(selector); if (button && !button.classList.contains('active')) button.click(); };
  if (job.style_id) click(`#styleSwitch [data-style="${CSS.escape(job.style_id)}"]`);
  if (job.style_variant) click(`#coldVariantSwitch [data-style-variant="${CSS.escape(job.style_variant)}"]`);
  if (job.mode) click(`#modeSwitch [data-mode="${CSS.escape(job.mode)}"]`);
  const engine = backendOf(job);
  body.dataset.accEngine = engine; remember('jt-accretion-engine', engine);
  if (engine !== 'api') {
   if (job.width && job.height) { fire($('genW'), job.width); fire($('genH'), job.height); }
   if (job.batch) fire($('genBatch'), job.batch);
   if (job.hd !== undefined && job.hd !== null && $('genHd')) fire($('genHd'), job.hd);
  } else if (job.api_ratio) {
   const radio = apiRatios.find(item => item.value === job.api_ratio);
   if (radio) { radio.checked = true; radio.dispatchEvent(new Event('change', {bubbles:true})); }
  }
  if (job.seed_mode === 'fixed' && job.seed !== undefined) { fire($('seedMode'), 'fixed'); fire($('genSeed'), job.seed); }
  if (prompt) {
   const radio = root.querySelector('input[name=promptModeRadio][value=manual]');
   if (radio && !radio.checked) radio.click();
   fire($('manualPositive'), prompt);
  }
  requestAnimationFrame(refresh);
 }
}

// The banner's hole is a live window onto the real background black hole: after
// each scene frame (jt:scene-frame) copy the region around the hole into the
// banner canvas. Until a frame arrives (or with WebGL off) the CSS hole shows.
function mirrorHole(root, holeBox) {
 const live = holeBox.querySelector('.acc-hole-live'), ctx = live.getContext('2d');
 let seen = true;
 new IntersectionObserver(entries => { seen = entries.some(entry => entry.isIntersecting); }).observe(holeBox);
 const draw = () => {
  const frame = window.jtApp?.sceneFrame;
  if (!frame || !seen || root.host?.hidden) return;
  const rect = holeBox.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const ratio = Math.min(2, devicePixelRatio || 1), w = Math.round(rect.width * ratio), h = Math.round(rect.height * ratio);
  if (live.width !== w || live.height !== h) { live.width = w; live.height = h; }
  const W = frame.canvas.width, H = frame.canvas.height;
  if (!W || !H) return;
  // The hole's shadow takes about a third of the banner window's height.
  const sh = Math.max(8, frame.r * H * 6), sw = sh * w / h;
  try { ctx.drawImage(frame.canvas, frame.u * W - sw / 2, frame.v * H - sh / 2, sw, sh, 0, 0, w, h); holeBox.classList.add('live'); } catch {}
 };
 addEventListener('jt:scene-frame', draw);
 addEventListener('jt:route', () => requestAnimationFrame(draw));
}

// The creator's result stream: recent batches from /api/jobs?scope=creator (the
// latest 12 jobs with a prompt excerpt), newest first, filtered by channel.
function feed(root, body, {reuse, engineButton}) {
 const $ = id => root.getElementById(id);
 const box = el('div', 'acc-feed');
 box.innerHTML = `<section class="acc-feed-hero"><div><p class="acc-eyebrow">SINGULARITY · 文生图</p><h2>向内坠落，向外成像。</h2><p>选好画风和人物，写下一个画面。它先坠入视界，再从光环里升起。</p></div><div class="acc-hole" aria-hidden="true"><i class="disk"></i><i class="lens"></i><i class="core"></i><canvas class="acc-hole-live"></canvas></div></section><div class="acc-groups" aria-live="polite"></div>`;
 root.querySelector('.preview-stage').append(box);
 const groupsBox = box.querySelector('.acc-groups');
 mirrorHole(root, box.querySelector('.acc-hole'));
 const viewer = el('div', 'acc-viewer');
 viewer.hidden = true;
 viewer.innerHTML = `<img alt=""><div class="acc-viewer-bar"><a class="acc-shot-btn" download title="下载原文件">${icon('download')}<span>下载</span></a><button type="button" class="acc-shot-btn" data-close>${icon('x')}<span>关闭</span></button></div>`;
 body.append(viewer);
 const closeViewer = () => { viewer.hidden = true; viewer.querySelector('img').removeAttribute('src'); };
 viewer.addEventListener('click', event => { if (!event.target.closest('a')) closeViewer(); });
 addEventListener('keydown', event => { if (event.key === 'Escape' && !viewer.hidden) closeViewer(); });

 let jobs = [], source = remember('jt-feed-src') || 'all', timer = 0, loading = false, again = false;
 // Prompts the person sent from this page, matched to the job that appears next on that channel.
 const promptKey = 'jt-feed-prompts';
 let prompts = {}; try { prompts = JSON.parse(sessionStorage.getItem(promptKey) || '{}') || {}; } catch { prompts = {}; }
 const pendingPrompts = [];
 root.querySelector('.creation-footer').addEventListener('click', event => {
  const button = event.target.closest('#genCloudBtn,#genLocalBtn,#genApiBtn');
  if (!button || button.disabled || button.classList.contains('is-loading') || button.getAttribute('aria-busy') === 'true') return;
  const manual = root.querySelector('input[name=promptModeRadio]:checked')?.value === 'manual';
  const prompt = (manual ? $('manualPositive').value : $('promptText').value).trim();
  if (prompt) pendingPrompts.push({engine: button.id === 'genApiBtn' ? 'api' : button.id === 'genLocalBtn' ? 'local' : 'cloud', prompt, at: Date.now() - 10000});
 }, true);
 const busy = () => ({cloud: $('genCloudBtn').classList.contains('is-loading'), local: $('genLocalBtn').classList.contains('is-loading'), api: $('genApiBtn').getAttribute('aria-busy') === 'true'});
 const styleName = id => root.querySelector(`#styleSwitch [data-style="${CSS.escape(String(id || ''))}"] .acc-style-name`)?.textContent.trim() || id || '画风';
 const statusText = engine => $({cloud:'genCloudStatus', local:'genLocalStatus', api:'genApiStatus'}[engine])?.textContent.trim() || '';

 async function load() {
  if (loading) { again = true; return; }
  loading = true;
  try {
   const response = await accountFetch('/api/jobs?scope=creator');
   if (response.ok) { const data = await response.json(); jobs = Array.isArray(data) ? data : (data.jobs || data.items || []); }
  } catch {}
  loading = false;
  render();
  if (again) { again = false; load(); }
 }
 function schedule() {
  clearTimeout(timer);
  const state = busy();
  if (Object.values(state).some(Boolean) || jobs.some(job => !FINISHED.has(String(job.status)))) timer = setTimeout(load, 3000);
 }
 function shot(job, image, index) {
  const ratio = job.width && job.height ? `aspect-ratio:${job.width}/${job.height}` : '';
  const full = image.url || image.preview_url, src = image.preview_url || image.url;
  return `<figure class="acc-shot" data-open="${esc(src)}" data-full="${esc(full)}" tabindex="0"><img class="acc-art" loading="lazy" decoding="async" alt="${esc(image.stage_label || '结果 ' + (index + 1))}" src="${esc(src)}">`
   + `<div class="acc-shot-bar"><a class="acc-shot-btn icon" href="${esc(full)}" download title="下载原文件" aria-label="下载原文件">${icon('download')}</a>`
   + (job.id ? `<button type="button" class="acc-shot-btn icon" data-fav="${esc(job.id)}" data-index="${index}" title="收藏" aria-label="收藏">${icon('heart')}</button>`
     + `<button type="button" class="acc-shot-btn icon" data-send="/realism" data-full="${esc(full)}" data-src="${esc(src)}" title="送去图片编辑" aria-label="送去图片编辑">${icon('edit')}</button>`
     + `<button type="button" class="acc-shot-btn icon" data-send="/video" data-full="${esc(full)}" data-src="${esc(src)}" title="生成视频" aria-label="生成视频">${icon('video')}</button>` : '')
   + `<span class="acc-grow"></span><button type="button" class="acc-shot-btn icon" data-open="${esc(src)}" data-full="${esc(full)}" title="放大查看" aria-label="放大查看">${icon('expand')}</button></div></figure>`;
 }
 function pendingShot(ratio, pct, note) {
  return `<div class="acc-shot pending" style="${ratio}"><div class="acc-prog"><b>${pct > 0 ? Math.round(pct) + '%' : '排队中'}</b><div class="acc-bar"><i style="width:${Math.max(0, Math.min(100, pct || 0))}%"></i></div>${note ? `<small>${esc(note)}</small>` : ''}</div></div>`;
 }
 function group(job, engine, items, prompt) {
  const dims = job.width && job.height ? job.width + '×' + job.height : '';
  const variant = job.style_variant === 'style_only' ? ' · 仅画风' : '';
  return `<section class="acc-group" data-job="${esc(job.id || '')}"><div class="acc-group-head"><time>${esc(clock(createdMs(job)) || '刚刚')}</time>`
   + `<span class="acc-tag acc-tag-acc">${esc(styleName(job.style_id))}${variant}</span>${dims ? `<span class="acc-tag acc-mono">${dims}</span>` : ''}`
   + `<span class="acc-tag">${icon(ENGINE_ICON[engine])}${ENGINE_NAME[engine]}</span><span class="acc-grow"></span>`
   + (job.id ? `<button type="button" class="acc-ghost" data-reuse="${esc(job.id)}">${icon('refresh')}复用参数</button>` : '')
   + (prompt && job.id ? `<button type="button" class="acc-ghost" data-copy="${esc(job.id)}">${icon('copy')}复制提示词</button>` : '')
   + `</div>${prompt ? `<p class="acc-group-prompt">${esc(prompt)}</p>` : ''}<div class="acc-grid">${items}</div></section>`;
 }
 function render() {
  const state = busy();
  // Attach prompts sent from this page to the first new job on that channel.
  for (const sent of [...pendingPrompts]) {
   const match = jobs.filter(job => job.id && !prompts[job.id] && backendOf(job) === sent.engine && createdMs(job) >= sent.at).sort((a, b) => createdMs(a) - createdMs(b))[0];
   if (match) { prompts[match.id] = sent.prompt; pendingPrompts.splice(pendingPrompts.indexOf(sent), 1); }
  }
  try { sessionStorage.setItem(promptKey, JSON.stringify(prompts)); } catch {}
  const sorted = [...jobs].sort((a, b) => createdMs(b) - createdMs(a));
  const parts = [];
  // A channel that is busy before its job shows up in history gets a placeholder batch.
  for (const engine of ['cloud', 'local', 'api']) {
   if (!state[engine] || sorted.some(job => backendOf(job) === engine && !FINISHED.has(String(job.status)))) continue;
   if (source !== 'all' && source !== engine) continue;
   const count = engine === 'api' ? 1 : Number($('genBatch').value) || 1;
   const ratio = engine === 'api' ? '' : `aspect-ratio:${$('genW').value}/${$('genH').value}`;
   const style = root.querySelector('#styleSwitch button.active')?.dataset.style;
   parts.push(group({style_id: style, width: engine === 'api' ? 0 : $('genW').value, height: engine === 'api' ? 0 : $('genH').value}, engine,
    Array.from({length: count}, () => pendingShot(ratio, 0, statusText(engine))).join(''), ''));
  }
  for (const job of sorted) {
   const engine = backendOf(job);
   if (source !== 'all' && source !== engine) continue;
   const status = String(job.status || ''), ratio = job.width && job.height ? `aspect-ratio:${job.width}/${job.height}` : '';
   let items;
   if (status === 'error' || status === 'failed') {
    items = `<div class="acc-shot failed" style="${ratio}"><span class="acc-tag acc-tag-bad acc-shot-tl">${icon('alert')}失败</span><div class="acc-prog"><span>${esc(styleName(job.style_id))}</span><small>${esc(job.error || '生成失败')}</small><button type="button" class="acc-ghost" data-retry="${esc(job.id)}">${icon('refresh')}重试</button></div></div>`;
   } else if (!FINISHED.has(status)) {
    items = Array.from({length: Number(job.batch) || 1}, () => pendingShot(ratio, Number(job.progress_pct) || 0, state[engine] ? statusText(engine) : '')).join('');
   } else {
    const images = (job.images || []).filter(image => image && (image.url || image.preview_url));
    if (!images.length) continue;
    items = images.map((image, i) => shot(job, image, i)).join('');
   }
   parts.push(group(job, engine, items, prompts[job.id] || job.prompt_excerpt || ''));
  }
  html(groupsBox, parts.join('') || `<div class="acc-emptybox">${icon('image')}<h3>${source === 'all' ? '还没有作品' : '这个通道还没有作品'}</h3><p>${source === 'all' ? '在下方输入台选好画风和人物后生成，结果会出现在这里。' : `在下方输入台选择「${ENGINE_NAME[source]}」通道后生成，结果会出现在这里。`}</p></div>`);
  const running = sorted.filter(job => !FINISHED.has(String(job.status))).length || Object.values(state).filter(Boolean).length;
  const tag = document.getElementById('shellRun');
  if (tag) { text(tag.querySelector('span') || tag, running ? running + ' 个任务生成中' : ''); tag.hidden = !running; }
  schedule();
 }
 box.addEventListener('click', event => {
  const target = event.target.closest('[data-open],[data-reuse],[data-copy],[data-retry],[data-fav],[data-send]');
  if (!target || event.target.closest('a[download]')) return;
  const find = id => jobs.find(job => String(job.id) === id);
  // Full prompt: what this page sent, else the server's owner-only copy.
  const fullPrompt = async job => prompts[job.id] || (job.prompt_truncated === false ? job.prompt_excerpt || '' : await fetchPrompt(job.id).catch(() => job.prompt_excerpt || ''));
  if (target.dataset.reuse) { const job = find(target.dataset.reuse); if (job) fullPrompt(job).then(prompt => reuse(job, prompt)); }
  else if (target.dataset.copy) { const job = find(target.dataset.copy); if (job) fullPrompt(job).then(prompt => prompt && navigator.clipboard?.writeText(prompt)).then(() => { target.dataset.done = '1'; setTimeout(() => delete target.dataset.done, 1200); }, () => {}); }
  else if (target.dataset.retry) { const job = find(target.dataset.retry); if (job) fullPrompt(job).then(prompt => { reuse(job, prompt); requestAnimationFrame(() => engineButton(backendOf(job))?.click()); }); }
  else if (target.dataset.fav) {
   if (target.dataset.state === 'saving' || target.dataset.state === 'saved') return;
   target.dataset.state = 'saving';
   addFavorite(target.dataset.fav, Number(target.dataset.index) || 0)
    .then(() => { target.dataset.state = 'saved'; target.title = '已收藏'; toast('已收藏，可在「收藏」页查看'); },
          error => { delete target.dataset.state; toast(error.message, true); });
  }
  else if (target.dataset.send) {
   if (target.dataset.state === 'saving') return;
   target.dataset.state = 'saving';
   sendImageTo(target.dataset.send, {url: target.dataset.full, preview: target.dataset.src})
    .then(() => toast(target.dataset.send === '/video' ? '图片已放进视频页的图片输入' : '图片已放进图片编辑的输入'), error => toast(error.message, true))
    .finally(() => delete target.dataset.state);
  }
  else if (target.dataset.open) { const img = viewer.querySelector('img'); img.src = target.dataset.open; viewer.querySelector('a').href = target.dataset.full || target.dataset.open; viewer.hidden = false; viewer.querySelector('[data-close]').focus(); }
 });
 box.addEventListener('keydown', event => { if (event.key === 'Enter' && event.target.matches('.acc-shot[data-open]')) event.target.click(); });
 addEventListener('jt:feed-src', event => { source = event.detail; render(); });
 // Reload when a channel finishes or starts, and when the page shows again.
 let last = JSON.stringify(busy());
 const watch = new MutationObserver(() => { const now = JSON.stringify(busy()); if (now !== last) { last = now; load(); } });
 for (const id of ['genCloudBtn', 'genLocalBtn', 'genApiBtn']) watch.observe($(id), {attributes:true, attributeFilter:['class', 'aria-busy']});
 const results = new MutationObserver(() => load());
 for (const id of ['genCloudResult', 'genLocalResult', 'genApiResult']) if ($(id)) results.observe($(id), {childList:true});
 addEventListener('jt:route', event => { if (event.detail.path === '/') load(); });
 load();
}

// Image edit and video: their forms are long and mostly uploads, so the dock
// keeps the whole form in one panel above it, open until the person folds it.
const WB_MODEL = /^(MiniMax|Wan|SCAIL|Qwen|GPT|Flux|Kling|Seedance|Hunyuan)/i;
const WB_ICON = {'视频生成':'video', '视频编辑':'edit', '动作迁移':'shuffle', '图片编辑':'image'};
function workflowPage(root, body, key) {
 const pane = root.querySelector('.creation-pane'), footer = pane.querySelector('.creation-footer');
 body.classList.add('acc', 'acc-workflow');
 const select = root.getElementById('workflowSelect');
 const row = el('div', 'acc-row');
 const chips = el('div', 'acc-chips');
 const flowChip = chip('panel', icon('layers') + '<span class="acc-flow"></span>' + icon('chevron'), '方案与参数');
 chips.append(flowChip);
 const launch = el('div', 'acc-launch');
 launch.append(...[...footer.children]);
 row.append(chips, launch);
 footer.prepend(row);
 const storeKey = 'jt-accretion-panel-' + key;
 // Outside clicks do not fold this panel: people keep uploading in it while results load.
 const controls = dock(root, pane, {initial: remember(storeKey) === 'closed' ? '' : 'panel', closeOnOutside: false,
  onChange: group => remember(storeKey, group ? 'open' : 'closed')});
 chips.addEventListener('click', event => { if (event.target.closest('.acc-chip')) controls.toggle('panel'); });
 measure(body, pane);
 // Workbench: one scheme card stands in for the wall of workflow names; the library dialog lists them
 // as cards grouped by purpose. Picking a card clicks the page's own button / changes its own select.
 body.classList.add('acc-wb');
 const safe = value => String(value).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
 const split = name => { const at = name.indexOf(' · '); return at > 0 && WB_MODEL.test(name) ? [name.slice(at + 3).trim(), name.slice(0, at).trim()] : [name.trim(), '']; };
 const schemes = () => select
  ? [...select.options].map(option => ({id: option.value, name: option.textContent.trim(), group: option.parentElement.tagName === 'OPTGROUP' ? option.parentElement.label : '图片编辑', active: option.selected, pick: () => fire(select, option.value)}))
  : [...root.querySelectorAll('#wfSwitch button[data-wf]')].map(button => ({id: button.dataset.wf, name: button.textContent.trim(), group: button.closest('.workflow-section')?.querySelector('.workflow-section-title')?.textContent.trim() || '其他', active: button.classList.contains('active'), pick: () => button.click()}));
 if (select) { select.classList.add('wb-hide'); if (select.previousElementSibling?.tagName === 'LABEL') select.previousElementSibling.classList.add('wb-hide'); }
 const schemeCard = el('button', 'wb-scheme', `<span class="wb-art">${icon('layers')}</span><span class="wb-scheme-text"><b></b><small></small></span>${icon('chevron')}`);
 schemeCard.type = 'button'; schemeCard.setAttribute('aria-haspopup', 'dialog'); schemeCard.setAttribute('aria-label', '更换方案');
 const schemeWrap = el('div', 'wb-scheme-wrap', '<span class="wb-label">方案</span>');
 schemeWrap.append(schemeCard);
 pane.querySelector('.creation-scroll').prepend(schemeWrap);
 const library = el('div', 'wb-lib');
 library.hidden = true;
 body.append(library);
 let filter = '全部';
 const drawLibrary = () => {
  const list = schemes(), groups = ['全部', ...new Set(list.map(item => item.group))];
  html(library, `<div class="wb-lib-card" role="dialog" aria-modal="true" aria-label="选择方案"><header><div><h2>选择方案</h2><p>按你想做的事来选，模型名在卡片下方</p></div><button type="button" class="acc-icon-button" data-close aria-label="关闭">${icon('x')}</button></header>${
   groups.length > 2 ? `<nav>${groups.map(name => `<button type="button" class="wb-filter" data-filter="${safe(name)}" aria-pressed="${name === filter}">${safe(name)}</button>`).join('')}</nav>` : ''
  }<div class="wb-grid">${list.map((item, index) => {
   if (filter !== '全部' && item.group !== filter) return '';
   const [title, model] = split(item.name);
   return `<button type="button" class="wb-card" data-index="${index}" data-pick="${safe(item.id)}" aria-pressed="${item.active}"><span class="wb-art" style="--h:${(index * 47 + 18) % 360}">${icon(WB_ICON[item.group] || 'layers')}</span><b>${safe(title)}</b><span class="wb-tags"><i>${safe(item.group)}</i>${model ? `<i>${safe(model)}</i>` : ''}</span></button>`;
  }).join('')}</div></div>`);
 };
 const closeLibrary = () => { if (!library.hidden) { library.hidden = true; schemeCard.focus(); } };
 schemeCard.addEventListener('click', () => { filter = '全部'; drawLibrary(); library.hidden = false; library.querySelector('[aria-pressed="true"].wb-card')?.focus(); });
 library.addEventListener('click', event => {
  const target = event.target;
  if (target === library || target.closest('[data-close]')) return closeLibrary();
  const tab = target.closest('[data-filter]');
  if (tab) { filter = tab.dataset.filter; return drawLibrary(); }
  const card = target.closest('.wb-card');
  if (card) { schemes()[Number(card.dataset.index)]?.pick(); closeLibrary(); }
 });
 root.addEventListener('keydown', event => { if (event.key === 'Escape' && !library.hidden) { event.stopPropagation(); closeLibrary(); } }, true);
 const stage = root.querySelector('.preview-stage');
 if (stage) stage.append(el('div', 'wb-empty', icon(key === 'video' ? 'video' : 'image') + '<b>结果会显示在这里</b><span>任务完成后自动出现，也可以在右侧点开已完成的任务</span>'));
 // Task rail rows read "thumbnail + name + state"; the name lives in each card's details popover.
 const rail = root.querySelector('#taskPanel, .task-panel');
 const nameTasks = () => rail?.querySelectorAll('.task-card').forEach(card => {
  const tile = card.querySelector('.task-tile'), name = card.querySelector('.task-name')?.textContent.trim() || '';
  if (tile) attr(tile, 'data-wb-title', split(name)[0] || '任务');
 });
 // The count reads as one badge: the fixed "（最多 N 个并发）" tail is left out of the badge text.
 const badgeCount = () => { const count = rail?.querySelector('#taskCount'); if (!count) return; const short = count.textContent.replace(/\s*[（(].*$/, '').trim(); attr(count, 'data-wb', short); attr(count, 'data-live', String(/[1-9]/.test(short.replace(/\/\s*\d+/, '')))); };
 if (rail) { new MutationObserver(() => { nameTasks(); badgeCount(); }).observe(rail, {subtree:true, childList:true, characterData:true}); nameTasks(); badgeCount(); }
 function refresh() {
  const name = (select ? select.selectedOptions[0]?.textContent : root.querySelector('#wfSwitch button.active')?.textContent) || '';
  text(flowChip.querySelector('.acc-flow'), (name || '选择方案').trim());
  const current = schemes().find(item => item.active), [title, model] = split(name || '选择方案');
  text(schemeCard.querySelector('b'), title);
  text(schemeCard.querySelector('small'), [model, current?.group].filter(Boolean).join(' · ') || '点击选择');
 }
 root.addEventListener('change', refresh);
 root.addEventListener('click', () => requestAnimationFrame(refresh));
 new MutationObserver(refresh).observe(pane, {subtree:true, childList:true, attributes:true, attributeFilter:['class','disabled']});
 refresh();
}

addEventListener('jt:page-mounted', event => {
 const {root} = event.detail, body = root.querySelector?.('.jt-page-body');
 if (!body || body.classList.contains('acc')) return;
 if (root.getElementById('genCloudBtn')) creator(root, body);
 else if (root.getElementById('workflowSelect')) workflowPage(root, body, 'edit');
 else if (root.getElementById('wfSwitch')) workflowPage(root, body, 'video');
});

// Shell chrome: the title row names the current page and the sidebar card mirrors the quota the
// account dialog already shows. Nothing here asks the server or changes account state.
const TITLES = {'/':['创作台','选好画风和人物，写下一个画面'], '/realism':['图片编辑','上传人物图，按描述或参考图改造'], '/video':['视频','生成、编辑与动作迁移']};
let quotaBound = false;
function mirrorQuota() {
 const source = document.getElementById('accountQuota'), card = document.getElementById('sideQuota');
 if (quotaBound || !source || !card) return;
 quotaBound = true;
 const render = () => {
  const rows = [...source.querySelectorAll('dt')].map(dt => [dt.textContent.trim(), dt.nextElementSibling?.textContent.trim() || '', dt.nextElementSibling?.dataset.ratio]);
  // The two balances get a meter each; the two limits share one "任务" line.
  const nodes = [], limits = [];
  for (const [name, value, ratio] of rows) {
   if (!/剩余额度/.test(name)) { limits.push((/排队/.test(name) ? '排队 ' : '同时 ') + value); continue; }
   const row = el('div', 'side-quota-row'), label = el('span'), amount = el('b'), meter = el('div', 'side-meter'), fill = el('i');
   label.textContent = name.replace('剩余', ''); amount.textContent = value; row.append(label, amount);
   const number = Number(value);
   fill.style.width = (ratio !== undefined ? Number(ratio) * 100 : number > 0 ? 100 : 0) + '%';
   meter.append(fill); nodes.push(row, meter);
  }
  if (limits.length) {
   const row = el('div', 'side-quota-row'), label = el('span'), badge = el('span', 'side-badge');
   label.textContent = '任务'; badge.textContent = limits.join(' · '); row.append(label, badge); nodes.push(row);
  }
  card.replaceChildren(...nodes);
  card.hidden = !rows.length;
 };
 new MutationObserver(render).observe(source, {childList:true, subtree:true, characterData:true});
 render();
}
// Creator title row: channel filter for the result stream and a running-task tag.
const SOURCES = [['all','全部'],['cloud','云端'],['local','本地'],['api','API']];
function shellTools() {
 const top = document.querySelector('body > .app-shell > .shell-top');
 if (!top || document.getElementById('shellSrc')) return;
 const seg = el('div', 'shell-seg');
 seg.id = 'shellSrc'; seg.setAttribute('role', 'group'); seg.setAttribute('aria-label', '按通道筛选结果');
 const saved = remember('jt-feed-src') || 'all';
 for (const [key, name] of SOURCES) {
  const button = el('button'); button.type = 'button'; button.dataset.src = key; button.textContent = name;
  button.setAttribute('aria-pressed', String(key === saved));
  seg.append(button);
 }
 seg.addEventListener('click', event => {
  const button = event.target.closest('[data-src]');
  if (!button) return;
  seg.querySelectorAll('[data-src]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
  remember('jt-feed-src', button.dataset.src);
  dispatchEvent(new CustomEvent('jt:feed-src', {detail: button.dataset.src}));
 });
 const run = el('span', 'shell-run', icon('clock') + '<span></span>');
 run.id = 'shellRun'; run.hidden = true;
 top.append(run, seg);
}
addEventListener('jt:route', event => {
 const [title, sub] = TITLES[event.detail.path] || ['', ''];
 const heading = document.getElementById('shellTitle'), note = document.getElementById('shellSub');
 if (heading) text(heading, title);
 if (note) text(note, sub);
 mirrorQuota();
 shellTools();
 const creatorPage = event.detail.path === '/';
 for (const id of ['shellSrc', 'shellRun']) { const node = document.getElementById(id); if (node) node.classList.toggle('shell-off', !creatorPage); }
 document.body.classList.toggle('wb-route', !creatorPage);
});
