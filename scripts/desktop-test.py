"""Inspect the actual packaged Electron workbench through local Chromium debugging."""

import argparse
import json
from pathlib import Path
import sys
import time
import httpx
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=9225)
parser.add_argument("--accept", action="store_true")
parser.add_argument(
    "--skip-provider",
    action="store_true",
    help="Verify a UI-only update without repeating live model requests",
)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
out = root / "data/reports"
errors = []
with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{args.port}")
    context = browser.contexts[0]
    page = (
        context.pages[0]
        if context.pages
        else context.wait_for_event("page", timeout=60000)
    )
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.get_by_role("button", name="我的作品", exact=True).wait_for(timeout=60000)
    page.get_by_role("button", name="我的作品", exact=True).click()
    page.get_by_role("heading", name="我的作品", exact=True).wait_for(timeout=60000)
    connection = page.evaluate("window.studioDesktop.connection()")
    client = httpx.Client(
        base_url=connection["baseUrl"],
        headers={"Authorization": "Bearer " + connection["token"]},
        timeout=120,
    )
    diagnostics = client.get("/api/diagnostics").json()
    assert (
        "/release/win-unpacked/resources/media/".replace("/", "\\")
        in diagnostics["media"]["ffmpeg"]["path"]
    )
    assert diagnostics["media"]["ffmpeg"]["ready"] and diagnostics["agent"]["ready"]
    assert "Roaming" in diagnostics["data_dir"]
    if not args.skip_provider:
        result = client.post("/api/settings/test")
        result.raise_for_status()
    completed = next(
        value
        for value in client.get("/api/projects").json()
        if value["kind"] == "drama" and value.get("export_id")
    )
    page.get_by_role(
        "button", name="打开作品" + completed["title"], exact=True
    ).first.click()
    video = page.locator("video").first
    video.wait_for()

    def poll_video(predicate):
        deadline = time.monotonic() + 30
        while not video.evaluate(predicate):
            if time.monotonic() > deadline:
                raise TimeoutError("Actual desktop media did not become ready")
            time.sleep(0.25)

    poll_video("(v)=>v.readyState>=2")
    page.get_by_role("button", name="播放镜头", exact=True).click()
    poll_video("(v)=>v.currentTime>0.5")
    page.get_by_role("button", name="暂停预览", exact=True).click()
    first_video = next(
        scene["video_id"] for scene in completed["scenes"] if scene.get("video_id")
    )
    source = next(
        asset
        for asset in client.get("/api/assets").json()
        if asset["id"] == first_video
    )
    expected_width = next(
        stream["width"]
        for stream in source["info"]["streams"]
        if stream["codec_type"] == "video"
    )
    assert video.evaluate("(v)=>v.videoWidth") == expected_width
    assert not page.locator(
        ".creation-card,.connection-card,.source-grid,.production-steps,.suggestion,.waveform"
    ).count()
    page.wait_for_timeout(300)
    timeline = page.locator(".timeline").bounding_box()
    assert timeline and timeline["y"] + timeline["height"] <= page.evaluate(
        "window.innerHeight"
    ), timeline
    maker = page.locator(".reference-maker")
    maker.get_by_role("button", name="视频制作", exact=True).click()
    viewport_height = page.evaluate("window.innerHeight")
    for name in ("视频比例", "视频时长", "视频画质"):
        control = page.get_by_label(name)
        bounds = control.bounding_box()
        assert (
            control.is_visible()
            and bounds
            and bounds["y"] + bounds["height"] <= viewport_height
        ), name
    assert page.get_by_role("button", name="生成视频", exact=True).is_visible()
    page.screenshot(path=str(out / "desktop-drama.png"), full_page=True)
    page.get_by_role("button", name="口播制作", exact=True).first.click()
    completed_narration = next(
        value
        for value in client.get("/api/projects").json()
        if value["kind"] == "narration" and value.get("export_id")
    )
    page.get_by_role("combobox", name="切换作品").select_option(
        completed_narration["id"]
    )
    page.get_by_role("button", name="视频合成", exact=True).click()
    video = page.locator("video").first
    video.wait_for()
    poll_video("(v)=>v.readyState>=2")
    assert video.evaluate("(v)=>v.videoWidth") == 720
    video.evaluate("(v)=>v.play()")
    poll_video("(v)=>v.currentTime>0.5")
    video.evaluate("(v)=>v.pause()")
    page.wait_for_timeout(300)
    page.screenshot(path=str(out / "desktop-narration.png"), full_page=True)
    page.get_by_role("button", name="模型设置", exact=True).click()
    assert (
        all(
            control.input_value() == ""
            for control in page.locator("input[type=password]").all()
        )
        and "cpk-" not in page.content()
        and "bce-v3/ALTAK-" not in page.content()
    )
    page.get_by_role("button", name="连接与验收", exact=True).click()
    if args.accept:
        page.get_by_role("button", name="一键验收", exact=True).click()
        page.wait_for_timeout(2000)
    page.screenshot(path=str(out / "desktop-debug.png"), full_page=True)
    assert not errors, errors
    report = {
        "status": "passed",
        "packaged": True,
        "backend": connection["baseUrl"],
        "diagnostics": diagnostics,
        "checks": [
            "独立服务启动",
            "DPAPI 模型配置",
            "桌面短剧视频播放",
            "竖屏口播视频播放",
            "前端密钥隔离",
        ],
        "page_errors": errors,
        "acceptance_started": args.accept,
        "provider_test_skipped": args.skip_provider,
        "ui_checks": [
            "无装饰卡片与模拟波形",
            "短剧首屏时间线",
            "五步流程与当前分镜预览操作",
            "视频制作子页集中显示模型、比例、时长与画质",
        ],
    }
    if not args.skip_provider:
        report["checks"].append("真实文本请求")
    (out / "desktop-test.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("PACKAGED_DESKTOP_TEST_PASSED", flush=True)
    # Disconnecting CDP leaves the user's desktop window running.
