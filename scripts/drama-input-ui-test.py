"""Exercise the current asset-first drama workflow against an actual local service."""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
import httpx
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--native", action="store_true")
parser.add_argument("--generate-character", action="store_true")
parser.add_argument("--url")
args = parser.parse_args()
data = (
    Path(os.environ["APPDATA"]) / "LimeStudio/workspace"
    if args.native
    else root / "data"
)
base = args.url or (
    json.loads((data / "runtime.json").read_text(encoding="utf-8"))["backendUrl"]
    if args.native
    else "http://127.0.0.1:"
    + str(
        json.loads((data / "dev-services.json").read_text(encoding="utf-8-sig"))[
            "backend_port"
        ]
    )
)
token = (data / "session-token").read_text(encoding="utf-8").strip()
client = httpx.Client(
    base_url=base, headers={"Authorization": "Bearer " + token}, timeout=60
)
out = root / "data/reports"
report = {"status": "running", "native": args.native, "checks": [], "page_errors": []}
created = []


def call(method, path, body=None):
    r = client.request(method, path, json=body)
    r.raise_for_status()
    return r.json()


assets = call("GET", "/api/assets")
image = next(a for a in assets if a["kind"] == "image" and a.get("thumbnail"))
voice = next(a for a in assets if a["kind"] == "voice" and a.get("path"))
video = next(
    a
    for a in assets
    if a["kind"] == "video" and a.get("info", {}).get("duration", 0) >= 4
)
prop = next((a for a in assets if a["kind"] == "prop"), None)
project = call("POST", "/api/projects", {"kind": "drama", "title": "参考流程界面验证"})
pid = project["id"]
other = call("POST", "/api/projects", {"kind": "drama", "title": "自动保存隔离验证"})
call(
    "PATCH",
    "/api/projects/" + other["id"],
    {"revision": other["revision"], "script": "其他作品独立文案"},
)


def read():
    return call("GET", "/api/projects/" + pid)


def wait_value(predicate):
    deadline = time.monotonic() + 20
    while not predicate(read()):
        assert time.monotonic() < deadline, read()
        time.sleep(0.15)


