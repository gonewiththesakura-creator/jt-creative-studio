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
