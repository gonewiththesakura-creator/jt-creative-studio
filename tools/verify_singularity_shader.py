"""Real WebGL shader regression, no provider requests. Uses the supplied camera preset."""
import json
import mimetypes
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/singularity-motion'

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--use-angle=swiftshader','--enable-unsafe-swiftshader'])
        page=browser.new_page(viewport={'width':800,'height':600})
        def serve(route):
            path=urlparse(route.request.url).path
            if path=='/':
                return route.fulfill(content_type='text/html',body='<script type="importmap">{"imports":{"three":"/static/singularity/vendor/build/three.module.js"}}</script><canvas id="probe"></canvas>')
            file=ROOT/path.lstrip('/')
            if file.resolve().is_relative_to(ROOT/'static') and file.is_file():
                return route.fulfill(body=file.read_bytes(),content_type=mimetypes.guess_type(file)[0])
            return route.fulfill(status=404)
        page.route('**/*',serve);page.goto('http://fixture.test/')
        result=page.evaluate('''async()=>{
          const T=await import('three'), s=await import('/static/singularity/shaders.js');
          const renderer=new T.WebGLRenderer({canvas:document.querySelector('canvas'),preserveDrawingBuffer:true});
          renderer.setSize(800,600);let failed=false;renderer.debug.onShaderError=()=>failed=true;
          const scene=new T.Scene(),camera=new T.Camera(),position=new T.Vector3();
          const a=19*Math.PI/180,b=5*Math.PI/180,r=15.2;
          position.set(Math.sin(a)*Math.cos(b)*r,Math.sin(b)*r,Math.cos(a)*Math.cos(b)*r);
          const forward=position.clone().normalize().negate(),right=new T.Vector3().crossVectors(forward,new T.Vector3(0,1,0)).normalize().applyAxisAngle(forward,20*Math.PI/180),up=new T.Vector3().crossVectors(right,forward).normalize();
          const uniforms={resolution:{value:new T.Vector2(800,600)},cameraPositionBH:{value:position},cameraRight:{value:right},cameraUp:{value:up},cameraForward:{value:forward},time:{value:0},mass:{value:1},flow:{value:1},temperature:{value:.3},lensing:{value:.99},flashEnergy:{value:0},focal:{value:1.35*1.63},mobile:{value:0},centerOffset:{value:new T.Vector2(.39,.02)},starMotion:{value:1}};
          const sky=s.fragmentShader.split('void main(){')[0]+'void main(){gl_FragColor=vec4(sky(normalize(vec3((vUv-.5)*2.,1.))),1.);}';
          const material=new T.ShaderMaterial({vertexShader:s.vertexShader,fragmentShader:sky,uniforms});
          const mesh=new T.Mesh(new T.PlaneGeometry(2,2),material);mesh.frustumCulled=false;scene.add(mesh);
          function render(t){uniforms.time.value=t;renderer.render(scene,camera);const gl=renderer.getContext(),pixels=new Uint8Array(800*600*4);gl.readPixels(0,0,800,600,gl.RGBA,gl.UNSIGNED_BYTE,pixels);return pixels;}
          const diff=(a,b)=>a.reduce((n,v,i)=>n+Math.abs(v-b[i]),0)/a.length;
          const star0=render(0),star1=render(2),starDifference=diff(star0,star1);
          material.fragmentShader=s.fragmentShader;material.needsUpdate=true;uniforms.starMotion.value=0;
          const disk0=render(0),diskLate=render(256),lateDifference=diff(disk0,diskLate);
          const lateMotion=diff(diskLate,render(258));
          const seam16=diff(render(15.999),render(16.001)),seam32=diff(render(31.999),render(32.001));
          window.renderProbe=render;
          return {failed,starDifference,lateDifference,lateMotion,seam16,seam32};
        }''')
        page.screenshot(path=str(OUT/'late-frame.png'))
        print(json.dumps(result))
        browser.close()
        assert not result['failed']
        assert result['starDifference']>.001,'stars do not animate'
        assert result['lateDifference']<.01,'disk texture accumulates shear rather than cycling'
        assert result['lateMotion']>.01,'disk no longer moves late in the animation'
        assert max(result['seam16'],result['seam32'])<.05,'visible jump at gas-layer reset'

if __name__=='__main__': main()
