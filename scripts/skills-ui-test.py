"""Verify the packaged Skills UI and the generated drama in the real Electron renderer."""

import json
from pathlib import Path
import sys
import time

from playwright.sync_api import sync_playwright


sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "data" / "reports"
PROJECT_TITLE = "《最后一盏灯》· Skills 验收"


with sync_playwright() as playwright:
    browser = playwright.chromium.connect_over_cdp("http://127.0.0.1:9225")
    page = browser.contexts[0].pages[0]
    page.set_default_timeout(10_000)
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    page.get_by_role("button", name="提示词库", exact=True).click()
    page.get_by_role("heading", name="提示词库", exact=True).wait_for()
    page.get_by_role("button", name="创作 Skills", exact=True).click()
    expected = [
        "Screenwriting · 剧情编剧",
        "Visual Video · 视听分镜",
        "Agnes · 生成提示适配",
    ]
    for title in expected:
        page.get_by_role("button", name=title, exact=True).wait_for()
    textarea = page.get_by_role("textbox", name="步骤提示词", exact=True)
    screenwriting_text = textarea.input_value()
    assert "五段递进" in screenwriting_text
    assert "人物" in screenwriting_text and "对白" in screenwriting_text

    page.get_by_role("button", name="Visual Video · 视听分镜", exact=True).click()
    visual_text = textarea.input_value()
    for keyword in ("运镜", "光线", "声音", "剪辑", "image_prompt", "video_prompt"):
        assert keyword in visual_text, keyword

    page.get_by_role("button", name="Agnes · 生成提示适配", exact=True).click()
    assert "Agnes" in textarea.input_value()
    assert textarea.is_editable()
    page.screenshot(path=str(REPORTS / "skills-prompt-library.png"), full_page=True)
    print("PROMPT_LIBRARY_OK", flush=True)

    page.get_by_role("button", name="我的作品", exact=True).click()
    page.get_by_role("button", name="打开作品" + PROJECT_TITLE, exact=True).click()
    page.get_by_role("button", name="视频文案", exact=True).click()
    production_bible = page.locator("details.production-bible")
    production_bible.wait_for()
    if production_bible.get_attribute("open") is None:
        production_bible.locator("summary").click()
    production_bible.locator("pre").filter(has_text="主题与前提").wait_for()
    page.get_by_role("button", name="视频制作", exact=True).click()
    page.get_by_role("button", name="智能优化", exact=True).wait_for()
    page.get_by_role("button", name="制作全部", exact=True).wait_for()
    video = page.locator("video").first
    video.wait_for()
    print("DRAMA_PAGE_OK", flush=True)
    deadline = time.monotonic() + 20
    while video.evaluate("node => node.readyState") < 2:
        if time.monotonic() > deadline:
            raise TimeoutError("短剧视频未能在正式桌面加载")
        page.wait_for_timeout(200)
    assert video.evaluate("node => node.videoWidth") == 1280
    before = video.evaluate("node => node.currentTime")
    video.evaluate("node => { void node.play(); return true; }")
    page.wait_for_timeout(900)
    assert video.evaluate("node => node.currentTime") > before
    video.evaluate("node => node.pause()")
    page.screenshot(path=str(REPORTS / "skills-drama-desktop.png"), full_page=True)
    print("VIDEO_PLAYBACK_OK", flush=True)

    assert not page_errors, page_errors
    report = {
        "status": "passed",
        "packaged": True,
        "project": PROJECT_TITLE,
        "prompt_group": "创作 Skills",
        "prompt_templates": expected,
        "checks": [
            "三项创作提示词在真实打包界面可见",
            "系统提示词文本可编辑",
            "视听提示覆盖运镜、光线、声音与剪辑",
            "制作设计在作品内可见",
            "60 秒短剧分镜视频可播放",
        ],
        "page_errors": page_errors,
    }
    (REPORTS / "skills-ui-acceptance.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("SKILLS_UI_ACCEPTANCE_PASSED")
