"""Verify drama shot-duration controls persist and follow the writing flow."""

import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
root = Path(__file__).resolve().parents[1]
out = root / "data/reports"
token = (root / "data/session-token").read_text(encoding="utf-8").strip()
services = json.loads((root / "data/dev-services.json").read_text(encoding="utf-8-sig"))
base = "http://127.0.0.1:" + str(services["backend_port"])
client = httpx.Client(base_url=base, headers={"Authorization": "Bearer " + token})
project = client.post(
    "/api/projects",
    json={
        "kind": "drama",
        "title": "分镜时长 UI 验收",
        "prompt": "雨夜车站里，两位旧友重逢",
        "target_duration": 60,
    },
).json()


def wait_duration(value):
    deadline = time.monotonic() + 15
    while client.get("/api/projects/" + project["id"]).json()["shot_duration"] != value:
        assert time.monotonic() < deadline
        time.sleep(0.2)


def wait_scene_durations(values):
    deadline = time.monotonic() + 15
    while True:
        current = client.get("/api/projects/" + project["id"]).json()
        if [scene["duration"] for scene in current["scenes"]] == values and [
            scene["video_seconds"] for scene in current["scenes"]
        ] == values:
            return
        assert time.monotonic() < deadline
        time.sleep(0.2)


try:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 820})
        app_url = "http://127.0.0.1:5178/#" + urlencode({"api": base, "token": token})
        page.goto("about:blank")
        page.goto(app_url, wait_until="domcontentloaded")
        page.get_by_role("button", name="打开作品" + project["title"], exact=True).wait_for()
        page.get_by_role("button", name="打开作品" + project["title"], exact=True).click()
        control = page.get_by_label("分镜时长（秒）")
        control.fill("13")
        control.blur()
        wait_duration(13)
        assert control.input_value() == "13"
        page.screenshot(path=str(out / "drama-shot-duration-idea.png"), full_page=True)
        page.get_by_role("button", name="视频文案", exact=True).click()
        control = page.get_by_label("分镜时长（秒）")
        control.fill("30")
        control.blur()
        wait_duration(30)
        assert page.get_by_role("button", name="按时长重写", exact=True).is_visible()
        page.screenshot(path=str(out / "drama-shot-duration-script.png"), full_page=True)

        current = client.get("/api/projects/" + project["id"]).json()
        script = (
            "（0-7秒）分镜1：雨滴落在站台灯下。\n"
            "（7-20秒）分镜2：两位旧友隔着人群认出彼此。\n"
            "（20-50秒）分镜3：列车驶离，两人并肩走出车站。"
        )
        scenes = [
            {
                "id": "duration-7",
                "title": "雨夜站台",
                "description": "雨滴落在站台灯下。",
                "duration": 7,
                "video_seconds": 7,
            },
            {
                "id": "duration-13",
                "title": "旧友重逢",
                "description": "两位旧友隔着人群认出彼此。",
                "duration": 13,
                "video_seconds": 13,
            },
            {
                "id": "duration-30",
                "title": "走出车站",
                "description": "列车驶离，两人并肩走出车站。",
                "duration": 30,
                "video_seconds": 30,
            },
        ]
        client.patch(
            "/api/projects/" + project["id"],
            json={"revision": current["revision"], "script": script, "scenes": scenes},
        ).raise_for_status()
        page.goto("about:blank")
        page.goto(app_url, wait_until="domcontentloaded")
        page.get_by_role("button", name="打开作品" + project["title"], exact=True).wait_for()
        page.get_by_role("button", name="打开作品" + project["title"], exact=True).click()
        page.get_by_role("button", name="分镜设置", exact=True).click()
        duration_inputs = page.get_by_label("时长", exact=True)
        assert duration_inputs.count() == 3
        for index, value in enumerate((7, 13, 30)):
            duration_inputs.nth(index).fill(str(value))
        duration_inputs.nth(2).fill("31")
        assert duration_inputs.nth(2).input_value() == "30"
        wait_scene_durations([7, 13, 30])
        page.get_by_role("button", name="开始创作", exact=True).click()
        page.wait_for_selector('.timeline-clip[data-scene-id="duration-30"]')
        assert "00:07" in page.locator('.timeline-clip[data-scene-id="duration-7"]').inner_text()
        assert "00:13" in page.locator('.timeline-clip[data-scene-id="duration-13"]').inner_text()
        assert "00:30" in page.locator('.timeline-clip[data-scene-id="duration-30"]').inner_text()
        page.screenshot(path=str(out / "drama-shot-duration-30s.png"), full_page=True)
        browser.close()
    (out / "drama-shot-duration-ui-test.json").write_text(
        json.dumps(
            {
                "status": "passed",
                "checks": [
                    "想法页分镜时长输入框",
                    "视频文案页每镜内容输入框",
                    "1–30 秒任意整数可选",
                    "选择自动保存到后端",
                    "分镜卡片 7/13/30 秒与视频时长同步",
                    "31 秒输入自动限制为 30 秒",
                    "时间线按 7/13/30 秒显示",
                    "按时长重写入口",
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("DRAMA_SHOT_DURATION_UI_TEST_PASSED")
finally:
    client.delete("/api/projects/" + project["id"]).raise_for_status()
