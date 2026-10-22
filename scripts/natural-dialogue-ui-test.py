"""Verify the packaged short-drama natural-dialogue UI and preview audio path."""

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

    page.get_by_role("button", name="我的作品", exact=True).click()
    page.get_by_role("heading", name="我的作品", exact=True).wait_for()
    page.get_by_role("button", name="打开作品" + PROJECT_TITLE, exact=True).click()

    page.get_by_role("button", name="分镜设置", exact=True).click()
    page.get_by_text("人物对白 · 视频自然发声", exact=True).first.wait_for()
    speaker_selects = page.locator("select[aria-label$='说话角色']")
    dialogue_boxes = page.locator("label:has-text('人物对白 · 视频自然发声') textarea")
    narration_boxes = page.locator("label:has-text('画外旁白（可选）') textarea")
    assert speaker_selects.count() == 6
    assert dialogue_boxes.count() == 6
    assert narration_boxes.count() == 6
    assert sum(bool(dialogue_boxes.nth(index).input_value().strip()) for index in range(6)) == 4
    assert all(not narration_boxes.nth(index).input_value().strip() for index in range(6))
    assert sum(bool(speaker_selects.nth(index).input_value()) for index in range(6)) == 4
    dialogue_index = next(
        index for index in range(6) if dialogue_boxes.nth(index).input_value().strip()
    )
    page.screenshot(path=str(REPORTS / "drama-natural-dialogue-storyboard.png"), full_page=True)
    print("STORYBOARD_DIALOGUE_UI_OK", flush=True)

    page.get_by_role("button", name="视频制作", exact=True).click()
    page.locator(".timeline-clip").nth(dialogue_index).click()
    page.get_by_role("button", name="视频制作", exact=True).last.click()
    page.locator("label:has-text('人物对白 · 视频自然发声')").wait_for()
    dialogue = page.locator("label:has-text('人物对白 · 视频自然发声') textarea")
    assert dialogue.input_value().strip()
    assert page.get_by_role("combobox", name="说话角色", exact=True).input_value()

    video = page.locator("section.sequence-preview video")
    video.wait_for()
    deadline = time.monotonic() + 20
    while video.evaluate("node => node.readyState") < 2:
        if time.monotonic() > deadline:
            raise TimeoutError("短剧分镜视频未能加载")
        page.wait_for_timeout(200)
    assert video.evaluate("node => node.muted") is False
    assert video.evaluate("node => node.volume") == 1
    assert page.locator("section.sequence-preview audio:not([loop])").count() == 0
    caption = page.locator("section.sequence-preview .caption-preview")
    assert caption.inner_text().strip() == dialogue.input_value().strip()
    before = video.evaluate("node => node.currentTime")
    video.evaluate("node => { void node.play(); return true; }")
    page.wait_for_timeout(900)
    assert video.evaluate("node => node.currentTime") > before
    video.evaluate("node => node.pause()")
    page.screenshot(path=str(REPORTS / "drama-natural-dialogue-production.png"), full_page=True)

    assert not page_errors, page_errors
    report = {
        "status": "passed",
        "packaged": True,
        "project": PROJECT_TITLE,
        "scene_count": 6,
        "dialogue_scene_count": 4,
        "narration_scene_count": 0,
        "external_tts_tracks": 0,
        "preview": {
            "video_muted": False,
            "video_volume": 1,
            "separate_voice_elements": 0,
            "dialogue_caption_visible": True,
            "playback_advanced": True,
        },
        "page_errors": page_errors,
    }
    (REPORTS / "drama-natural-dialogue-ui.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("NATURAL_DIALOGUE_UI_PASSED")
