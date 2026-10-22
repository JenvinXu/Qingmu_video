"""Verify the Lei Jun project in the real packaged renderer."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
root = Path(__file__).resolve().parents[1]
reports = root / "data" / "reports"
workspace = Path(os.environ["APPDATA"]) / "LimeStudio" / "workspace"
runtime = json.loads((workspace / "runtime.json").read_text(encoding="utf-8"))
token = (workspace / "session-token").read_text(encoding="utf-8").strip()
expected = json.loads(
    (reports / "packaged-lei-jun-project.json").read_text(encoding="utf-8")
)
client = httpx.Client(
    base_url=runtime["backendUrl"],
    headers={"Authorization": "Bearer " + token},
    timeout=120,
)
project = client.get("/api/projects/" + expected["project_id"]).raise_for_status().json()
assert len(project["scenes"]) == 11
assert all(scene.get("video_id") and scene.get("audio_id") for scene in project["scenes"])
assert project.get("bgm_id")

page_errors: list[str] = []
with sync_playwright() as playwright:
    browser = playwright.chromium.connect_over_cdp("http://127.0.0.1:9237")
    page = browser.contexts[0].pages[0]
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.get_by_role("button", name="口播制作", exact=True).first.click()
    page.get_by_role("combobox", name="切换作品").select_option(project["id"])
    for name in (
        "我的想法",
        "口播文案",
        "画面拆分",
        "素材搜集",
        "配音",
        "素材匹配",
        "配乐音效",
        "视频合成",
    ):
        assert page.get_by_role("button", name=name, exact=True).count() == 1, name
    page.get_by_role("button", name="素材匹配", exact=True).click()
    assert page.get_by_role("button", name="重新生成本段视频", exact=False).count()
    page.get_by_role("button", name="配乐音效", exact=True).click()
    assert page.get_by_role(
        "checkbox", name="旁白时自动压低配乐", exact=True
    ).is_checked()
    page.get_by_role("button", name="视频合成", exact=True).click()
    video = page.locator("video").first
    video.wait_for()
    deadline = time.monotonic() + 30
    while video.evaluate("element => element.readyState") < 2:
        if time.monotonic() > deadline:
            raise TimeoutError("packaged video did not become ready")
        time.sleep(0.2)
    duration = float(video.evaluate("element => element.duration"))
    assert 60 <= duration <= 120, duration
    video.evaluate("element => element.play()")
    while video.evaluate("element => element.currentTime") < 1:
        if time.monotonic() > deadline:
            raise TimeoutError("packaged video did not play")
        time.sleep(0.2)
    video.evaluate("element => element.pause()")
    page.screenshot(path=str(reports / "packaged-lei-jun-ui.png"), full_page=True)
    assert not page_errors, page_errors
    browser.close()

result = {
    "status": "passed",
    "project_id": project["id"],
    "export_id": project["export_id"],
    "duration": duration,
    "scene_count": len(project["scenes"]),
    "page_errors": page_errors,
    "checks": [
        "packaged eight-step narration flow",
        "11/11 video and voice bindings",
        "BGM ducking enabled",
        "final video metadata and actual playback",
    ],
}
(reports / "packaged-lei-jun-ui-test.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
)
print("PACKAGED_LEI_JUN_UI_TEST_PASSED", duration, flush=True)
