function videoInputEnabled(workflow,mapping,params){
  if(workflow.id==='h3_remix_full'&&mapping===workflow.rh_media.face_reference&&!params.face_refine)return false;
  const rule=mapping.depends_on;
  return !rule||(params[rule.key]??workflow.rh_params?.[rule.key]?.default)===rule.value;
}
function enhanceRemixForm(form,workflow,state){
  form.onchange=null;form.classList.remove('remix-form');
  if(workflow.id!=='h3_remix_full')return;
  form.classList.add('remix-form');
  const groups=new Map(),fields=[];
  function group(name){
    if(groups.has(name))return groups.get(name);
    const box=document.createElement('details'),heading=document.createElement('summary');
    box.className='remix-group';box.dataset.group=name;box.open=['基本设置','参考素材'].includes(name);
    heading.textContent=name;box.append(heading);groups.set(name,box);return box;
  }
  // Detach each field as one unit, so hidden dependencies never leave orphan labels.
  for(const [key,mapping] of Object.entries(workflow.rh_media||{})){
    const drop=form.querySelector('.drop[data-media-key="'+key+'"]'),label=drop.previousElementSibling,box=document.createElement('div');
    box.className='remix-field';box.dataset.mediaField=key;box.append(label,drop);group(mapping.group||'参考素材').append(box);
    drop.dataset.mediaType=mapping.type;
    if(mapping.type==='audio'){
      drop.querySelector('.upload-kind-icon').textContent='♪';
      drop.querySelector('.upload-formats').textContent='点击或拖入音频 · MP3 / WAV / FLAC / M4A / OGG';
    }
    fields.push({box,mapping,key,media:true});
  }
  for(const [key,mapping] of Object.entries(workflow.rh_params||{})){
    const input=form.querySelector('#param_'+key);if(!input)continue;
    const label=input.previousElementSibling,box=document.createElement('div');box.className='remix-field';box.dataset.control=key;
    const presets=key==='prompt'?form.querySelector('.prompt-presets'):null;
    const duration=key==='duration'?form.querySelector('#durationAutoNote'):null;
    label.htmlFor=input.id;box.append(label,input);if(presets)box.append(presets);if(duration)box.append(duration);
    if(input.type==='checkbox'){box.classList.add('remix-toggle');label.prepend(input)}
    if(mapping.description){const help=document.createElement('div');help.className='note';help.textContent=mapping.description;box.append(help)}
    group(mapping.group||'基本设置').append(box);fields.push({box,mapping,key});
  }
  for(const name of ['基本设置','参考素材','更多参考素材','一采与高级设置','二次采样设置','LoRA 设置','人脸精修设置','独立人脸参考','参考素材截取','输出设置']){
    const box=groups.get(name);if(box)form.append(box);
  }
  const update=()=>{
    const params={};for(const key of Object.keys(workflow.rh_params))params[key]=readParamValue(form.querySelector('#param_'+key));
    for(const field of fields){
      let enabled=videoInputEnabled(workflow,field.mapping,params);
      if(field.mapping.group==='二次采样设置')enabled&&=params.second_pass;
      if(field.mapping.group==='人脸精修设置')enabled&&=params.face_refine;
      if(field.key==='save_second')enabled&&=params.second_pass;
      if(field.key==='save_face')enabled&&=params.face_refine;
      field.box.hidden=!enabled;
      // Keep values when switching off; hidden branches are excluded server-side.
    }
    for(const box of groups.values())box.hidden=![...box.querySelectorAll(':scope > .remix-field')].some(field=>!field.hidden);
    state.formParams={...params};
  };
  form.onchange=update;update();
}

function installVideoCompactForm(form,workflow,state){
  const items=Object.entries(workflow.rh_media||{}).map(([key,mapping])=>{
    const drop=form.querySelector('.drop[data-media-key="'+key+'"]');
    let box=drop.closest('.remix-field');
    if(!box){box=document.createElement('div');box.className='compact-upload-field';const label=drop.previousElementSibling;drop.before(box);if(label?.tagName==='LABEL')box.append(label);box.append(drop)}
    return {key,type:mapping.type,label:mapping.label||key,box,drop,
      filled:()=>!!state.tokens[key],hasFile:()=>!!state.files[key],
      enabled:()=>videoInputEnabled(workflow,mapping,Object.fromEntries(Object.entries(workflow.rh_params||{}).map(([key,p])=>[key,document.getElementById('param_'+key)?readParamValue(document.getElementById('param_'+key)):p.default])))};
  });
  installCompactUploads(form,items,{before:form.children[1]});
  for(const group of form.querySelectorAll('.remix-group'))if(!group.querySelector('.remix-field'))group.hidden=true;
  installWorkflowToggleButtons(form);
}
