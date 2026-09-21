"""Final deterministic frontend packaging, after the three authoritative builders."""
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
FRONT = ROOT / 'frontend'
OUT = ROOT / 'static' / 'assets'
USED = set()


def asset(name, text, suffix):
    name = name.replace('.', '-')
    raw = text.encode('utf-8') if isinstance(text, str) else text
    digest = hashlib.sha256(raw).hexdigest()[:12]
    path = OUT / f'{name}.{digest}.{suffix}'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    USED.add(path.name)
    return '/static/assets/' + path.name


def external_images(text):
    def replace(match):
        mime, data = match.groups()
        suffix = {'jpeg': 'jpg', 'svg+xml': 'svg'}.get(mime, mime)
        return asset('preview', base64.b64decode(data), suffix)
    return re.sub(r'data:image/(png|jpeg|webp|gif|svg\+xml);base64,([A-Za-z0-9+/=]+)', replace, text)


def scoped_css(css):
    css = css.replace('html:has(body.singularity)', ':host')
    css = re.sub(r'(?<![\w-])body(?![\w-])', '.jt-page-body', css)
    return re.sub(r'(?<![\w-])html(?![\w-])|:root', ':host', css)


def build():
    USED.clear()
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {'pages': {}}
    built = {}
    def module(path):
        path = path.resolve()
        if path in built:
            return built[path]
        code = path.read_text(encoding='utf8')
        def dependency(spec):
            if spec.startswith('.'):
                target = (path.parent / spec.split('?')[0]).resolve()
            elif spec == 'three':
                target = ROOT / 'static/singularity/vendor/build/three.module.js'
            elif spec.startswith('three/addons/'):
                target = ROOT / 'static/singularity/vendor/examples/jsm' / spec[len('three/addons/'):]
            else:
                return spec
            return module(target)
        code = re.sub(r"\?v='\+new URL\(import.meta.url\).searchParams.get\('v'\)", "'", code)
        imports = json.loads(subprocess.run(['node',str(FRONT/'imports.mjs')],input=json.dumps(code),encoding='utf8',capture_output=True,check=True).stdout)
        for start,end,spec in sorted(imports,reverse=True):
            code = code[:start] + json.dumps(dependency(spec)) + code[end:]
        built[path] = asset(path.stem, code, 'js')
        return built[path]

    manifest['singularity'] = module(ROOT / 'static/singularity/workbench.js')
    asset('three-LICENSE',(ROOT/'static/singularity/vendor/LICENSE').read_bytes(),'txt')
    theme = (ROOT / 'static/singularity/theme.css').read_text(encoding='utf8')
    manifest['main'] = module(FRONT / 'main.js')
    styles = asset('app', theme + '\n' + (FRONT / 'styles/app.css').read_text(encoding='utf8'), 'css')
    for route, name in [('/', 'index'), ('/realism', 'realism'), ('/video', 'video')]:
        html = external_images((ROOT / 'static' / f'{name}.html').read_text(encoding='utf8'))
        title = re.search(r'<title>(.*?)</title>', html, re.S).group(1)
        css = '\n'.join(re.findall(r'<style[^>]*>(.*?)</style>', html, re.S))
        body = re.search(r'<body[^>]*>(.*?)</body>', html, re.S).group(1)
        scripts = re.findall(r'<script>(.*?)</script>', body, re.S)
        body = re.sub(r'<script\b[^>]*>.*?</script>', '', body, flags=re.S)
        code = '\n'.join(scripts)
        if name == 'index':
            source = re.search(r'const STYLE_CONFIG_URL="([^"]+)"', code).group(1)
            profiles = json.loads((ROOT / source.lstrip('/')).read_text(encoding='utf8'))
            profile_urls = {key: asset('style-'+key, external_images(json.dumps(value,ensure_ascii=False,separators=(',', ':'))), 'json') for key,value in profiles.items()}
            code = 'const STYLE_ASSETS=' + json.dumps(profile_urls) + ';\n' + code
        compiled = subprocess.run(['node', str(FRONT / 'compile-page.mjs')], input=json.dumps({
            'code': code, 'ids': re.findall(r'\bid="([^"]+)"', body), 'creator': name == 'index',
            'styleLoader': (FRONT / 'pages/creator/style-data.js').read_text(encoding='utf8'),
        }), encoding='utf8', capture_output=True, check=True).stdout
        manifest['pages'][route] = {
            'module': asset(name, compiled, 'js'),
            'markup': asset(name, body, 'html'),
            'css': asset(name, scoped_css(css + '\n' + theme) + '\n' + (FRONT/'styles/page.css').read_text(encoding='utf8'), 'css'),
            'title': title,
        }
    shell = (FRONT / 'index.html').read_text(encoding='utf8').replace('__APP_CSS__', styles).replace('__APP_MAIN__', manifest['main']).replace('__APP_MANIFEST__', json.dumps(manifest,ensure_ascii=False).replace('<','\\u003c'))
    (ROOT/'static/app.html').write_text(shell,encoding='utf8')
    manifest['assets'] = ['/static/assets/'+name for name in sorted(USED)]
    (ROOT/'static/app-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    # This directory is owned exclusively by this deterministic build. Remove
    # superseded content-addressed outputs locally, never on a running server.
    for path in OUT.iterdir():
        if path.is_file() and path.name not in USED and re.fullmatch(r'[\w.-]+\.[0-9a-f]{12}\.[\w]+',path.name):
            path.unlink()
    print(json.dumps({'shell_bytes':len(shell.encode()),'pages':manifest['pages']},ensure_ascii=False))


if __name__ == '__main__':
    build()
