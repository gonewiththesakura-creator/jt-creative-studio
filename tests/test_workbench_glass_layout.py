"""Render freshly built pages without scripts/network or paid workflow calls."""
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def built_pages(tmp_path_factory):
    root = tmp_path_factory.mktemp("glass-build")
    (root / "sources").mkdir()
    shutil.copy2(ROOT / "workbench_theme.py", root / "workbench_theme.py")
    shutil.copytree(ROOT / "static" / "singularity", root / "static" / "singularity")
    (root / "static" / "previews").mkdir(parents=True)
    for name in ("video_business.js", "workbench_glass.css"):
        source = ROOT / "sources" / name
        if source.exists():
            shutil.copy2(source, root / "sources" / name)
    for source in (ROOT / "static" / "previews").glob("realism-*.webp"):
        shutil.copy2(source, root / "static" / "previews" / source.name)
    for name in ("realism", "video"):
        builder = f"build_{name}_workbench.py"
        shutil.copy2(ROOT / builder, root / builder)
        subprocess.run([sys.executable, str(root / builder)], check=True, capture_output=True)
    return {
        name: (root / "static" / f"{name}.html").read_text(encoding="utf8")
        for name in ("realism", "video")
    }


def render_without_network(page, html):
    page.set_content(re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S))


def render_real_task_card(page, html, name):
    # Run only actual task DOM factories; omit boot code and provider requests.
    functions = ["createTaskCard"] if name == "realism" else ["fmtTime", "refreshTaskCount", "addTaskCard"]
    code = "const tasks = new Map();\n" + "\n".join(
        re.search(r"function " + function + r"\([^\n]+", html).group(0)
        for function in functions
    )
    page.add_script_tag(content=code)
    page.evaluate("""name => {
        if(name === 'realism') document.querySelector('#taskList').append(createTaskCard('fixture-task','测试任务').card);
        else addTaskCard('fixture-task','测试任务');
        document.querySelector('.task-view').hidden = false;
    }""", name)


@pytest.fixture(scope="module")
def browser():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.mark.parametrize("name", ["realism", "video"])
@pytest.mark.parametrize("width", [320, 390, 820])
def test_phone_footer_stays_in_flow_and_long_tasks_fit(browser, built_pages, name, width):
    page = browser.new_page(viewport={"width": width, "height": 844})
    try:
        render_without_network(page, built_pages[name])
        render_real_task_card(page, built_pages[name], name)
        page.evaluate("""() => {
            document.querySelector('.creation-scroll').insertAdjacentHTML('beforeend', '<div class="control form"><textarea aria-label="测试提示词">长提示词</textarea></div>');
            document.querySelector('.status').textContent = '生成失败：' + 'longfilename'.repeat(32);
            document.querySelector('.task-name').textContent = 'reference_file_'.repeat(30);
            document.querySelector('.task-meta').textContent = '任务恢复中，正在重新读取远程状态。'.repeat(10);
        }""")
        result = page.evaluate("""() => {
            const footer = document.querySelector('.creation-footer');
            const scroll = document.querySelector('.creation-scroll');
            const preview = document.querySelector('.preview-pane');
            const task = document.querySelector('.task-card');
            return {
                position:getComputedStyle(footer).position,
                ordered:footer.getBoundingClientRect().top >= scroll.getBoundingClientRect().bottom - 1 && preview.getBoundingClientRect().top >= footer.getBoundingClientRect().bottom - 1,
                overflow:document.documentElement.scrollWidth > innerWidth,
                taskOverflow:task.scrollWidth > task.clientWidth + 1,
                fontSize:parseFloat(getComputedStyle(scroll.querySelector('textarea')).fontSize),
                closeSize:parseFloat(getComputedStyle(document.querySelector('.close')).minHeight)
            };
        }""")
        assert result["position"] == "static", result
        assert result["ordered"] and not result["overflow"] and not result["taskOverflow"], result
        assert result["fontSize"] >= 16 and result["closeSize"] >= 44, result
    finally:
        page.close()


@pytest.mark.parametrize("name", ["realism", "video"])
def test_background_variables_reach_inert_layer_and_reduced_motion_stops_edges(browser, built_pages, name):
    page = browser.new_page(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
    try:
        render_without_network(page, built_pages[name])
        page.locator('.creation-pane').hover()
        result = page.evaluate("""() => {
            const root = document.documentElement;
            root.style.setProperty('--app-background-image', 'linear-gradient(rgb(0, 0, 0), rgb(255, 0, 0))');
            root.style.setProperty('--app-background-opacity', '.4');
            const layer = document.querySelector('.app-background');
            if (!layer) return {layer:false};
            const background = getComputedStyle(layer, '::before');
            const shell = document.querySelector('.creation-pane');
            return {layer:true, image:background.backgroundImage, opacity:background.opacity,
                inert:getComputedStyle(layer).pointerEvents === 'none',
                edgeMotion:getComputedStyle(shell,'::after').transitionDuration,
                edgeTransform:getComputedStyle(shell,'::after').transform,
                columns:getComputedStyle(document.querySelector('.studio-grid')).gridTemplateColumns.split(' ').length,
                overflow:document.documentElement.scrollWidth > innerWidth};
        }""")
        assert result["layer"] and result["inert"], result
        assert "linear-gradient" in result["image"] and result["opacity"] == "0.4", result
        assert result["edgeMotion"] == "0s" and result["edgeTransform"] == "none", result
        assert result["columns"] == 2 and not result["overflow"], result
    finally:
        page.close()


@pytest.mark.parametrize("name", ["realism", "video"])
def test_phone_library_keeps_close_visible_and_wide_media_inside_scroll(browser, built_pages, name):
    page = browser.new_page(viewport={"width": 320, "height": 640})
    try:
        render_without_network(page, built_pages[name])
        result = page.evaluate("""() => {
            const overlay = document.querySelector('#favOverlay');
            overlay.classList.add('open');
            const list = overlay.querySelector('.library-scroll');
            list.innerHTML = ('<div class="job"><video width="1920" height="1080" controls></video><div class="note">' + 'filename_'.repeat(80) + '</div></div>').repeat(8);
            list.scrollTop = list.scrollHeight;
            const close = overlay.querySelector('.close').getBoundingClientRect();
            const panel = overlay.querySelector('.library-panel').getBoundingClientRect();
            return {closeVisible:close.top >= 0 && close.bottom <= innerHeight,
                closeSize:close.height, panelFits:panel.bottom <= innerHeight,
                scrolls:list.scrollTop > 0, overflow:list.scrollWidth > list.clientWidth,
                mediaFits:list.querySelector('video').getBoundingClientRect().right <= panel.right};
        }""")
        assert result["closeVisible"] and result["closeSize"] >= 44 and result["panelFits"], result
        assert result["scrolls"] and not result["overflow"] and result["mediaFits"], result
    finally:
        page.close()
