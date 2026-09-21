"""Offline performance comparison and real WebGL lifetime checks. Zero live API access."""
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from test_app_shell import serve_page, current
from playwright.sync_api import sync_playwright, expect

OUT=ROOT/'evidence/app-shell'


def measure(browser,legacy,width):
    page=browser.new_page(viewport={'width':width,'height':900})
    requests=serve_page(page,legacy=legacy,block_scene=True)
    page.goto('http://fixture.test/')
    expect(page.locator('#genApiBtn')).to_be_enabled()
    ready=page.evaluate('performance.now()')
    nav=page.evaluate('performance.getEntriesByType("navigation")[0].toJSON()')
    resources=page.evaluate('performance.getEntriesByType("resource").map(r=>({name:r.name,bytes:r.decodedBodySize}))')
    sizes={'html':0,'js':0,'css':0,'style':0,'images':0}
    from urllib.parse import urlparse
    initial=ROOT/'static'/('index.html' if legacy else 'app.html')
    sizes['html']=initial.stat().st_size
    for row in resources:
        path=urlparse(row['name']).path;file=ROOT/path.lstrip('/')
        if not file.is_file():continue
        if not row['bytes']:continue
        key='style' if 'style-' in path and file.suffix=='.json' else {'html':'html','js':'js','css':'css','webp':'images'}.get(file.suffix.lstrip('.'))
        if key:sizes[key]+=file.stat().st_size
    timings=[]
    if not legacy:page.evaluate("window.routeTimes=[];addEventListener('jt:route',e=>routeTimes.push(e.detail))")
    for route in ['/realism','/video','/']:
        start=time.perf_counter()
        page.locator(('body > .app-shell > .topbar ' if not legacy else '')+f'.topnav-link[href="{route}"]').click()
        expect(page.locator('.creation-pane').filter(visible=True)).to_be_visible()
        if not legacy:page.wait_for_function('document.body.dataset.page === '+json.dumps(route))
        else:page.wait_for_url('**'+('/' if route=='/' else route))
        timings.append(round((time.perf_counter()-start)*1000,1))
    warm=[]
    if not legacy:
        for route in ['/realism','/video','/']:
            page.locator(f'body > .app-shell > .topbar .topnav-link[href="{route}"]').click()
            page.wait_for_function('document.body.dataset.page === '+json.dumps(route))
        warm=page.evaluate('routeTimes')
        page.screenshot(path=str(OUT/f'ui-{width}.png'))
    result={'legacy':legacy,'width':width,'initial_bytes':sizes,'dcl_ms':round(nav['domContentLoadedEventEnd'],1),
        'router_events':warm,
        'controls_ready_ms':round(ready,1),'switch_ms':timings,'document_requests':len([r for r in requests if r[2]=='document'])}
    page.close();return result


def gpu(browser,width):
    page=browser.new_page(viewport={'width':width,'height':700})
    requests=serve_page(page);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('console',lambda message:print(message.type,message.text,flush=True) if message.type in ('warning','error') else None)
    page.add_init_script('''window.gpuCounts={contexts:0,compiles:0};
      const contexts=new Set(),get=HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext=function(...args){const result=get.apply(this,args);if(result&&String(args[0]).startsWith('webgl')&&!contexts.has(result)){contexts.add(result);gpuCounts.contexts++}return result};
      for(const type of [WebGLRenderingContext,WebGL2RenderingContext]){const compile=type.prototype.compileShader;type.prototype.compileShader=function(...args){gpuCounts.compiles++;return compile.apply(this,args)}}''')
    page.goto('http://fixture.test/')
    expect(current(page).locator('#genApiBtn')).to_be_enabled()
    ui_ready=page.evaluate('performance.now()')
    page.wait_for_function("['ready','fallback'].includes(document.body.dataset.singularity)",timeout=60000)
    assert page.evaluate('document.body.dataset.singularity')=='ready',errors
    counts=page.evaluate('({...gpuCounts,renderers:jtApp.metrics.renderers})')
    page.locator('#singularityMotion').click()
    for route in ['/realism','/video','/']:
        page.locator(f'body > .app-shell > .topbar a[href="{route}"]').click()
        page.wait_for_function('document.body.dataset.page === '+json.dumps(route))
    assert counts==page.evaluate('({...gpuCounts,renderers:jtApp.metrics.renderers})')
    assert counts['contexts']==counts['renderers']==1,counts
    # A task in a hidden keep-alive page still pauses the only renderer.
    page.evaluate("jtApp.router.pages.get('/').shadow.querySelector('#genApiBtn').setAttribute('aria-busy','true')")
    page.wait_for_function('jtApp.metrics.businessBusy===true')
    page.locator('body > .app-shell > .topbar a[href="/video"]').click()
    assert page.evaluate('jtApp.metrics.businessBusy')
    page.locator('#singularityMotion').click()
    page.wait_for_timeout(300)
    sim=page.evaluate('jtApp.metrics.sim');page.wait_for_timeout(400)
    assert page.evaluate('jtApp.metrics.sim')==sim
    page.evaluate("jtApp.router.pages.get('/').shadow.querySelector('#genApiBtn').removeAttribute('aria-busy')")
    page.wait_for_function('jtApp.metrics.businessBusy===false')
    page.wait_for_timeout(300)
    before=page.evaluate('({frames:jtApp.metrics.frames,t:performance.now()})')
    page.wait_for_timeout(1500)
    after=page.evaluate('({frames:jtApp.metrics.frames,t:performance.now()})')
    page.emulate_media(reduced_motion='reduce')
    expect(page.locator('#singularityMotion')).to_have_attribute('aria-pressed','true')
    metrics=page.evaluate('jtApp.metrics')
    assert not errors,errors
    assert not [r for r in requests if r[0]!='GET']
    result={'width':width,'ui_ready_ms':ui_ready,**counts,**metrics,'software_renderer_fps':round((after['frames']-before['frames'])*1000/(after['t']-before['t']),2)}
    page.close();return result


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--disable-webgl'])
        timings=[measure(browser,legacy,width) for width in [390,1440] for legacy in [True,False]]
        browser.close()
        browser=p.chromium.launch(headless=True,args=['--use-angle=swiftshader','--enable-unsafe-swiftshader'])
        graphics=[gpu(browser,width) for width in [390,1000]]
        browser.close()
    report={'conditions':'Offline local assets; Chromium; GPU metrics use SwiftShader, not physical phone/GPU. No paid calls.', 'loading':timings,'graphics':graphics}
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
