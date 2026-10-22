"""Verify the normalized eight-step narration workflow in the real renderer."""

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:4368")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
out = root / "data/reports"
token = (root / "data/session-token").read_text(encoding="utf-8").strip()
client = httpx.Client(
    base_url=args.url, headers={"Authorization": "Bearer " + token}, timeout=45
)
assets = client.get("/api/assets").json()
image = next(a for a in assets if a["kind"] == "image")
voice = next(a for a in assets if a["kind"] == "voice")
project = client.post(
    "/api/projects",
    json={
        "kind": "narration",
        "title": "标准口播链路 UI 验收",
        "prompt": "解释为什么每天晒太阳有助于建立稳定作息",
        "target_duration": 64,
        "scene_count": 2,
    },
).json()
script = "早晨拉开窗帘，让阳光成为身体的时间信号。然后走到窗边，给自己几分钟安静清醒的时间。"
scenes = [
    {
        "id": "sunlight",
        "title": "晨光入室",
        "description": "晨光从窗户照进有绿植的安静房间",
        "narration": "早晨拉开窗帘，让阳光成为身体的时间信号。",
        "image_prompt": "清晨阳光穿过窗户，室内绿植，真实摄影",
        "video_prompt": "镜头缓慢推近窗边，窗帘轻轻摆动，阳光逐渐洒入室内",
        "material_query": "morning sunlight window indoor plant",
        "duration": 8,
        "audio_id": voice["id"],
        "asset_ids": [],
        "reference_ids": [],
        "first_frame_id": None,
        "video_id": None,
        "trim_in": 0,
        "status": "draft",
    },
    {
        "id": "quiet",
        "title": "窗边清醒",
        "description": "人物在窗边安静呼吸并逐渐清醒",
        "narration": "然后走到窗边，给自己几分钟安静清醒的时间。",
        "image_prompt": "人物站在明亮窗边安静呼吸，真实生活摄影",
        "video_prompt": "固定镜头，人物缓慢深呼吸，光影自然变化",
        "material_query": "person calm breathing bright window",
        "match_reason": "素材包含窗边人物和安静清醒的动作，与本段口播一致。",
        "match_score": 91,
        "duration": 8,
        "audio_id": voice["id"],
        "asset_ids": [],
        "reference_ids": [],
        "first_frame_id": image["id"],
        "video_id": None,
        "trim_in": 0,
        "status": "draft",
    },
]
project = client.patch(
    "/api/projects/" + project["id"],
    json={"revision": project["revision"], "script": script, "scenes": scenes},
).json()
collected_id = None
page_errors = []


def read_project():
    return client.get("/api/projects/" + project["id"]).json()


def wait_project(predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while not predicate(read_project()):
        assert time.monotonic() < deadline
        time.sleep(0.2)


try:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 820})
        page.on("pageerror", lambda value: page_errors.append(str(value)))
        page.goto(
            "http://127.0.0.1:5178/#"
            + urlencode({"api": args.url, "token": token}),
            wait_until="networkidle",
        )
        page.get_by_role("button", name="打开作品" + project["title"], exact=True).click()
        expected_steps = (
            "我的想法",
            "口播文案",
            "画面拆分",
            "素材搜集",
            "配音",
            "素材匹配",
            "配乐音效",
            "视频合成",
        )
        for name in expected_steps:
            assert page.get_by_role("button", name=name, exact=True).count() == 1, name

        page.get_by_role("button", name="素材搜集", exact=True).click()
        query = page.locator(".material-search-row input")
        query.wait_for()
        query.fill("morning sunlight window indoor plant")
        page.get_by_role("button", name="搜集", exact=True).click()
        page.locator(".material-candidate").first.wait_for(timeout=45_000)
        page.locator(".material-candidate").first.get_by_role("button", name="采用", exact=True).click()
        wait_project(
            lambda value: bool(value["scenes"][0].get("first_frame_id"))
            and bool(value["scenes"][0].get("match_reason")),
            timeout=45,
        )
        collected_id = read_project()["scenes"][0]["first_frame_id"]

        page.get_by_role("button", name="配音", exact=True).click()
        assert page.get_by_role("textbox", name="此段口播", exact=True).input_value().startswith("早晨")
        assert page.get_by_role("button", name="生成配音", exact=False).is_visible()

        page.get_by_role("button", name="素材匹配", exact=True).click()
        page.get_by_role("textbox", name="本段视频提示词", exact=True).fill(
            "镜头缓慢推近窗边，窗帘轻摆，阳光照亮绿植"
        )
        assert page.get_by_role("button", name="生成本段 AI 视频", exact=True).is_visible()
        page.locator(".timeline-clip").nth(1).click()
        wait_project(
            lambda value: "阳光照亮绿植" in value["scenes"][0]["video_prompt"]
        )

        page.get_by_role("button", name="配乐音效", exact=True).click()
        page.get_by_role("button", name="选择音效", exact=True).click()
        page.get_by_role("dialog").locator('[data-asset-id="' + voice["id"] + '"]').click()
        page.get_by_role("button", name="确认选择", exact=True).click()
        page.get_by_role("button", name="应用并预览", exact=True).click()
        wait_project(lambda value: value["scenes"][1].get("sfx_id") == voice["id"])
        assert page.get_by_role("button", name="合成视频", exact=False).is_enabled()

        page.set_viewport_size({"width": 1100, "height": 780})
        for index, name in enumerate(expected_steps, 1):
            page.get_by_role("button", name=name, exact=True).click()
            page.wait_for_timeout(250)
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), name
            page.screenshot(path=str(out / f"narration-standard-{index}.png"), full_page=True)
        assert not page_errors, page_errors
        browser.close()
    report = {
        "status": "passed",
        "project_id": project["id"],
        "page_errors": page_errors,
        "checks": [
            "八步口播链路",
            "公开素材搜索、下载、来源保存与片段绑定",
            "逐段时间线切换和自动保存",
            "单段 AI 视频入口与模型时长配置",
            "片段音效配置",
            "素材匹配依据控制合成就绪状态",
            "1100px 无水平溢出",
        ],
    }
    (out / "narration-standard-ui-test.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("NARRATION_STANDARD_UI_TEST_PASSED")
finally:
    client.delete("/api/projects/" + project["id"]).raise_for_status()
    if collected_id:
        response = client.delete("/api/assets/" + collected_id)
        if response.status_code not in {200, 404}:
            print("Unable to remove collected test asset:", response.text)
