"""Attach the self-contained Singularity skin without rewriting business scripts."""
from pathlib import Path
import hashlib

ROOT = Path(__file__).resolve().parent


def apply_workbench_theme(html):
    assets = ROOT / 'static' / 'singularity'
    digest = hashlib.sha256()
    for path in sorted(assets.rglob('*')):
        if path.is_file():
            digest.update(path.relative_to(assets).as_posix().encode())
            digest.update(path.read_bytes().replace(b'\r\n', b'\n'))
    version = digest.hexdigest()[:12]
    head = ('<!-- singularity:start -->'
            f'<link rel="stylesheet" href="/static/singularity/theme.css?v={version}">'
            '<script type="importmap">{"imports":{"three":"/static/singularity/vendor/build/three.module.js",'
            '"three/addons/":"/static/singularity/vendor/examples/jsm/"}}</script>'
            f'<script type="module" src="/static/singularity/workbench.js?v={version}"></script>'
            '<!-- singularity:end -->')
    return html.replace('</head>', head + '</head>').replace('<body>', '<body class="singularity">')
