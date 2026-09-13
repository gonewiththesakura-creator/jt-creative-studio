from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
VIDEO=(ROOT/'sources/video_business.js').read_text(encoding='utf8')
VIDEO_BUILD=(ROOT/'build_video_workbench.py').read_text(encoding='utf8')
CREATOR=(ROOT/'build_unified_three_styles.py').read_text(encoding='utf8')
REALISM=(ROOT/'build_realism_workbench.py').read_text(encoding='utf8')

def test_video_uses_one_main_viewer_with_horizontal_thumbnails():
    for token in ('mediaGallery','galleryMain','galleryThumbs','galleryPrev','galleryNext','selectGalleryItem'):
        assert token in VIDEO or token in VIDEO_BUILD, token
    assert 'overflow-x:auto' in VIDEO_BUILD
    assert 'scroll-snap-type:x mandatory' in VIDEO_BUILD
    assert "resEl.appendChild(createVideoResult" not in VIDEO
    assert ".studio-grid{display:grid" in VIDEO_BUILD and "min-height:0" in VIDEO_BUILD
    assert ".preview-pane{display:flex" in VIDEO_BUILD
    assert ".preview-stage{position:relative;flex:1;min-height:0" in VIDEO_BUILD

def test_creator_and_realism_use_single_main_media_gallery():
    for source in (CREATOR,REALISM):
        assert 'media-gallery' in source
        assert 'gallery-thumbs' in source
        assert 'gallery-prev' in source and 'gallery-next' in source

def test_creator_hides_numeric_progress_labels():
    assert 'class="liquid-percent"' not in CREATOR
    assert "Math.round(pct)+'%'" not in CREATOR
    assert "Math.round(lastProgress)+'%'" not in CREATOR
