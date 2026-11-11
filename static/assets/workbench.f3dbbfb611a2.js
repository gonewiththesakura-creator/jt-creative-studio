// Visual-only adapter. Never reads prompts, credentials, jobs or generation endpoints.
const shell = document.querySelector('.app-shell');
const canvas = document.createElement('canvas');
canvas.id = 'singularityCanvas';
canvas.setAttribute('aria-hidden', 'true');
document.body.prepend(canvas);
// Scene settings share one topbar entry; the work entries (favorites, history, account) stay first-level.
const sceneMenu = document.createElement('div');
sceneMenu.className = 'scene-menu-anchor';
sceneMenu.innerHTML = '<button type="button" class="topbar-action scene-menu-toggle" id="sceneMenuOpen" aria-expanded="false" aria-controls="sceneMenu" title="背景光场、沉浸与外观"><span>场景</span></button>';
const controls = document.createElement('div');
controls.className = 'scene-menu';
controls.id = 'sceneMenu';
controls.hidden = true;
controls.innerHTML = '<button type="button" class="topbar-action" id="singularityMotion" aria-pressed="false" title="暂停或继续黑洞背景动画">暂停光场</button><button type="button" class="topbar-action" id="singularityFocus" title="进入黑洞场景，可拖动旋转、滚轮缩放">沉浸</button>';
sceneMenu.append(controls);
const tools = document.querySelector('.topbar-tools');
const historyEntry = tools?.querySelector('#histOpen');
if (historyEntry) historyEntry.after(sceneMenu); else tools?.prepend(sceneMenu);
const sceneToggle = sceneMenu.querySelector('#sceneMenuOpen');
function setSceneMenu(open, restoreFocus = false) {
  controls.hidden = !open;
  sceneToggle.setAttribute('aria-expanded', String(open));
  if (open) controls.querySelector('button:not(:disabled)')?.focus();
  else if (restoreFocus) sceneToggle.focus();
}
sceneToggle.onclick = () => setSceneMenu(controls.hidden);
// Items keep their own handlers. The menu closes after an action, except the motion toggle, whose new label stays visible.
controls.addEventListener('click', e => {
  const item = e.target.closest('button');
  if (item && item.id !== 'singularityMotion') setSceneMenu(false, document.activeElement === item);
});
sceneMenu.addEventListener('focusout', e => { if (!controls.hidden && e.relatedTarget && !sceneMenu.contains(e.relatedTarget)) setSceneMenu(false); });
document.addEventListener('pointerdown', e => { if (!controls.hidden && !sceneMenu.contains(e.target)) setSceneMenu(false); });
addEventListener('keydown', e => { if (e.key === 'Escape' && !controls.hidden) setSceneMenu(false, true); });
const exit = document.createElement('button');
exit.type = 'button';
exit.className = 'singularity-exit';
exit.textContent = '返回工作台 · Esc';
document.body.append(exit);
const motion = controls.querySelector('#singularityMotion');
const focus = controls.querySelector('#singularityFocus');
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
let paused = reduced.matches, immersive = false, draw = () => {}, available = false, businessBusy = false;
// Low-power still frame: chosen automatically for software rasterizers or a
// scene that stays under 1 fps; the motion button resumes it for the session.
let autoStill = false, stillOverride = false;
// Accretion: a running task feeds the disk instead of freezing it. energy eases
// toward 1 while any page is busy; pulse flashes the photon ring once a task ends.
let energy = 0, pulse = 0;
const pageRoots = new Set([shell]);
// Generating in any page counts: creator buttons, and image-edit / video task cards.
const busySelector='.primary.is-loading, .primary[aria-busy="true"], .task-spin:not(.done):not(.err), .task-card[data-status="running"], .task-card[data-status="recovering"]';
function markBusy(root) {
  const body = root === shell ? document.body : root.querySelector?.('.jt-page-body');
  body?.classList.toggle('accretion-busy', businessBusy);
}
function checkBusy() {
  const busy = [...pageRoots].some(root=>root.querySelector(busySelector));
  if(window.jtApp)window.jtApp.metrics.businessBusy=!!busy;
  if (busy !== businessBusy) {
    if (!busy) pulse = 1;
    businessBusy = busy;
    pageRoots.forEach(markBusy);
    draw();
  }
}
function observePage(root) {
  if (!root || typeof root.querySelector !== 'function') return;
  pageRoots.add(root);
  markBusy(root);
  new MutationObserver(checkBusy).observe(root, {subtree:true, childList:true, attributes:true, attributeFilter:['class','aria-busy','data-status']});
  checkBusy();
}
observePage(shell);
try { paused ||= localStorage.getItem('jt-singularity-paused') === 'true'; } catch {}
function updateMotion() {
  const still = paused || autoStill;
  motion.textContent = still ? '继续光场' : '暂停光场';
  motion.setAttribute('aria-pressed', String(still));
}
function enterStill(reason) {
  if (autoStill || stillOverride) return;
  autoStill = true;
  document.body.dataset.singularityPower = 'still';
  if (window.jtApp) window.jtApp.metrics.lowPower = reason;
  updateMotion(); draw();
}
motion.onclick = () => {
  if (paused || autoStill) {
    // One press resumes from any still frame; automatic stills stay off for this session.
    if (autoStill) {
      autoStill = false; stillOverride = true;
      delete document.body.dataset.singularityPower;
      if (window.jtApp) window.jtApp.metrics.lowPower = false;
    }
    paused = false;
  } else paused = true;
  try { localStorage.setItem('jt-singularity-paused', String(paused)); } catch {}
  updateMotion(); draw();
};
function setImmersive(value) {
  immersive = value;
  document.body.classList.toggle('scene-focus', value);
  shell.inert = value;
  canvas.setAttribute('aria-hidden', String(!value));
  (value ? exit : sceneToggle).focus();
  draw();
}
focus.onclick = () => setImmersive(true);
exit.onclick = () => setImmersive(false);
addEventListener('keydown', e => { if (e.key === 'Escape' && immersive) setImmersive(false); });
reduced.addEventListener('change', e => { paused = e.matches; updateMotion(); draw(); });
updateMotion();
let appearance, applySceneSettings = () => {};
const {installAppearance,installPreview} = await import("/static/assets/appearance.4502ac7e3877.js");
appearance=installAppearance(controls,values=>applySceneSettings(values));
installPreview();
function attachPage(root,scope) { observePage(root);installPreview(scope.document,scope.page?.styleBoot); }
addEventListener('jt:page-mounted',event=>attachPage(event.detail.root,event.detail.scope));
if(window.jtApp?.router)for(const page of window.jtApp.router.pages.values())attachPage(page.shadow,page.scope);
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
  // The login gate or business interface has painted before GPU setup begins.
  try {
    if(window.jtApp)window.jtApp.metrics.importStarted=performance.now();
    const [THREE, {EffectComposer}, {RenderPass}, {UnrealBloomPass}, {OutputPass}, shaders] = await Promise.all([
      import("/static/assets/three-module.71e909ad3fc6.js"), import("/static/assets/EffectComposer.88857d0d9347.js"),
      import("/static/assets/RenderPass.5c6b1fa147e5.js"), import("/static/assets/UnrealBloomPass.6b2ef6cf2ccd.js"),
      import("/static/assets/OutputPass.f59d09171ad0.js"), import("/static/assets/shaders.7ff4fe47bac2.js")
    ]);
    const renderer = new THREE.WebGLRenderer({canvas, antialias:innerWidth>820, powerPreference:'low-power'});
    const gl=renderer.getContext();
    if(window.jtApp){window.jtApp.metrics.renderers++;window.jtApp.metrics.initialized=performance.now();window.jtApp.metrics.lowPower=false;}
    // Software rasterizers spend seconds on one frame and stall input with it.
    const rendererInfo=gl.getExtension('WEBGL_debug_renderer_info');
    const rendererName=String(gl.getParameter(rendererInfo?rendererInfo.UNMASKED_RENDERER_WEBGL:gl.RENDERER)||'');
    if(/swiftshader|llvmpipe|softpipe|software|basic render/i.test(rendererName))enterStill('software');
    renderer.debug.onShaderError = () => fallback(new Error('Black-hole shader could not compile'));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = .95;
    const scene = new THREE.Scene(), camera = new THREE.Camera();
    const uniforms = {
      resolution:{value:new THREE.Vector2()}, cameraPositionBH:{value:new THREE.Vector3()},
      cameraRight:{value:new THREE.Vector3()}, cameraUp:{value:new THREE.Vector3()}, cameraForward:{value:new THREE.Vector3()},
      time:{value:0}, mass:{value:1}, flow:{value:1}, temperature:{value:.95}, lensing:{value:1},
      flashEnergy:{value:0}, ringPulse:{value:0}, starMotion:{value:1}, focal:{value:1.35}, mobile:{value:0}, centerOffset:{value:new THREE.Vector2(.19,.075)}
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
    // Retain the finished, tone-mapped frame at its existing resolution. Login
    // travel samples this texture; it never enlarges a DOM canvas or reruns the
    // expensive ray marcher while the interface is fading.
    composer.renderToScreen=false;
    const displayUniforms={image:{value:null},zoom:{value:1},center:{value:new THREE.Vector2(.5,.5)}};
    const displayScene=new THREE.Scene();
    displayScene.add(new THREE.Mesh(new THREE.PlaneGeometry(2,2),new THREE.ShaderMaterial({
      uniforms:displayUniforms,vertexShader:shaders.vertexShader,
      fragmentShader:'varying vec2 vUv; uniform sampler2D image; uniform float zoom; uniform vec2 center; void main(){gl_FragColor=texture2D(image,center+(vUv-center)/zoom);}',
      depthTest:false,depthWrite:false,toneMapped:false
    })));
    const display=()=>{renderer.setRenderTarget(null);renderer.render(displayScene,camera)};
    let entryActive=false,hasFrame=false,entryReady=Promise.resolve(false),pendingFrame=null;
    let azimuth=0, elevation=12, radius=20, width=1, height=1, frameId=0, last=0, sim=0, pointer=null;
    let settings=appearance.get();
    let budget = (innerWidth <= 820 ? 550000 : 1400000)*settings.quality, slowFrames=0, verySlowFrames=0;
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
    // Where the hole sits on the canvas (u,v from the top-left, r = shadow
    // radius as a fraction of canvas height), published right after a frame is
    // drawn so page mirrors (the creator banner) can copy that region while the
    // drawing buffer is still valid.
    function publishFrame() {
      if(!window.jtApp)return;
      const res=uniforms.resolution.value,c=uniforms.centerOffset.value,zoom=displayUniforms.zoom.value,ce=displayUniforms.center.value;
      const su=.5+c.x*res.y/res.x,sv=.5+c.y,dist=uniforms.cameraPositionBH.value.length(),b=2.598*uniforms.mass.value;
      const r=uniforms.focal.value*b/Math.sqrt(Math.max(1e-6,dist*dist-b*b));
      window.jtApp.sceneFrame={canvas,u:ce.x+(su-ce.x)*zoom,v:1-(ce.y+(sv-ce.y)*zoom),r:r*zoom,at:performance.now()};
      dispatchEvent(new Event('jt:scene-frame'));
    }
    function render(now) {
      frameId=0;
      if (!available || document.hidden || entryActive) return;
      if (last && now-last < (width<=820?50:33)) { frameId=requestAnimationFrame(render); return; }
      const dt=Math.max(0,(now-(last||now))/1000);last=now;
      const target=businessBusy?1:0;
      // A paused, reduced-motion or low-power scene shows the end state in one still frame.
      const still=paused||autoStill;
      if (still) { energy=target; pulse=0; }
      else { energy+=(target-energy)*Math.min(1,dt*1.6); pulse=Math.max(0,pulse-dt*.9); }
      if (!still) sim+=dt*settings.speed*(1+2.4*energy);
      uniforms.time.value=sim;
      uniforms.flashEnergy.value=energy*1.4+pulse*2.2;
      uniforms.ringPulse.value=pulse;
      uniforms.temperature.value=settings.temperature*(1+.22*energy+.12*pulse);
      uniforms.centerOffset.value.set(immersive?0:width<=820?settings.mobileX:settings.offsetX,immersive?.01:width<=820?settings.mobileY:settings.offsetY);
      const a=azimuth*Math.PI/180,b=elevation*Math.PI/180;
      uniforms.cameraPositionBH.value.set(Math.sin(a)*Math.cos(b)*radius,Math.sin(b)*radius,Math.cos(a)*Math.cos(b)*radius);
      uniforms.cameraForward.value.copy(uniforms.cameraPositionBH.value).normalize().negate();
      uniforms.cameraRight.value.crossVectors(uniforms.cameraForward.value,up).normalize();
      uniforms.cameraRight.value.applyAxisAngle(uniforms.cameraForward.value,settings.tilt*Math.PI/180);
      uniforms.cameraUp.value.crossVectors(uniforms.cameraRight.value,uniforms.cameraForward.value).normalize();
      const before=performance.now();
      try {composer.render();displayUniforms.image.value=composer.readBuffer.texture;display();hasFrame=true;} catch(error) { fallback(error); return; }
      if (!available) return;
      publishFrame();
      if(window.jtApp){window.jtApp.metrics.frames=(window.jtApp.metrics.frames||0)+1;window.jtApp.metrics.sim=sim;window.jtApp.metrics.energy=energy;window.jtApp.metrics.pixelBudget=budget;}
      // GPU commands are asynchronous: CPU submission time alone misses a slow
      // compositor. Also observe consecutive active frame intervals.
      if (performance.now()-before>60 || (!still&&dt>.1)) slowFrames++; else slowFrames=Math.max(0,slowFrames-1);
      // Under 1 fps the slow-frame count needs tens of seconds; two such frames
      // in a row go straight to the still frame.
      if (!still&&dt>1) { if (++verySlowFrames>=2) enterStill('slow'); } else verySlowFrames=0;
      const floor=width<=820?120000:300000;
      if (slowFrames>8 && budget>floor) {
        // Step down from the pixels actually drawn: a phone canvas is smaller than its nominal budget.
        budget=Math.max(floor,Math.min(budget,canvas.width*canvas.height)*.6);slowFrames=0;resize();
      } else if (slowFrames>8 && !still) enterStill('slow');
      document.body.dataset.singularity='ready';
      if(window.jtApp&&!window.jtApp.metrics.firstFrame)window.jtApp.metrics.firstFrame=performance.now();
      const settling=Math.abs(target-energy)>.005||pulse>0;
      if (!(paused||autoStill) && (settings.speed>0||settling) && settings.opacity>0 && !frameId){
        // Keep at most one expensive frame in flight. A slow GPU must not build
        // up a backlog that later blocks input or the login transition.
        pendingFrame=gl.fenceSync?.(gl.SYNC_GPU_COMMANDS_COMPLETE,0);gl.flush();
        const nextFrame=()=>{
          frameId=0;
          if(!pendingFrame){if(available&&!entryActive&&!document.hidden)frameId=requestAnimationFrame(render);return}
          const status=gl.clientWaitSync(pendingFrame,0,0),done=status===gl.ALREADY_SIGNALED||status===gl.CONDITION_SATISFIED;
          if(done||entryActive||!available||document.hidden){gl.deleteSync(pendingFrame);pendingFrame=null;if(done&&available&&!entryActive&&!document.hidden)frameId=requestAnimationFrame(render);return}
          frameId=requestAnimationFrame(nextFrame);
        };
        frameId=requestAnimationFrame(pendingFrame?nextFrame:render);
      }
    }
    draw = () => { if (available && !document.hidden && !entryActive && !frameId) {last=0;frameId=requestAnimationFrame(render);} };
    if(window.jtApp)window.jtApp.scene={
      beginEntry(){
        if(!available||!hasFrame)return false;
        if(entryActive)return true;
        entryActive=true;cancelAnimationFrame(frameId);frameId=0;
        if(pendingFrame){gl.deleteSync(pendingFrame);pendingFrame=null}
        const x=width<=820?settings.mobileX:settings.offsetX,y=width<=820?settings.mobileY:settings.offsetY;
        displayUniforms.center.value.set(.5+x*height/width,.5+y);
        // Command submission is asynchronous. Drain the final expensive frame
        // before starting the travel clock, without a blocking gl.finish().
        const fence=gl.fenceSync?.(gl.SYNC_GPU_COMMANDS_COMPLETE,0);
        entryReady=fence?new Promise(resolve=>{
          const deadline=performance.now()+3000;gl.flush();
          const check=()=>{
            const status=gl.clientWaitSync(fence,0,0),done=status===gl.ALREADY_SIGNALED||status===gl.CONDITION_SATISFIED;
            if(done||!entryActive||!available||performance.now()>deadline){gl.deleteSync(fence);resolve(done&&entryActive&&available);return}
            requestAnimationFrame(check);
          };
          requestAnimationFrame(check);
        }):Promise.resolve(true);
        return true;
      },
      waitForEntry:()=>entryReady,
      paintEntry(zoom){if(!entryActive||!available)return;displayUniforms.zoom.value=zoom;display();},
      endEntry(){entryActive=false;displayUniforms.zoom.value=1;last=0;draw();},
      getAppearance:()=>({...settings})
    };
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
if (document.body.dataset.loginScene&&document.body.dataset.loginScene!=='workbench')requestAnimationFrame(startScene);
else if ('requestIdleCallback' in window) requestIdleCallback(startScene,{timeout:1600});
else setTimeout(startScene,250);
