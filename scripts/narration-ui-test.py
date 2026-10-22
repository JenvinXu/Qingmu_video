"""Exercise editable narration stages with real reusable local media."""

import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
import argparse
import httpx
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:4388")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
out = root / "data/reports"
token = (root / "data/session-token").read_text(encoding="utf-8").strip()
client = httpx.Client(
    base_url=args.url, headers={"Authorization": "Bearer " + token}, timeout=30
)
assets = client.get("/api/assets").json()
image = next(a for a in assets if a["kind"] == "image" and a["source"] == "generated")
project = client.post(
    "/api/projects",
    json={
        "kind": "narration",
        "title": "UI验收 • 分步口播",
        "prompt": "午后窗边",
        "scene_count": 2,
    },
).json()
errors = []


def read():
    return client.get("/api/projects/" + project["id"]).json()


def wait_value(predicate):
    deadline = time.monotonic() + 15
    while not predicate(read()):
        assert time.monotonic() < deadline
        time.sleep(0.2)


try:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(
            "http://127.0.0.1:5178/#" + urlencode({"api": args.url, "token": token})
        )
        page.get_by_role(
            "button", name="打开作品" + project["title"], exact=True
        ).click()
        assert page.get_by_role("textbox", name="我的想法", exact=True).is_visible()
        page.get_by_role("textbox", name="我的想法", exact=True).fill(
            "午后窗边，给自己片刻安静"
        )
        page.get_by_role("button", name="口播文案", exact=True).click()
        wait_value(lambda p: p["prompt"] == "午后窗边，给自己片刻安静")
        text = "午后的阳光落在窗边。放下手机，给自己片刻安静。"
        page.get_by_role("textbox", name="口播文案", exact=True).fill(text)
        page.get_by_role("button", name="画面设置", exact=True).click()
        wait_value(lambda p: p["script"] == text)
        page.get_by_label("片段数量").fill("2")
        page.get_by_role("button", name="应用数量", exact=True).click()
        cards = page.locator(".storyboard-card")
        assert cards.count() == 2
        cards.nth(0).get_by_label("口播内容").fill("午后的阳光落在窗边。")
        cards.nth(1).get_by_label("口播内容").fill("放下手机，给自己片刻安静。")
        cards.nth(0).get_by_label("画面与动作").fill("阳光照进窗边")
        # Switching away saves unsaved storyboard edits.
        page.get_by_role("button", name="画面制作", exact=True).click()
        wait_value(
            lambda p: len(p["scenes"]) == 2
            and p["scenes"][0]["description"] == "阳光照进窗边"
        )
        page.locator(".timeline-clip").nth(1).wait_for()
        assert page.locator(".timeline-clip").count() == 2
        page.get_by_label("画面提示词").fill("午后阳光，绿色窗帘")
        page.locator(".timeline-clip").nth(1).click()
        wait_value(lambda p: p["scenes"][0]["image_prompt"] == "午后阳光，绿色窗帘")
        page.get_by_role("button", name="选择图片或视频", exact=True).click()
        page.get_by_role("dialog").locator(
            '[data-asset-id="' + image["id"] + '"]'
        ).click()
        page.get_by_role("button", name="确认选择", exact=True).click()
        page.get_by_role("button", name="保存设置", exact=True).click()
        wait_value(lambda p: p["scenes"][1]["first_frame_id"] == image["id"])
        page.locator(".timeline-clip").nth(1).get_by_text("已生成").wait_for()
        assert "已生成" in page.locator(".timeline-clip").nth(1).inner_text()
        page.get_by_role("button", name="声音字幕", exact=True).click()
        page.get_by_label("片段声音").select_option("zh-CN-YunxiNeural")
        page.get_by_label("此段口播").fill("放下手机，享受这片刻安静。")
        page.get_by_label("自动字幕").uncheck()
        page.get_by_role("button", name="视频合成", exact=True).click()
        wait_value(
            lambda p: p["scenes"][1]["voice"] == "zh-CN-YunxiNeural"
            and not p["subtitles"]
            and "享受这片刻安静" in p["script"]
        )
        assert page.get_by_role("button", name="合成视频", exact=True).is_disabled()
        page.set_viewport_size({"width": 1100, "height": 780})
        for index, name in enumerate(
            ("我的想法", "口播文案", "画面设置", "画面制作", "声音字幕", "视频合成"), 1
        ):
            page.get_by_role("button", name=name, exact=True).click()
            page.wait_for_timeout(300)
            assert page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth"
            ), name
            if index >= 4:
                box = page.locator(".timeline").bounding_box()
                assert box and box["y"] + box["height"] <= 780, (name, box)
            page.screenshot(
                path=str(out / f"narration-step-{index}.png"), full_page=True
            )
        assert not errors, errors
        browser.close()
    (out / "narration-ui-test.json").write_text(
        json.dumps(
            {
                "status": "passed",
                "page_errors": errors,
                "checks": [
                    "六步独立页面",
                    "想法/文案/片段切换自动保存",
                    "逐片段画面与声音配置",
                    "真实素材选择与图片就绪状态",
                    "缺媒体时阻止合成",
                    "1100px 首屏时间线与无水平溢出",
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("NARRATION_UI_TEST_PASSED")
finally:
    client.delete("/api/projects/" + project["id"]).raise_for_status()
