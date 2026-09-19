// Visual-only adapter. Never reads prompts, credentials, jobs or generation endpoints.
const shell = document.querySelector('.app-shell');
const canvas = document.createElement('canvas');
canvas.id = 'singularityCanvas';
canvas.setAttribute('aria-hidden', 'true');
document.body.prepend(canvas);
const controls = document.createElement('div');
controls.className = 'singularity-controls';
controls.innerHTML = '<button type="button" class="topbar-action" id="singularityMotion" aria-pressed="false" title="暂停或继续黑洞背景动画">暂停光场</button><button type="button" class="topbar-action" id="singularityFocus" title="进入黑洞场景，可拖动旋转、滚轮缩放">沉浸</button>';
document.querySelector('.topbar-tools')?.prepend(controls);
const exit = document.createElement('button');
exit.type = 'button';
exit.className = 'singularity-exit';
exit.textContent = '返回工作台 · Esc';
document.body.append(exit);
const motion = controls.querySelector('#singularityMotion');
const focus = controls.querySelector('#singularityFocus');
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
let paused = reduced.matches, immersive = false, draw = () => {}, available = false, businessBusy = false;
new MutationObserver(() => {
  const busy = !!shell.querySelector('.primary.is-loading, .primary[aria-busy="true"], .task-spin:not(.done):not(.err)');
  if (busy !== businessBusy) { businessBusy = busy; draw(); }
}).observe(shell, {subtree:true, childList:true, attributes:true, attributeFilter:['class','aria-busy']});
try { paused ||= localStorage.getItem('jt-singularity-paused') === 'true'; } catch {}
function updateMotion() {
  motion.textContent = paused ? '继续光场' : '暂停光场';
  motion.setAttribute('aria-pressed', String(paused));
}
motion.onclick = () => {
  paused = !paused;
  try { localStorage.setItem('jt-singularity-paused', String(paused)); } catch {}
  updateMotion(); draw();
};
function setImmersive(value) {
  immersive = value;
  document.body.classList.toggle('scene-focus', value);
  shell.inert = value;
  canvas.setAttribute('aria-hidden', String(!value));
  (value ? exit : focus).focus();
  draw();
}
focus.onclick = () => setImmersive(true);
exit.onclick = () => setImmersive(false);
addEventListener('keydown', e => { if (e.key === 'Escape' && immersive) setImmersive(false); });
reduced.addEventListener('change', e => { paused = e.matches; updateMotion(); draw(); });
updateMotion();
const empty = document.querySelector('#previewEmpty');
if (empty) {
  const hero = document.createElement('div');
  hero.className = 'singularity-hero';
  hero.innerHTML = '<small>SINGULARITY / 灵感的引力</small><h2>让想象，<br><em>越过视界。</em></h2><p>从一个念头，到一个新世界。<br>选择画风，开始你的创作。</p>';
  empty.parentElement.prepend(hero);
}
function fallback(error) {
  console.warn('Black-hole visual unavailable; workbench remains usable.', error?.message || 'WebGL context lost');
  available = false;
  canvas.hidden = true;
  document.body.dataset.singularity = 'fallback';
  motion.textContent = '静态光场'; motion.disabled = true;
  if (immersive) setImmersive(false);
  focus.disabled = true;
}

