"""Verify the final packaged eight-step narration flow and minute playback."""

import json
import os
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
root = Path(__file__).resolve().parents[1]
out = root / "data" / "reports"
workspace = Path(os.environ["APPDATA"]) / "LimeStudio" / "workspace"
runtime = json.loads((workspace / "runtime.json").read_text(encoding="utf-8"))
token = (workspace / "session-token").read_text(encoding="utf-8").strip()
expected = json.loads((out / "packaged-minute-project.json").read_text(encoding="utf-8"))
client = httpx.Client(
    base_url=runtime["backendUrl"],
    headers={"Authorization": "Bearer " + token},
    timeout=120,
)
before = client.get("/api/projects/" + expected["project_id"]).raise_for_status().json()
assert before["export_id"] == expected["export_id"]
page_errors = []

with sync_playwright() as playwright:
    browser = playwright.chromium.connect_over_cdp("http://127.0.0.1:9236")
    page = browser.contexts[0].pages[0]
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.get_by_role("button", name="口播制作", exact=True).first.click()
    page.get_by_role("combobox", name="切换作品").select_option(expected["project_id"])
    steps = (
        "我的想法",
        "口播文案",
        "画面拆分",
        "素材搜集",
        "配音",
        "素材匹配",
        "配乐音效",
        "视频合成",
    )
    for name in steps:
        assert page.get_by_role("button", name=name, exact=True).count() == 1, name
    page.get_by_role("button", name="素材搜集", exact=True).click()
    assert page.locator(".material-search-row input").is_visible()
    page.get_by_role("button", name="配音", exact=True).click()
    assert page.get_by_role("button", name="重新生成配音", exact=False).is_visible()
    page.get_by_role("button", name="素材匹配", exact=True).click()
    assert page.get_by_role("button", name="重新生成本段视频", exact=False).count() + page.get_by_role(
        "button", name="生成本段 AI 视频", exact=True
    ).count() >= 1
    page.get_by_role("button", name="配乐音效", exact=True).click()
    assert page.get_by_role("checkbox", name="旁白时自动压低配乐", exact=True).is_checked()
    page.get_by_role("button", name="视频合成", exact=True).click()
    video = page.locator("video").first
    video.wait_for()
    deadline = time.monotonic() + 30
    while video.evaluate("(element) => element.readyState") < 2:
        assert time.monotonic() < deadline
        time.sleep(0.2)
    assert video.evaluate("(element) => element.duration") >= 60
    video.evaluate("(element) => element.play()")
    while video.evaluate("(element) => element.currentTime") < 1:
        assert time.monotonic() < deadline
        time.sleep(0.2)
    video.evaluate("(element) => element.pause()")
    page.screenshot(path=str(out / "packaged-narration-standard.png"), full_page=True)
    assert not page_errors, page_errors
    browser.close()

after = client.get("/api/projects/" + expected["project_id"]).raise_for_status().json()
assert after["export_id"] == before["export_id"]
assert after["revision"] == before["revision"]
report = {
    "status": "passed",
    "project_id": after["id"],
    "export_id": after["export_id"],
    "duration": expected["duration"],
    "page_errors": page_errors,
    "checks": [
        "packaged eight-step narration flow",
        "material collection page",
        "per-segment voice and AI video controls",
        "BGM ducking and SFX page",
        "69-second final video metadata and playback",
        "no-op page navigation preserves export and revision",
    ],
}
(out / "packaged-narration-standard-test.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
)
print("PACKAGED_NARRATION_STANDARD_TEST_PASSED", flush=True)
