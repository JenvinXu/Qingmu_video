"""Exercise the workbench with real existing clips and isolated editable projects."""

from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
import httpx
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:4368")
args = parser.parse_args()
token = (root / "data/session-token").read_text(encoding="utf-8").strip()
out = root / "data/reports"
out.mkdir(exist_ok=True)
client = httpx.Client(
    base_url=args.url, headers={"Authorization": "Bearer " + token}, timeout=30
)
assets = client.get("/api/assets").json()
for previous in client.get("/api/projects").json():
    if previous["title"] == "UI验收 • 连续预览" and [
        scene["id"] for scene in previous["scenes"]
    ] == ["ui-scene-0", "ui-scene-1", "ui-scene-2"]:
        client.delete("/api/projects/" + previous["id"]).raise_for_status()
videos = [
    asset
    for asset in assets
    if asset["kind"] == "video"
    and asset["source"] == "generated"
    and asset["info"]["duration"] >= 4
]
assert videos, "A real generated video fixture is required"
project = client.post(
    "/api/projects",
    json={
        "kind": "drama",
        "title": "UI验收 • 连续预览",
        "aspect": "16:9",
        "scene_count": 3,
    },
).json()
scenes = [
    {
        "id": f"ui-scene-{index}",
        "title": title,
        "description": title,
        "narration": "",
        "image_prompt": "",
        "video_prompt": "",
        "duration": duration,
        "trim_in": trim,
        "asset_ids": [],
        "first_frame_id": None,
        "video_id": video,
        "audio_id": None,
        "status": "draft",
    }
    for index, (title, duration, trim, video) in enumerate(
        [
            ("开场", 1, 0, videos[0]["id"]),
            ("空分镜", 2, 0, None),
            ("结尾", 3, 0.5, videos[-1]["id"]),
        ]
    )
]
response = client.patch(
    "/api/projects/" + project["id"],
    json={
        "revision": project["revision"],
        "scenes": scenes,
        "script": "窗边的青年读信，停顿，然后微笑。",
        "asset_ids": [
            asset["id"] for asset in assets if asset["kind"] in {"character", "prop"}
        ][:16],
    },
)
response.raise_for_status()
project = response.json()
errors = []
with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(
        viewport={"width": 1480, "height": 960}, device_scale_factor=1
    )
    page.on("pageerror", lambda error: errors.append(str(error)))

    def snapshot(name):
        page.evaluate("window.scrollTo(0,0)")
        page.wait_for_timeout(350)
        page.screenshot(path=str(out / name), full_page=True)

    page.goto("http://127.0.0.1:5178/#" + urlencode({"api": args.url, "token": token}))
    page.get_by_role("heading", name="我的作品", exact=True).wait_for()
    cards = page.locator(".project-card")
    assert cards.count() >= 2
    boxes = [cards.nth(index).bounding_box() for index in range(2)]
    assert boxes[1]["x"] > boxes[0]["x"] and abs(boxes[0]["y"] - boxes[1]["y"]) < 2
    page.get_by_role("button", name="删除作品" + project["title"], exact=True).click()
    page.get_by_role("dialog").wait_for()
    assert client.get("/api/projects/" + project["id"]).status_code == 200
    page.get_by_role("button", name="取消", exact=True).click()
    assert client.get("/api/projects/" + project["id"]).status_code == 200
    snapshot("workbench-projects.png")
    page.get_by_role("button", name="打开作品" + project["title"], exact=True).click()
    workflow = page.locator(".workflow-tabs")
    workflow.wait_for()
    assert (
        workflow.get_by_role("button", name="视频制作", exact=True).get_attribute(
            "aria-current"
        )
        == "step"
    )
    for name in ("我的想法", "视频文案", "资产配置", "分镜设置", "视频制作"):
        workflow.get_by_role("button", name=name, exact=True).click()
        page.wait_for_timeout(200)
        assert (
            workflow.get_by_role("button", name=name, exact=True).get_attribute(
                "aria-current"
            )
            == "step"
        )
        if name == "视频文案":
            assert (
                page.get_by_role("textbox", name="视频文案", exact=True).input_value()
                == project["script"]
            )
        if name == "资产配置":
            assert page.get_by_role("button", name="一键分镜", exact=True).is_visible()
        if name == "分镜设置":
            assert page.locator(".storyboard-card").count() == 3
    page.get_by_role("button", name="图片参考", exact=True).click()
    assert page.get_by_label("首帧提示词").count() == 1
    assert page.get_by_role("button", name="生成首帧", exact=True).is_visible()
    assert page.get_by_role("button", name="选择生成首帧模型", exact=True).is_visible()
    page.get_by_role("button", name="全部参考", exact=True).click()
    page.locator(".reference-maker").get_by_role(
        "button", name="视频制作", exact=True
    ).click()
    for label in (
        "视频比例",
        "视频时长",
        "视频画质",
    ):
        assert page.get_by_label(label).count() == 1, label
    assert page.get_by_role("button", name="选择生成视频模型", exact=True).is_visible()
    timeline = page.locator(".timeline").bounding_box()
    assert timeline and timeline["y"] + timeline["height"] <= 960, timeline
    clips = page.locator(".timeline-clip")
    widths = [clips.nth(index).bounding_box()["width"] for index in range(3)]
    assert (
        abs(widths[1] / widths[0] - 2) < 0.03 and abs(widths[2] / widths[0] - 3) < 0.03
    ), widths
    clips.nth(1).click()
    assert page.locator(".scene-maker-heading strong").inner_text() == "输入参考"
    assert page.locator(".scene-maker-heading span").inner_text() == "空分镜"
    assert page.locator(".sequence-stage video").count() == 0
    clips.nth(2).click()
    assert page.locator(".scene-maker-heading span").inner_text() == "结尾"
    page.get_by_role("button", name="整片预览", exact=True).click()
    page.get_by_role("button", name="播放整片", exact=True).click()
    deadline = time.monotonic() + 15
    while not page.locator(".sequence-stage video").evaluate(
        "(v) => v.dataset.sceneId === 'ui-scene-2' && v.currentTime > .6"
    ):
        assert time.monotonic() < deadline, (
            "Sequential preview did not skip to the last generated scene"
        )
        time.sleep(0.2)
    page.get_by_role("button", name="播放整片", exact=True).wait_for(timeout=15000)
    assert abs(float(page.get_by_label("预览进度").input_value()) - 4) < 0.1
    snapshot("workbench-drama.png")
    page.get_by_role("button", name="分镜设置", exact=True).click()
    assert page.get_by_label("分镜数量").count() == 0
    page.get_by_role("button", name="添加分镜", exact=True).click()
    assert page.locator(".storyboard-card").count() == 4
    page.get_by_role("button", name="删除分镜 4", exact=True).click()
    page.get_by_role("button", name="取消", exact=True).click()
    assert page.locator(".storyboard-card").count() == 4
    page.get_by_role("button", name="删除分镜 4", exact=True).click()
    page.get_by_role("button", name="确认移除", exact=True).click()
    assert page.locator(".storyboard-card").count() == 3
    page.get_by_role("button", name="开始创作", exact=True).click()
    page.locator(".timeline-clip").nth(2).click()
    page.get_by_role("button", name="图片参考", exact=True).click()
    page.get_by_role("button", name="选择生成首帧模型", exact=True).click()
    page.get_by_role("menu").get_by_role(
        "button", name="自定义模型…", exact=True
    ).click()
    page.get_by_label("自定义生成首帧模型", exact=True).fill("qa-image-model")
    page.get_by_label("自定义生成首帧模型", exact=True).press("Enter")
    page.locator(".reference-maker").get_by_role(
        "button", name="视频制作", exact=True
    ).click()
    page.get_by_role("button", name="选择生成视频模型", exact=True).click()
    page.get_by_role("menu").get_by_role(
        "button", name="自定义模型…", exact=True
    ).click()
    page.get_by_label("自定义生成视频模型", exact=True).fill("qa-video-model")
    page.get_by_label("自定义生成视频模型", exact=True).press("Enter")
    page.get_by_label("视频比例").select_option("16:9")
    page.get_by_label("视频时长").fill("4")
    page.get_by_role("button", name="全部参考", exact=True).click()
    for kind, label in [("character", "选择角色"), ("prop", "选择物品")]:
        candidates = [asset for asset in assets if asset["kind"] == kind]
        if candidates:
            page.get_by_role(
                "button",
                name="角色参考" if kind == "character" else "物品参考",
                exact=True,
            ).click()
            page.get_by_role("button", name=label, exact=True).click()
            page.get_by_role("dialog").get_by_role(
                "button", name=candidates[0]["name"], exact=True
            ).click()
            page.get_by_role("button", name="确定", exact=True).click()
    page.locator(".reference-maker").get_by_role(
        "button", name="视频制作", exact=True
    ).click()
    page.locator(".scene-advanced summary").click()
    page.get_by_label("剪辑时长", exact=True).fill("4")
    page.get_by_role("button", name="视频文案", exact=True).click()
    deadline = time.monotonic() + 20
    while True:
        saved = client.get("/api/projects/" + project["id"]).json()["scenes"][2]
        if (
            saved["image_model"] == "qa-image-model"
            and saved["video_model"] == "qa-video-model"
            and saved["duration"] == 4
        ):
            break
        assert time.monotonic() < deadline, {
            key: saved[key]
            for key in ["title", "image_model", "video_model", "duration"]
        }
        page.wait_for_timeout(100)
    assert (
        saved["image_model"] == "qa-image-model"
        and saved["video_model"] == "qa-video-model"
    )
    assert (
        saved["aspect"] == "16:9"
        and saved["video_seconds"] == 4
        and saved["duration"] == 4
    )
    assert saved["video_id"] is None
    workflow.get_by_role("button", name="视频制作", exact=True).click()
    page.get_by_role("button", name="智能优化", exact=True).click()
    assert page.get_by_role("button", name="执行", exact=True).is_visible()
    page.get_by_role("button", name="关闭", exact=True).click()
    page.get_by_role("button", name="我的作品", exact=True).click()
    page.get_by_role("button", name="删除作品" + project["title"], exact=True).click()
    page.get_by_role("button", name="确认删除", exact=True).click()
    page.get_by_role("dialog").wait_for(state="detached")
    assert client.get("/api/projects/" + project["id"]).status_code == 404
    page.get_by_role("button", name="口播制作", exact=True).click()
    page.get_by_role("heading", name="口播制作", exact=True).wait_for()
    for name in (
        "我的想法",
        "口播文案",
        "画面设置",
        "画面制作",
        "声音字幕",
        "视频合成",
    ):
        assert page.get_by_role("button", name=name, exact=True).is_visible()
    snapshot("workbench-narration.png")
    page.get_by_role("button", name="素材库", exact=True).click()
    page.get_by_role("heading", name="素材库", exact=True).wait_for()
    snapshot("workbench-library.png")
    page.get_by_role("button", name="模型设置", exact=True).click()
    assert page.get_by_role("tab").count() == 3
    assert page.get_by_role("button", name="保存配置", exact=True).count() == 1
    assert (
        all(
            control.input_value() == ""
            for control in page.locator("input[type=password]").all()
        )
        and "cpk-" not in page.content()
        and "bce-v3/ALTAK-" not in page.content()
    )
    snapshot("workbench-settings.png")
    page.get_by_role("button", name="连接与验收", exact=True).click()
    snapshot("workbench-debug.png")
    for name in ("角色库", "物品库"):
        page.get_by_role("button", name=name, exact=True).click()
        page.get_by_role("heading", name=name, exact=True).wait_for()
        assert page.locator(".library-toolbar .filter-tabs").count() == 0
    page.set_viewport_size({"width": 1100, "height": 780})
    for name in (
        "我的作品",
        "短剧制作",
        "口播制作",
        "素材库",
        "模型设置",
        "连接与验收",
    ):
        page.get_by_role("button", name=name, exact=True).first.click()
        page.wait_for_timeout(250)
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        ), name
        if name == "短剧制作":
            box = page.locator(".timeline").bounding_box()
            assert box and box["y"] + box["height"] <= 780, box
    browser.close()
assert not errors, errors
(out / "ui-test.json").write_text(
    json.dumps(
        {
            "status": "passed",
            "page_errors": errors,
            "checks": [
                "作品卡片横向排列",
                "删除前确认及取消/确认分支",
                "五步流程与视频制作默认页",
                "逐分镜必要参数",
                "分镜添加删除确认、自动保存及开始创作",
                "分镜卡片与时长比例占位",
                "真实连续播放跳过空镜头并遵守源入点",
                "口播及素材库导航",
                "密钥隔离",
                "1100px 六页面无溢出及首屏时间线",
            ],
            "screenshots": 6,
        },
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)
print("UI_TEST_PASSED")
