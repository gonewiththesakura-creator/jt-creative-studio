from pathlib import Path

FILES=[Path(r'D:/LAN-Share/lora/_work/comfy_panel/static/promptgen.html'),Path(r'D:/LAN-Share/lora/_work/comfy_panel/static/index.html')]
for p in FILES:
 s=p.read_text(encoding='utf8')
 def once(a,b):
  nonlocal_dummy=None
  global s
  if a not in s: raise RuntimeError(f'missing in {p}: {a[:80]}')
  s=s.replace(a,b,1)
 once('''    .picker-wrap{
      margin-top:12px;
    }''','''    .picker-wrap{display:none;margin-top:12px}
    .item.expanded .picker-wrap{display:block}
    .expand-picker{width:34px;height:34px;border-radius:11px;background:#f5f0f4;color:#947789;font-size:15px}''')
 once('''let state = {};
let locked = {};''','''let state = {};
let locked = {};
let expandedKeys = new Set();''')
 once('''function pick(arr){ return arr[Math.floor(Math.random()*arr.length)] }

function randomize''','''function pick(arr){ return arr[Math.floor(Math.random()*arr.length)] }
function emptyItem(key){ return POOLS[key].find(item=>item[1]==="") || POOLS[key][0]; }
function initializeDefaults(){
  Object.keys(POOLS).forEach(key=>{
    if(!state[key]) state[key] = MULTI_KEYS.has(key) ? [emptyItem(key)] : emptyItem(key);
  });
}

function randomize''')
 once('''    div.className = "item" + (["holiday","story","pose","camera","scene"].includes(key) ? " wide" : "") + (locked[key] ? " locked" : "");''','''    div.className = "item" + (["holiday","story","pose","camera","scene"].includes(key) ? " wide" : "") + (locked[key] ? " locked" : "") + (expandedKeys.has(key) ? " expanded" : "");''')
 once('''        <div class="item-actions">
          <button class="reroll"''','''        <div class="item-actions">
          <button class="expand-picker" title="展开/收起选项" aria-label="展开/收起选项">⌄</button>
          <button class="reroll"''')
 once('''    div.querySelector(".lock").onclick = ()=>{
      locked[key] = !locked[key];''','''    div.querySelector(".expand-picker").onclick = ()=>{
      if(expandedKeys.has(key)) expandedKeys.delete(key); else expandedKeys.add(key);
      render();
    };
    div.querySelector(".lock").onclick = ()=>{
      locked[key] = !locked[key];''')
 once('''  state = snapshot.state;
  locked = snapshot.locked || {};''','''  state = normalizeSnapshotState(snapshot.state);
  locked = snapshot.locked || {};
  expandedKeys = new Set(Object.keys(state).filter(k=>selectedItems(k).some(x=>x && x[1])));''')
 once('''  window.scrollTo({top:0, behavior:'smooth'});
}

async function copyText''','''  window.scrollTo({top:0, behavior:'smooth'});
}
function normalizeSnapshotState(saved){
  const out={};
  Object.keys(POOLS).forEach(key=>{
    const vals = MULTI_KEYS.has(key)
      ? (Array.isArray(saved?.[key]?.[0]) ? saved[key] : (saved?.[key] ? [saved[key]] : []))
      : (saved?.[key] ? [saved[key]] : []);
    const matched=vals.map(v=>POOLS[key].find(x=>x[1]===v[1] || x[0]===v[0])).filter(Boolean);
    out[key]=MULTI_KEYS.has(key) ? (matched.length?matched:[emptyItem(key)]) : (matched[0]||emptyItem(key));
  });
  return out;
}

async function copyText''')
 once('''load();
randomize(false);''','''load();
initializeDefaults();
render();''')
 p.write_text(s,encoding='utf8')
 print('updated',p)
