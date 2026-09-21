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
const pageRoots = new Set([shell]);
const busySelector='.primary.is-loading, .primary[aria-busy="true"], .task-spin:not(.done):not(.err)';
function checkBusy() {
  const busy = [...pageRoots].some(root=>root.querySelector(busySelector));
  if(window.jtApp)window.jtApp.metrics.businessBusy=!!busy;
  if (busy !== businessBusy) { businessBusy = busy; draw(); }
}
function observePage(root) {
  pageRoots.add(root);
  new MutationObserver(checkBusy).observe(root, {subtree:true, childList:true, attributes:true, attributeFilter:['class','aria-busy']});
  checkBusy();
}
observePage(shell);
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
let appearance, applySceneSettings = () => {};
const {installAppearance,installPreview} = await import("/static/assets/appearance.effeec028e01.js");
appearance=installAppearance(controls,values=>applySceneSettings(values));
installPreview();
function attachPage(root,scope) { observePage(root);installPreview(scope.document,scope.page?.styleBoot); }
addEventListener('jt:page-mounted',event=>attachPage(event.detail.root,event.detail.scope));
if(window.jtApp)for(const page of window.jtApp.router.pages.values())attachPage(page.shadow,page.scope);
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
    if(window.jtApp)window.jtApp.metrics.importStarted=performance.now();
    const [THREE, {EffectComposer}, {RenderPass}, {UnrealBloomPass}, {OutputPass}, shaders] = await Promise.all([
      import("/static/assets/three-module.71e909ad3fc6.js"), import("/static/assets/EffectComposer.88857d0d9347.js"),
      import("/static/assets/RenderPass.5c6b1fa147e5.js"), import("/static/assets/UnrealBloomPass.6b2ef6cf2ccd.js"),
      import("/static/assets/OutputPass.f59d09171ad0.js"), import("/static/assets/shaders.96809084e5fe.js")
    ]);
    const renderer = new THREE.WebGLRenderer({canvas, antialias:innerWidth>820, powerPreference:'low-power'});
    if(window.jtApp){window.jtApp.metrics.renderers++;window.jtApp.metrics.initialized=performance.now();}
    renderer.debug.onShaderError = () => fallback(new Error('Black-hole shader could not compile'));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = .95;
    const scene = new THREE.Scene(), camera = new THREE.Camera();
    const uniforms = {
      resolution:{value:new THREE.Vector2()}, cameraPositionBH:{value:new THREE.Vector3()},
      cameraRight:{value:new THREE.Vector3()}, cameraUp:{value:new THREE.Vector3()}, cameraForward:{value:new THREE.Vector3()},
      time:{value:0}, mass:{value:1}, flow:{value:1}, temperature:{value:.95}, lensing:{value:1},
      flashEnergy:{value:0}, starMotion:{value:1}, focal:{value:1.35}, mobile:{value:0}, centerOffset:{value:new THREE.Vector2(.19,.075)}
    };
    const quad = new THREE.Mesh(new THREE.PlaneGeometry(2,2), new THREE.ShaderMaterial({
      uniforms, vertexShader:shaders.vertexShader, fragmentShader:shaders.fragmentShader, depthTest:false, depthWrite:false
    }));
    quad.frustumCulled = false; scene.add(quad);
    const target = new THREE.WebGLRenderTarget(1,1,{type:THREE.HalfFloatType,samples:innerWidth>820?2:0});
    const composer = new EffectComposer(renderer,target);
    composer.addPass(new RenderPass(scene,camera));
    const bloom=new UnrealBloomPass(new THREE.Vector2(1,1),.075,.4,1.15);
    composer.addPass(bloom);
    composer.addPass(new OutputPass());
    let azimuth=0, elevation=12, radius=20, width=1, height=1, frameId=0, last=0, sim=0, pointer=null;
    let settings=appearance.get();
    let budget = (innerWidth <= 820 ? 550000 : 1400000)*settings.quality, slowFrames=0;
    const up = new THREE.Vector3(0,1,0);
    function resize() {
      width=innerWidth; height=innerHeight;
      const ratio=Math.min(devicePixelRatio,width<=820?1:1.25,Math.sqrt(budget/(width*height)));
      renderer.setPixelRatio(ratio);renderer.setSize(width,height,false);
      composer.setPixelRatio(ratio);composer.setSize(width,height);
      uniforms.resolution.value.set(width,height);uniforms.mobile.value=width<=820?1:0;
      uniforms.focal.value=(width<=820?.67:1.35)*settings.zoom;
      draw();
    }
    function render(now) {
      frameId=0;
      if (!available || document.hidden) return;
      if (last && now-last < (width<=820?50:33)) { frameId=requestAnimationFrame(render); return; }
      const dt=Math.max(0,(now-(last||now))/1000);last=now;
      if (!paused && !businessBusy) sim+=dt*settings.speed;
      uniforms.time.value=sim;
      uniforms.centerOffset.value.set(immersive?0:width<=820?settings.mobileX:settings.offsetX,immersive?.01:width<=820?settings.mobileY:settings.offsetY);
      const a=azimuth*Math.PI/180,b=elevation*Math.PI/180;
      uniforms.cameraPositionBH.value.set(Math.sin(a)*Math.cos(b)*radius,Math.sin(b)*radius,Math.cos(a)*Math.cos(b)*radius);
      uniforms.cameraForward.value.copy(uniforms.cameraPositionBH.value).normalize().negate();
      uniforms.cameraRight.value.crossVectors(uniforms.cameraForward.value,up).normalize();
      uniforms.cameraRight.value.applyAxisAngle(uniforms.cameraForward.value,settings.tilt*Math.PI/180);
      uniforms.cameraUp.value.crossVectors(uniforms.cameraRight.value,uniforms.cameraForward.value).normalize();
      const before=performance.now();
      try { composer.render(); } catch(error) { fallback(error); return; }
      if (!available) return;
      if(window.jtApp){window.jtApp.metrics.frames=(window.jtApp.metrics.frames||0)+1;window.jtApp.metrics.sim=sim;window.jtApp.metrics.pixelBudget=budget;}
      // GPU commands are asynchronous: CPU submission time alone misses a slow
      // compositor. Also observe consecutive active frame intervals.
      if (performance.now()-before>60 || (!paused&&!businessBusy&&dt>.1)) slowFrames++; else slowFrames=Math.max(0,slowFrames-1);
      if (slowFrames>8 && budget>300000) { budget=Math.max(300000,budget*.6);slowFrames=0;resize(); }
      document.body.dataset.singularity='ready';
      if(window.jtApp&&!window.jtApp.metrics.firstFrame)window.jtApp.metrics.firstFrame=performance.now();
      if (!paused && !businessBusy && !frameId) frameId=requestAnimationFrame(render);
    }
    draw = () => { if (available && !document.hidden && !frameId) {last=0;frameId=requestAnimationFrame(render);} };
    applySceneSettings = values => {
      const qualityChanged=settings.quality!==values.quality;
      settings=values;azimuth=settings.azimuth;elevation=settings.elevation;radius=settings.radius;
      for(const key of ['mass','flow','temperature','lensing','starMotion'])uniforms[key].value=settings[key];
      renderer.toneMappingExposure=settings.exposure;bloom.strength=settings.bloom*(innerWidth<=820?.8:1);
      if(qualityChanged)budget=(innerWidth<=820?550000:1400000)*settings.quality;
      resize();
    };
    canvas.addEventListener('webglcontextlost', e => { e.preventDefault();cancelAnimationFrame(frameId);fallback(); });
    addEventListener('visibilitychange', () => {
      cancelAnimationFrame(frameId);frameId=0;last=0;
      if (!document.hidden) draw();
    });
    canvas.addEventListener('pointerdown',e=>{pointer={x:e.clientX,y:e.clientY};canvas.setPointerCapture(e.pointerId);});
    canvas.addEventListener('pointermove',e=>{if(!pointer)return;azimuth-=(e.clientX-pointer.x)*.25;elevation=THREE.MathUtils.clamp(elevation+(e.clientY-pointer.y)*.18,4,65);pointer={x:e.clientX,y:e.clientY};draw();});
    canvas.addEventListener('pointerup',()=>{pointer=null;azimuth=((azimuth+180)%360+360)%360-180;appearance.update({azimuth,elevation});});
    canvas.addEventListener('pointercancel',()=>pointer=null);
    canvas.addEventListener('wheel',e=>{if(!immersive)return;e.preventDefault();radius=THREE.MathUtils.clamp(radius+e.deltaY*.012,13,40);appearance.update({radius});},{passive:false});
    addEventListener('resize',resize);
    available=true;applySceneSettings(settings);draw();
  } catch(error) { fallback(error); }
}
if ('requestIdleCallback' in window) requestIdleCallback(startScene,{timeout:1600});
else setTimeout(startScene,250);