try:
    with sync_playwright() as p:
        browser = (
            p.chromium.connect_over_cdp("http://127.0.0.1:9225")
            if args.native
            else p.chromium.launch(channel="msedge", headless=True)
        )
        page = (
            browser.contexts[0].pages[0]
            if args.native
            else browser.new_page(viewport={"width": 1280, "height": 820})
        )
        page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
        if not args.native:
            page.goto(
                "http://127.0.0.1:5178/#" + urlencode({"api": base, "token": token})
            )
        page.reload()
        page.get_by_role("button", name="我的作品", exact=True).wait_for(timeout=15000)
        page.get_by_role("button", name="我的作品", exact=True).click()
        page.get_by_role(
            "button", name="打开作品" + project["title"], exact=True
        ).wait_for(timeout=15000)
        page.get_by_role(
            "button", name="打开作品" + project["title"], exact=True
        ).click()
        page.get_by_role("button", name="视频文案", exact=True).click()
        assert page.get_by_label("分镜数量", exact=True).count() == 0
        assert page.get_by_role("button", name="保存文案", exact=True).count() == 0
        script = "小雨来到窗边，捡起桌上的信封，读完后微笑。"
        page.get_by_role("textbox", name="视频文案", exact=True).fill(script)
        wait_value(lambda v: v["script"] == script and v["scene_count"] is None)
        page.get_by_role("textbox", name="视频文案", exact=True).fill(
            script + "她把信放回桌面。"
        )
        page.get_by_role("button", name="我的作品", exact=True).click()
        wait_value(lambda v: v["script"] == script + "她把信放回桌面。")
        page.get_by_role(
            "button", name="打开作品" + project["title"], exact=True
        ).click()
        page.get_by_role("button", name="选择资产", exact=True).click()
        assert (
            page.locator(".configured-asset").count() == 0
            and page.locator(".drama-asset-tile").count() == 0
        )
        report["checks"].append(
            "默认自动数量，文案自动保存，离开页面即时保存，资产页空白起始"
        )
        page.get_by_role("button", name="视频文案", exact=True).click()
        page.get_by_role("textbox", name="视频文案", exact=True).fill(
            script + "切换前的修改。"
        )
        page.get_by_role("button", name="我的作品", exact=True).click()
        page.get_by_role("button", name="打开作品" + other["title"], exact=True).click()
        wait_value(lambda v: v["script"].endswith("切换前的修改。"))
        assert (
            call("GET", "/api/projects/" + other["id"])["script"] == "其他作品独立文案"
        )
        page.reload()
        page.get_by_role("button", name="我的作品", exact=True).wait_for(timeout=15000)
        page.get_by_role("button", name="我的作品", exact=True).click()
        page.get_by_role(
            "button", name="打开作品" + project["title"], exact=True
        ).click()
        assert (
            page.get_by_role("textbox", name="视频文案", exact=True)
            .input_value()
            .endswith("切换前的修改。")
        )
        page.get_by_role("button", name="选择资产", exact=True).click()
        report["checks"].append("切换作品即时保存且不会覆盖其他作品文案")
        page.get_by_role("button", name="创建角色", exact=True).click()
        dialog = page.get_by_role("dialog")
        create_button = dialog.get_by_role("button", name="创建角色", exact=True)
        assert create_button.is_enabled()
        dialog.get_by_role("button", name="生成照片", exact=True).click()
        dialog.get_by_label("照片提示词", exact=True).fill("中国篮球运动员")
        dialog.get_by_label("角色描述", exact=False).fill("中国篮球运动员")
        create_button.click()
        dialog.get_by_role("alert").get_by_text("请填写角色名称", exact=True).wait_for()
        assert dialog.get_by_label("角色名称", exact=True).evaluate(
            "e => document.activeElement === e"
        )
        dialog.get_by_label("角色名称", exact=True).fill("只有名称的角色")
        assert dialog.get_by_label("照片提示词", exact=True).count() == 1, (
            dialog.inner_text()
        )
        dialog.get_by_label("照片提示词", exact=True).fill("")
        create_button.click()
        dialog.get_by_role("alert").get_by_text(
            "请填写照片提示词，或切换到上传照片", exact=True
        ).wait_for()
        if not args.native:
            page.set_viewport_size({"width": 1100, "height": 600})
        footer = dialog.locator("footer").bounding_box()
        height = page.evaluate("window.innerHeight")
        assert (
            footer and footer["y"] >= 0 and footer["y"] + footer["height"] <= height
        ), footer
        assert create_button.evaluate(
            "e => {const r=e.getBoundingClientRect();return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}"
        )
        page.screenshot(
            path=str(
                out
                / (
                    "character-create-native-validation.png"
                    if args.native
                    else "character-create-validation.png"
                )
            )
        )
        if not args.native:
            page.set_viewport_size({"width": 1440, "height": 900})
        dialog.get_by_role("button", name="上传照片", exact=True).click()
        dialog.get_by_label("角色描述", exact=False).fill("")

        def reject_character(route):
            route.fulfill(
                status=503,
                content_type="application/json",
                body=json.dumps({"detail": "角色服务暂时不可用"}, ensure_ascii=False),
            )

        page.route("**/api/characters", reject_character)
        create_button.click()
        dialog.get_by_role("alert").get_by_text(
            "角色服务暂时不可用", exact=True
        ).wait_for()
        assert create_button.is_enabled()
        page.unroute("**/api/characters", reject_character)
        report["checks"].append(
            "角色名称/照片提示词缺失有明确提示与焦点；创建操作始终可见；只有名称可创建"
        )
        report["checks"].append("接口失败原因在弹窗内可见，保留输入并允许重试")
        dialog.get_by_label("角色名称", exact=True).fill("只有名称的角色")
        dialog.get_by_role("button", name="创建角色", exact=True).click()
        dialog.wait_for(state="detached")
        wait_value(lambda v: len(v["asset_ids"]) == 1)
        name_only = read()["asset_ids"][0]
        created.append(name_only)
        assert (
            next(a for a in call("GET", "/api/assets") if a["id"] == name_only)["path"]
            == ""
        )
        page.get_by_role("button", name="角色库", exact=True).click()
        page.get_by_text("只有名称的角色", exact=True).wait_for()
        page.get_by_text("只有名称的角色", exact=True).click()
        page.get_by_role("dialog").get_by_text("未设置角色照片", exact=True).wait_for()
        assert page.get_by_role("dialog").locator("img").count() == 0
        page.get_by_role("button", name="关闭", exact=True).click()
        page.get_by_role("button", name="我的作品", exact=True).click()
        page.get_by_role(
            "button", name="打开作品" + project["title"], exact=True
        ).click()
        page.get_by_role("button", name="选择资产", exact=True).click()
        page.get_by_role("button", name="创建角色", exact=True).click()
        dialog = page.get_by_role("dialog")
        dialog.get_by_label("角色名称", exact=True).fill("小雨上传照片声音")
        dialog.get_by_label("上传角色照片", exact=True).set_input_files(
            str(data / "media" / image["path"])
        )
        dialog.get_by_alt_text("角色照片").wait_for()
        dialog.get_by_label("上传角色声音", exact=True).set_input_files(
            str(data / "media" / voice["path"])
        )
        dialog.locator("audio").wait_for()
        dialog.get_by_label("角色描述", exact=False).fill("青年女性，白色衬衫")
        dialog.get_by_label("声音描述", exact=False).fill("自然轻柔")
        dialog.get_by_role("button", name="创建角色", exact=True).click()
        dialog.wait_for(state="detached")
        wait_value(lambda v: len(v["asset_ids"]) == 2)
        role_id = next(i for i in read()["asset_ids"] if i != name_only)
        created.append(role_id)
        role = next(a for a in call("GET", "/api/assets") if a["id"] == role_id)
        created.extend([role["voice_asset_id"]])
        # The portrait was imported as a separate reusable image.
        created.extend(
            a["id"]
            for a in call("GET", "/api/assets")
            if a["kind"] == "image" and a["path"] == role["path"]
        )
        assert (
            role["description"] == "青年女性，白色衬衫"
            and role["voice_description"] == "自然轻柔"
        )
        if prop:
            page.get_by_role("button", name="添加物品", exact=True).click()
            page.locator(f'[data-asset-id="{prop["id"]}"]').click()
            page.get_by_role("dialog").get_by_role(
                "button", name="添加", exact=True
            ).click()
            wait_value(lambda v: prop["id"] in v["asset_ids"])
        page.get_by_role("button", name="添加角色", exact=True).click()
        assert (
            page.get_by_role("dialog")
            .get_by_role("heading", name="添加已有角色", exact=True)
            .is_visible()
        )
        page.get_by_role("button", name="关闭", exact=True).click()
        page.get_by_role("button", name="视频与声音", exact=True).click()
        page.get_by_label("视频比例", exact=True).select_option("16:9")
        wait_value(lambda v: v["aspect"] == "16:9")
        assert page.get_by_role("button", name="一键分镜", exact=True).is_visible()
        page.screenshot(
            path=str(
                out
                / (
                    "drama-input-native-assets.png"
                    if args.native
                    else "drama-input-assets.png"
                )
            )
        )
        report["checks"].append(
            "角色仅名称可创建；上传照片/声音和可选描述保存；添加已有资产；视频选项即时保存"
        )
        if args.generate_character:
            before_pool = set(read()["asset_ids"])
            page.get_by_role("button", name="创建角色", exact=True).click()
            dialog = page.get_by_role("dialog")
            dialog.get_by_label("角色名称", exact=True).fill("验收篮球运动员")
            dialog.get_by_role("button", name="生成照片", exact=True).click()
            dialog.get_by_label("照片提示词", exact=True).fill(
                "中国篮球运动员，青年男性，穿绿色球衣，正面半身人物照片，纯色背景"
            )
            dialog.get_by_label("角色描述", exact=False).fill("中国篮球运动员")
            started = time.monotonic()
            dialog.get_by_role("button", name="创建角色", exact=True).click()
            dialog.wait_for(state="detached", timeout=180000)
            generated_id = next(i for i in read()["asset_ids"] if i not in before_pool)
            created.append(generated_id)
            generated = next(
                a for a in call("GET", "/api/assets") if a["id"] == generated_id
            )
            assert generated["name"] == "验收篮球运动员" and generated[
                "mime"
            ].startswith("image/")
            from PIL import Image

            with Image.open(data / "media" / generated["path"]) as portrait:
                assert min(portrait.size) >= 256
                portrait.verify()
            created.extend(
                a["id"]
                for a in call("GET", "/api/assets")
                if a["kind"] == "image" and a["path"] == generated["path"]
            )
            report["generated_character"] = {
                "asset_id": generated_id,
                "model": generated.get("model"),
                "duration_seconds": round(time.monotonic() - started, 2),
                "image_decodable": True,
                "added_to_project_pool": True,
            }
            report["checks"].append(
                "实际图像模型生成角色照片、角色创建与资产池绑定成功，图片真实可解码"
            )
        current = read()
        call(
            "PATCH",
            "/api/projects/" + pid,
            {
                "revision": current["revision"],
                "scenes": [
                    {
                        "id": "first",
                        "title": "读信",
                        "description": script,
                        "duration": 2,
                        "video_id": video["id"],
                        "asset_ids": [role_id] + ([prop["id"]] if prop else []),
                    },
                    {
                        "id": "second",
                        "title": "微笑",
                        "description": "她把信放回桌面。",
                        "duration": 2,
                        "asset_ids": [name_only],
                    },
                ],
            },
        )
        page.reload()
        page.get_by_role("button", name="我的作品", exact=True).wait_for(timeout=15000)
        page.get_by_role("button", name="我的作品", exact=True).click()
        page.get_by_role(
            "button", name="打开作品" + project["title"], exact=True
        ).click()
        page.get_by_role("button", name="分镜设置", exact=True).click()
        assert page.locator(".storyboard-card").count() == 2
        assert page.get_by_label("分镜数量", exact=True).count() == 0
        assert page.get_by_role("button", name="应用数量", exact=True).count() == 0
        assert page.get_by_role("button", name="保存分镜", exact=True).count() == 0
        before = read()["revision"]
        page.get_by_label("分镜 1 标题", exact=True).fill("自动保存读信")
        wait_value(
            lambda v: v["revision"] > before
            and v["scenes"][0]["title"] == "自动保存读信"
            and v["scene_count"] is None
        )
        held = []

        def pause_save(route):
            if route.request.method == "PATCH" and not held:
                held.append(route)
            else:
                route.continue_()

        page.route("**/api/projects/" + pid, pause_save)
        page.get_by_label("分镜 1 标题", exact=True).fill("保存中继续编辑")
        deadline = time.monotonic() + 10
        while not held:
            assert time.monotonic() < deadline
            page.wait_for_timeout(100)
        page.get_by_label("分镜 1 标题", exact=True).fill("连续修改最终标题")
        held[0].continue_()
        deadline = time.monotonic() + 20
        while read()["scenes"][0]["title"] != "连续修改最终标题":
            assert time.monotonic() < deadline
            page.wait_for_timeout(100)
        page.unroute("**/api/projects/" + pid, pause_save)
        assert (
            page.get_by_label("分镜 1 标题", exact=True).input_value()
            == "连续修改最终标题"
        )
        report["checks"].append(
            "分镜自动保存、保存过程中继续编辑保留最新内容、开始创作即时保存"
        )
        assert (
            page.locator(".storyboard-card").first.inner_text().find(role["name"]) >= 0
        )
        page.get_by_label("分镜 2 标题", exact=True).fill("立即开始创作")
        page.get_by_role("button", name="开始创作", exact=True).click()
        wait_value(lambda v: v["scenes"][1]["title"] == "立即开始创作")
        assert page.locator(".scene-maker-heading strong").inner_text() == "输入参考"
        page.locator(".timeline-clip").nth(1).click()
        page.get_by_role("button", name="图片参考", exact=True).click()
        page.get_by_role("button", name="上一分镜尾帧", exact=True).click()
        wait_value(lambda v: len(v["scenes"][1]["reference_ids"]) == 1)
        tail_id = read()["scenes"][1]["reference_ids"][0]
        created.append(tail_id)
        page.locator(f'[data-reference-id="{tail_id}"]').wait_for()
        page.get_by_label("上传分镜参考", exact=True).set_input_files(
            [str(data / "media" / image["path"])] * 2
        )
        deadline = time.monotonic() + 15
        while page.locator(".reference-input-item").count() < 3:
            assert time.monotonic() < deadline
            time.sleep(0.1)
        page.get_by_role("button", name="视频文案", exact=True).click()
        wait_value(lambda v: len(v["scenes"][1]["reference_ids"]) == 3)
        created.extend(read()["scenes"][1]["reference_ids"])
        page.get_by_role("button", name="选择资产", exact=True).click()
        wait_value(lambda v: v["scene_count"] is None)
        page.locator(".workflow-tabs").get_by_role(
            "button", name="视频制作", exact=True
        ).click()
        page.locator(".timeline-clip").nth(1).click()
        page.get_by_role("button", name="图片参考", exact=True).click()
        page.get_by_label("上传分镜参考", exact=True).set_input_files(
            [str(data / "media" / image["thumbnail"])] * 31
        )
        page.get_by_text("添加后将超过本分镜的参考数量上限", exact=True).wait_for()
        assert page.locator(".reference-input-item").count() == 3
        page.get_by_role("button", name="全部参考", exact=True).click()
        assert page.locator(".reference-input-item").count() == 4
        assert page.locator(".reference-input-grid").count() == 1
        for name in [
            "全部参考",
            "角色参考",
            "物品参考",
            "音色参考",
            "视频参考",
            "图片参考",
        ]:
            assert page.get_by_role("button", name=name, exact=True).is_visible()
        caps = call(
            "GET", "/api/settings/video-capabilities?model=agnes-video-2.5-flash"
        )
        requires_link = (
            "需要模型可读取的素材链接" in page.locator(".reference-maker").inner_text()
        )
        assert requires_link == caps["public_urls"]
        page.screenshot(
            path=str(
                out
                / (
                    "drama-input-native-make.png"
                    if args.native
                    else "drama-input-make.png"
                )
            )
        )
        timeline = page.locator(".timeline").bounding_box()
        height = page.evaluate("window.innerHeight")
        assert timeline["y"] + timeline["height"] <= height + 1
        report["checks"].append(
            "分镜卡片显示已选角色物品；真实尾帧提取；多图上传与统一格子；固定数量保存；31 图拦截；本地参考提示与模型实际能力一致"
        )
        assert not report["page_errors"]
        report["status"] = "passed"
        if not args.native:
            browser.close()
except Exception as error:
    report["status"] = "failed"
    report["error"] = str(error)
    raise
finally:
    call("DELETE", "/api/projects/" + pid)
    call("DELETE", "/api/projects/" + other["id"])
    for ident in dict.fromkeys(created):
        client.delete("/api/assets/" + ident)
    (
        out
        / (
            "drama-input-native-ui-test.json"
            if args.native
            else "drama-input-ui-test.json"
        )
    ).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    client.close()
print("DRAMA_INPUT_UI_PASSED")
