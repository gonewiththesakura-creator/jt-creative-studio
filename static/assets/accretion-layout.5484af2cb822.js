// ACCRETION layout for the shell pages: the scene fills the window and the
// creation pane becomes a command dock at the bottom. Layout only. It moves a
// few existing nodes and adds chips that reveal existing sections; business
// code keeps its own elements, ids and handlers. Values change only through the
// same input/change events a person would fire.
const PATHS = {
 shuffle:'<path d="M4 7h3.2c4.3 0 5.3 10 9.6 10H20"/><path d="M4 17h3.2c1.6 0 2.7-1.4 3.6-3.2M13.2 10.2C14.1 8.4 15.2 7 16.8 7H20"/><path d="m17.5 4.5 2.5 2.5-2.5 2.5M17.5 14.5l2.5 2.5-2.5 2.5"/>',
 chevron:'<path d="m7 10 5 5 5-5"/>',
 sliders:'<path d="M5 7h9M18 7h1M5 17h3M12 17h7"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
 user:'<circle cx="12" cy="8.5" r="3.6"/><path d="M5 19.5c1.3-3.3 3.9-5 7-5s5.7 1.7 7 5"/>',
 layers:'<path d="m12 4 8 4-8 4-8-4 8-4Z"/><path d="m4 12 8 4 8-4M4 16l8 4 8-4"/>',
 bolt:'<path d="M13 3 5 13.5h6L10 21l8-10.5h-6L13 3Z"/>',
};
const icon = name => `<svg class="acc-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${PATHS[name]}</svg>`;
const RATIOS = [['1:1',1024,1024],['3:4',896,1184],['2:3',832,1248],['9:16',768,1360],['16:9',1360,768]];
const ENGINES = [['cloud','云端','ComfyUI 云端工作站'],['local','本地','本机 ComfyUI'],['api','API','GPT Image，每次 1 张']];

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
function remember(key, value) { try { if (value === undefined) return localStorage.getItem(key); localStorage.setItem(key, value); } catch { return null; } }

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
 const topbar = document.querySelector('body > .app-shell > .topbar'), footer = pane.querySelector('.creation-footer');
 const update = () => {
  if (!footer.offsetHeight) return;
  body.style.setProperty('--acc-top', (topbar?.offsetHeight || 68) + 'px');
  body.style.setProperty('--acc-dock', Math.round(footer.offsetHeight + (innerWidth <= 760 ? 8 : 24)) + 'px');
 };
 const observer = new ResizeObserver(update);
 observer.observe(footer);
 if (topbar) observer.observe(topbar);
 update();
}
function chip(group, html, label) {
 const button = el('button', 'acc-chip', html);
 button.type = 'button';
 if (group) { button.dataset.group = group; button.setAttribute('aria-expanded', 'false'); }
 if (label) button.setAttribute('aria-label', label);
 return button;
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
 // Size and count get their own groups; their labels keep the original inputs.
 const settings = scroll.querySelector('.settings');
 const sizeBox = el('section', 'acc-size settings'), countBox = el('section', 'acc-count');
 sizeBox.dataset.accGroup = 'size'; countBox.dataset.accGroup = 'count';
 const ratioRow = el('div', 'acc-options');
 for (const [name, width, height] of RATIOS) {
  const option = el('button', 'acc-option', `<i class="acc-ratio" style="aspect-ratio:${width}/${height}"></i><span>${name}</span><small>${width}×${height}</small>`);
  option.type = 'button'; option.dataset.w = width; option.dataset.h = height;
  option.onclick = () => { fire($('genW'), width); fire($('genH'), height); refresh(); };
  ratioRow.append(option);
 }
 sizeBox.append(ratioRow, $('genW').closest('label'), $('genH').closest('label'));
 const countRow = el('div', 'acc-options');
 for (let n = 1; n <= 4; n++) {
  const option = el('button', 'acc-option', `<span>× ${n}</span>`);
  option.type = 'button'; option.dataset.n = n;
  option.onclick = () => { fire($('genBatch'), n); refresh(); };
  countRow.append(option);
 }
 const batchLabel = $('genBatch').closest('label');
 countBox.append(countRow, batchLabel);
 settings.dataset.accGroup = 'params';
 settings.before(sizeBox, countBox);
 // Manual negative prompt lives with the other parameters, as in the prototype.
 const negative = $('manualNegative'), negativeBox = el('section', 'acc-negative prompt');
 negativeBox.dataset.accGroup = 'params';
 negativeBox.append(negative.previousElementSibling, negative);
 settings.before(negativeBox);
 // Prompt row: mode switch, the visible prompt, import-to-manual and shuffle.
 const promptRow = el('div', 'acc-prompt');
 const shuffle = el('button', 'acc-icon-button', icon('shuffle'));
 shuffle.type = 'button'; shuffle.title = '随机选项'; shuffle.setAttribute('aria-label', '随机选项');
 shuffle.onclick = () => $('randomAll').click();
 const promptTools = el('div', 'acc-prompt-tools');
 promptTools.append($('promptModePanel'), $('importGeneratedPrompt'), shuffle);
 $('promptText').readOnly = true;
 promptRow.append(promptTools, $('manualPromptPanel'), $('promptPanel'));
 // Chips and launch.
 const chips = el('div', 'acc-chips');
 const styleChip = chip('style', '<img class="acc-chip-art" alt=""><span class="acc-style-name"></span>' + icon('chevron'), '画风');
 const personChip = chip('person', icon('user') + '<span class="acc-person"></span>', '人物与选项');
 const sizeChip = chip('size', '<i class="acc-ratio"></i><span class="acc-size-text acc-mono"></span>', '画面尺寸');
 const countChip = chip('count', '<span class="acc-count-text acc-mono"></span>', '数量');
 const engineChip = chip('engine', icon('bolt') + '<span class="acc-engine-text"></span>', '生成引擎');
 const paramsChip = chip('params', icon('sliders') + '<span>参数</span>', '更多参数');
 chips.append(styleChip, personChip, sizeChip, countChip, engineChip, paramsChip);
 const meta = el('span', 'acc-dock-meta acc-mono');
 const row = el('div', 'acc-row');
 const launch = el('div', 'acc-launch');
 launch.append(footer.querySelector('.generation-actions'), footer.querySelector('.api-popover-anchor'));
 row.append(chips, meta, launch);
 footer.prepend(promptRow, row);
 // Engine group: choose which generate button is the launch button.
 const engineBox = el('section', 'acc-engine');
 engineBox.dataset.accGroup = 'engine';
 const engineList = el('div', 'acc-list');
 for (const [key, name, note] of ENGINES) {
  const option = el('button', 'acc-option acc-wide', `<b>${name}</b><small>${note}</small>`);
  option.type = 'button'; option.dataset.engine = key;
  option.onclick = () => { body.dataset.accEngine = key; remember('jt-accretion-engine', key); refresh(); controls.set(''); };
  engineList.append(option);
 }
 engineBox.append(engineList);
 scroll.append(engineBox);
 const saved = remember('jt-accretion-engine');
 body.dataset.accEngine = ENGINES.some(([key]) => key === saved) ? saved : 'cloud';
 for (const [id, name] of [['genCloudBtn','云端'],['genLocalBtn','本地']]) $(id).setAttribute('aria-label', '生成 · ' + name);
 // Hero for the empty stage.
 const hero = el('section', 'acc-hero', '<p class="acc-eyebrow">SINGULARITY · 文生图</p><h2>向内坠落，<br>向外成像。</h2><p>选好画风和人物，写下一个画面。<br>它先坠入视界，再从光环里升起。</p>');
 hero.setAttribute('aria-hidden', 'true');
 root.querySelector('.preview-stage').prepend(hero);
 const controls = dock(root, pane);
 measure(body, pane);
 chips.addEventListener('click', event => { const button = event.target.closest('.acc-chip[data-group]'); if (button) controls.toggle(button.dataset.group); });
 launch.addEventListener('click', event => { if (event.target.closest('.generate')) controls.set(''); });

 function refresh() {
  const style = root.querySelector('#styleSwitch button.active');
  text(styleChip.querySelector('.acc-style-name'), style?.textContent.trim() || '画风');
  const art = $('stylePreview')?.getAttribute('src');
  const img = styleChip.querySelector('img');
  if (art && img.getAttribute('src') !== art) img.src = art;
  if (img.hidden !== !art) img.hidden = !art;
  const mode = root.querySelector('#modeSwitch button.active');
  text(personChip.querySelector('.acc-person'), mode?.textContent.trim() || '人物');
  const width = Number($('genW').value), height = Number($('genH').value);
  text(sizeChip.querySelector('.acc-size-text'), width + '×' + height);
  const ratio = sizeChip.querySelector('.acc-ratio'), aspect = width && height ? width + ' / ' + height : '';
  if (ratio.style.aspectRatio !== aspect) ratio.style.aspectRatio = aspect;
  sizeBox.querySelectorAll('.acc-option').forEach(option => attr(option, 'aria-pressed', String(Number(option.dataset.w) === width && Number(option.dataset.h) === height)));
  text(countChip.querySelector('.acc-count-text'), '× ' + ($('genBatch').value || 1));
  countBox.querySelectorAll('.acc-option').forEach(option => attr(option, 'aria-pressed', String(option.dataset.n === String($('genBatch').value))));
  const engine = body.dataset.accEngine;
  text(engineChip.querySelector('.acc-engine-text'), ENGINES.find(([key]) => key === engine)[1]);
  engineList.querySelectorAll('.acc-option').forEach(option => attr(option, 'aria-pressed', String(option.dataset.engine === engine)));
  text(meta, engine === 'api' ? '每次 1 张' : width + '×' + height + ' · ' + ($('genBatch').value || 1) + ' 张');
 }
 root.addEventListener('click', () => requestAnimationFrame(refresh));
 root.addEventListener('change', refresh);
 root.addEventListener('input', refresh);
 new MutationObserver(refresh).observe(scroll, {subtree:true, attributes:true, attributeFilter:['class','src']});
 new MutationObserver(refresh).observe(root.querySelector('.preview-stage'), {subtree:true, attributes:true, attributeFilter:['src']});
 refresh();
}

// Image edit and video: their forms are long and mostly uploads, so the dock
// keeps the whole form in one panel above it, open until the person folds it.
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
 function refresh() {
  const name = select ? select.selectedOptions[0]?.textContent : root.querySelector('#wfSwitch button.active')?.textContent;
  text(flowChip.querySelector('.acc-flow'), (name || '选择方案').trim());
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