async function startScene() {
  // Defer GPU setup until the business interface has painted. No blocking overlay.
  try {
    const [THREE, {EffectComposer}, {RenderPass}, {UnrealBloomPass}, {OutputPass}, shaders] = await Promise.all([
      import('three'), import('three/addons/postprocessing/EffectComposer.js'),
      import('three/addons/postprocessing/RenderPass.js'), import('three/addons/postprocessing/UnrealBloomPass.js'),
      import('three/addons/postprocessing/OutputPass.js'), import('./shaders.js')
    ]);
    const renderer = new THREE.WebGLRenderer({canvas, antialias:true, powerPreference:'low-power'});
    renderer.debug.onShaderError = () => fallback(new Error('Black-hole shader could not compile'));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = .95;
    const scene = new THREE.Scene(), camera = new THREE.Camera();
    const uniforms = {
      resolution:{value:new THREE.Vector2()}, cameraPositionBH:{value:new THREE.Vector3()},
      cameraRight:{value:new THREE.Vector3()}, cameraUp:{value:new THREE.Vector3()}, cameraForward:{value:new THREE.Vector3()},
      time:{value:0}, mass:{value:1}, flow:{value:1}, temperature:{value:.95}, lensing:{value:1},
      flashEnergy:{value:0}, focal:{value:1.35}, mobile:{value:0}, centerOffset:{value:new THREE.Vector2(.19,.075)}
    };
    const quad = new THREE.Mesh(new THREE.PlaneGeometry(2,2), new THREE.ShaderMaterial({
      uniforms, vertexShader:shaders.vertexShader, fragmentShader:shaders.fragmentShader, depthTest:false, depthWrite:false
    }));
    quad.frustumCulled = false; scene.add(quad);
    const target = new THREE.WebGLRenderTarget(1,1,{type:THREE.HalfFloatType,samples:2});
    const composer = new EffectComposer(renderer,target);
    composer.addPass(new RenderPass(scene,camera));
    composer.addPass(new UnrealBloomPass(new THREE.Vector2(1,1),.075,.4,1.15));
    composer.addPass(new OutputPass());
    let azimuth=0, elevation=12, radius=20, width=1, height=1, frameId=0, last=0, sim=0, pointer=null;
    let budget = innerWidth <= 820 ? 550000 : 1400000, slowFrames=0;
    const up = new THREE.Vector3(0,1,0);
    function resize() {
      width=innerWidth; height=innerHeight;
      const ratio=Math.min(devicePixelRatio,1.25,Math.sqrt(budget/(width*height)));
      renderer.setPixelRatio(ratio);renderer.setSize(width,height,false);
      composer.setPixelRatio(ratio);composer.setSize(width,height);
      uniforms.resolution.value.set(width,height);uniforms.mobile.value=width<=820?1:0;
      uniforms.focal.value=width<=820?.67:1.35;
      draw();
    }
    function render(now) {
      frameId=0;
      if (!available || document.hidden) return;
      if (last && now-last < (width<=820?50:33)) { frameId=requestAnimationFrame(render); return; }
      const dt=Math.min((now-(last||now))/1000,.08);last=now;
      if (!paused && !businessBusy) sim+=dt;
      uniforms.time.value=sim;
      uniforms.centerOffset.value.set(immersive?0:width<=820?0:.19,immersive?.01:.015);
      const a=azimuth*Math.PI/180,b=elevation*Math.PI/180;
      uniforms.cameraPositionBH.value.set(Math.sin(a)*Math.cos(b)*radius,Math.sin(b)*radius,Math.cos(a)*Math.cos(b)*radius);
      uniforms.cameraForward.value.copy(uniforms.cameraPositionBH.value).normalize().negate();
      uniforms.cameraRight.value.crossVectors(uniforms.cameraForward.value,up).normalize();
      uniforms.cameraUp.value.crossVectors(uniforms.cameraRight.value,uniforms.cameraForward.value).normalize();
      const before=performance.now();
      try { composer.render(); } catch(error) { fallback(error); return; }
      if (!available) return;
      if (performance.now()-before>60) slowFrames++; else slowFrames=Math.max(0,slowFrames-1);
      if (slowFrames>8 && budget>300000) { budget=Math.max(300000,budget*.6);slowFrames=0;resize(); }
      document.body.dataset.singularity='ready';
      if (!paused && !businessBusy && !frameId) frameId=requestAnimationFrame(render);
    }
    draw = () => { if (available && !document.hidden && !frameId) frameId=requestAnimationFrame(render); };
    canvas.addEventListener('webglcontextlost', e => { e.preventDefault();cancelAnimationFrame(frameId);fallback(); });
    addEventListener('visibilitychange', () => {
      cancelAnimationFrame(frameId);frameId=0;last=0;
      if (!document.hidden) draw();
    });
    canvas.addEventListener('pointerdown',e=>{pointer={x:e.clientX,y:e.clientY};canvas.setPointerCapture(e.pointerId);});
    canvas.addEventListener('pointermove',e=>{if(!pointer)return;azimuth-=(e.clientX-pointer.x)*.25;elevation=THREE.MathUtils.clamp(elevation+(e.clientY-pointer.y)*.18,4,65);pointer={x:e.clientX,y:e.clientY};draw();});
    canvas.addEventListener('pointerup',()=>pointer=null);
    canvas.addEventListener('pointercancel',()=>pointer=null);
    canvas.addEventListener('wheel',e=>{if(!immersive)return;e.preventDefault();radius=THREE.MathUtils.clamp(radius+e.deltaY*.012,13,30);draw();},{passive:false});
    addEventListener('resize',resize);
    available=true;resize();draw();
  } catch(error) { fallback(error); }
}
if ('requestIdleCallback' in window) requestIdleCallback(startScene,{timeout:1600});
else setTimeout(startScene,250);
