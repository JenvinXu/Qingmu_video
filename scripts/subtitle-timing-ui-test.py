"""Verify packaged dialogue subtitle timing controls and preview visibility."""

import json
from pathlib import Path
import sys

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

    page.get_by_role("button", name="我的作品", exact=True).click()
    page.get_by_role("heading", name="我的作品", exact=True).wait_for()
    page.get_by_role("button", name="打开作品" + PROJECT_TITLE, exact=True).click()
    page.get_by_role("button", name="分镜设置", exact=True).click()
    timing_groups = page.locator(".dialogue-timing-fields")
    assert timing_groups.count() == 4
    first_start = timing_groups.first.locator("input").nth(0)
    first_end = timing_groups.first.locator("input").nth(1)
    assert float(first_start.input_value()) == 1.5
    assert float(first_end.input_value()) == 3.99
    page.screenshot(path=str(REPORTS / "subtitle-timing-storyboard.png"), full_page=True)

    page.get_by_role("button", name="视频制作", exact=True).click()
    page.locator(".timeline-clip").nth(1).click()
    page.get_by_role("button", name="视频制作", exact=True).last.click()
    production_timing = page.locator(".scene-dialogue-editor [aria-label='对白字幕时间']:visible")
    production_timing.wait_for()
    assert float(production_timing.locator("input").nth(0).input_value()) == 1.5
    assert float(production_timing.locator("input").nth(1).input_value()) == 3.99

    progress = page.get_by_role("slider", name="预览进度", exact=True)
    caption = page.locator("section.sequence-preview .caption-preview")
    progress.fill("0.8")
    page.wait_for_timeout(150)
    assert caption.count() == 0
    progress.fill("1.8")
    page.wait_for_timeout(150)
    assert caption.is_visible() and caption.inner_text().strip()
    visible_caption = caption.inner_text().strip()
    page.screenshot(path=str(REPORTS / "subtitle-timing-speaking.png"), full_page=True)
    progress.fill("4.2")
    page.wait_for_timeout(150)
    assert caption.count() == 0

    assert not page_errors, page_errors
    report = {
        "status": "passed",
        "packaged": True,
        "project": PROJECT_TITLE,
        "dialogue_scene_count": 4,
        "first_dialogue_window": {"start": 1.5, "end": 3.99},
        "preview_checks": {
            "hidden_before_speech_at": 0.8,
            "visible_during_speech_at": 1.8,
            "visible_caption": visible_caption,
            "hidden_after_speech_at": 4.2,
        },
        "page_errors": page_errors,
    }
    (REPORTS / "subtitle-timing-ui.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("SUBTITLE_TIMING_UI_PASSED", report, flush=True)
