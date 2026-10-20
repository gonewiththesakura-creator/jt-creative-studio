"""Make the repository root importable for every test, however pytest is invoked.

Many tests load server.py with spec_from_file_location; server.py then imports
its sibling modules (video_uploads, membership_media, ...) by plain name.
"""
import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[1])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
