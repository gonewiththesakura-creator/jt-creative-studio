"""Make the repository root importable for every test, however pytest is invoked.

Many tests load server.py with spec_from_file_location; server.py then imports
its sibling modules (video_uploads, membership_media, ...) by plain name.
"""
import sys
import uuid
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[1])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def pytest_configure(config):
    # Windows' shared pytest-of-<user> directory may belong to another login.
    # Isolate default runs inside the worktree; keep explicit release-gate paths.
    if sys.platform == 'win32' and config.option.basetemp is None:
        temp_root = Path(ROOT) / '.pytest_cache' / 'tmp'
        temp_root.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = str(temp_root / ('run-' + uuid.uuid4().hex))
