"""Real packaged narration steps; only one missing image is generated."""

import argparse
import json
import os
import sys
import time
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
parser = argparse.ArgumentParser()
parser.add_argument("--project")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
data = Path(os.environ["APPDATA"]) / "LimeStudio/workspace"
runtime = json.loads((data / "runtime.json").read_text(encoding="utf-8"))
token = (data / "session-token").read_text(encoding="utf-8").strip()
client = httpx.Client(
    base_url=runtime["backendUrl"],
    headers={"Authorization": "Bearer " + token},
    timeout=30,
)
out = root / "data/reports/narration-step-acceptance.json"
report = {
    "status": "running",
    "packaged": runtime["packaged"],
    "started_at": time.time(),
    "stages": [],
}
if args.project and out.exists():
    old = json.loads(out.read_text(encoding="utf-8"))
    if old.get("project_id") == args.project:
        report = old
        report.setdefault("attempts", []).append(
            {"status": old["status"], "error": old.get("error")}
        )
        report.update(status="running", resumed_at=time.time())
        report.pop("error", None)


def persist():
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def read():
    return client.get("/api/projects/" + report["project_id"]).json()


def wait(action, start):
    deadline = time.monotonic() + 800
    last = ""
    while time.monotonic() < deadline:
        jobs = [
            j
            for j in client.get("/api/jobs").json()
            if j["project_id"] == report["project_id"]
            and j["action"] == action
            and j["created_at"] >= start - 1
        ]
        if jobs:
            job = jobs[0]
            if job["message"] != last:
                last = job["message"]
                print(action, job["status"], last[:140], flush=True)
            if job["status"] in ("completed", "failed", "cancelled"):
                report["stages"].append(
                    {
                        "action": action,
                        "job_id": job["id"],
                        "status": job["status"],
                        "server_seconds": job["finished_at"] - job["created_at"],
                        "result": job.get("result"),
                        "error": job.get("error"),
                    }
                )
                persist()
                assert job["status"] == "completed", job.get("error")
                return job
        time.sleep(1)
    raise TimeoutError(action)


try:
    assert (
        runtime["packaged"] and client.get("/api/diagnostics").json()["key_configured"]
    )
    if args.project:
        report["project_id"] = args.project
    else:
        response = client.post(
            "/api/projects",
            json={
                "kind": "narration",
                "title": "分步口播样例 • 窗边片刻",
                "prompt": "用自然简短的口播，讲午后的窗边和片刻安静",
                "scene_count": 2,
                "target_duration": 12,
                "aspect": "9:16",
            },
        )
        response.raise_for_status()
        report["project_id"] = response.json()["id"]
    persist()
    project = read()
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9225")
        page = browser.contexts[0].pages[0]
        page.get_by_role("button", name="我的作品", exact=True).click()
        page.get_by_role(
            "button", name="打开作品" + project["title"], exact=True
        ).click()
        if not project["script"]:
            start = time.time()
            page.get_by_role("button", name="生成文案", exact=True).click()
            wait("idea", start)
            page.get_by_role("textbox", name="口播文案", exact=True).wait_for(
                timeout=15000
            )
            project = read()
            assert project["script"].strip() and not project["scenes"]
            report["idea_only_generates_script"] = True
            report["generated_script"] = project["script"]
            persist()
        if not project["scenes"]:
            page.get_by_role("button", name="口播文案", exact=True).click()
            text = "午后的阳光落在窗边。放下手机，给自己片刻安静。"
            page.get_by_role("textbox", name="口播文案", exact=True).fill(text)
            page.get_by_label("画面数量").fill("2")
            start = time.time()
            page.get_by_role("button", name="划分画面", exact=True).click()
            wait("storyboard", start)
            page.locator(".storyboard-card").first.wait_for(timeout=15000)
            project = read()
            assert project["script"] == text and len(project["scenes"]) == 2
            assert "".join(
                "".join(s["narration"].split()) for s in project["scenes"]
            ) == "".join(text.split())
            report["partition_preserves_original_script"] = True
            persist()
        page.get_by_role("button", name="画面制作", exact=True).click()
        if not any(s["first_frame_id"] or s["video_id"] for s in project["scenes"]):
            assets = client.get("/api/assets").json()
            image = next(
                a for a in assets if a["kind"] == "image" and a["source"] == "generated"
            )
            page.get_by_role("button", name="选择图片或视频", exact=True).click()
            page.get_by_role("dialog").locator(
                '[data-asset-id="' + image["id"] + '"]'
            ).click()
            page.get_by_role("button", name="确认选择", exact=True).click()
            report["reused_image_id"] = image["id"]
            persist()
        if any(not (s["first_frame_id"] or s["video_id"]) for s in project["scenes"]):
            start = time.time()
            page.get_by_role("button", name="补齐画面", exact=True).click()
            job = wait("images", start)
            assert (
                len(job["result"]["generated"]) == 1
                and len(job["result"]["reused_scene_ids"]) == 1
            )
            project = read()
            assert not project["export_id"] and not any(
                s["audio_id"] for s in project["scenes"]
            )
            report["image_stage_isolated_and_reuses_existing"] = True
            persist()
        page.get_by_role("button", name="声音字幕", exact=True).click()
        page.locator(".timeline-clip").first.click()
        project = read()
        if not project["scenes"][0]["audio_id"]:
            page.get_by_label("片段声音").select_option("zh-CN-YunxiNeural")
            start = time.time()
            page.get_by_role("button", name="生成配音", exact=True).click()
            wait("voice", start)
            project = read()
            assert (
                project["scenes"][0]["voice"] == "zh-CN-YunxiNeural"
                and not project["scenes"][1]["audio_id"]
                and not project["export_id"]
            )
            page.locator("audio.audio-preview").wait_for(timeout=15000)
            page.locator("audio.audio-preview").evaluate("(v)=>v.play()")
            deadline = time.monotonic() + 30
            while not page.locator("audio.audio-preview").evaluate(
                "(v)=>v.currentTime>.3"
            ):
                assert time.monotonic() < deadline
                time.sleep(0.2)
            page.locator("audio.audio-preview").evaluate("(v)=>v.pause()")
            report["single_clip_voice_generated_and_played"] = True
            persist()
        if any(not s["audio_id"] for s in project["scenes"]):
            start = time.time()
            page.get_by_role("button", name="补齐配音", exact=True).click()
            job = wait("voices", start)
            assert (
                len(job["result"]["generated"]) == 1
                and len(job["result"]["reused_scene_ids"]) == 1
            )
            project = read()
            assert not project["export_id"]
            report["voice_stage_isolated_and_reuses_existing"] = True
            persist()
        page.get_by_role("button", name="视频合成", exact=True).click()
        if not project["export_id"]:
            start = time.time()
            page.get_by_role("button", name="合成视频", exact=True).click()
            job = wait("export", start)
            report["export"] = job["result"]
            persist()
        project = read()
        assets = client.get("/api/assets").json()
        media = next(a for a in assets if a["id"] == project["export_id"])
        expected = sum(s["duration"] for s in project["scenes"])
        assert abs(media["info"]["duration"] - expected) < 0.15
        assert (
            next(s for s in media["info"]["streams"] if s["codec_type"] == "video")[
                "width"
            ]
            == 720
        )
        video = page.locator(".narration-preview video")
        video.wait_for(timeout=15000)
        video.evaluate("(v)=>v.play()")
        deadline = time.monotonic() + 30
        while not video.evaluate("(v)=>v.currentTime>.4"):
            assert time.monotonic() < deadline
            time.sleep(0.2)
        video.evaluate("(v)=>v.pause()")
        assert video.evaluate("(v)=>v.videoWidth===720 && v.videoHeight===1280")
        report["actual_export_played"] = True
        report["project"] = project
        report["export_info"] = media["info"]
        page.screenshot(
            path=str(root / "data/reports/desktop-narration-steps.png"), full_page=True
        )
        page.reload()
        page.get_by_role(
            "button", name="打开作品" + project["title"], exact=True
        ).click()
        video = page.locator(".narration-preview video")
        video.wait_for(timeout=15000)
        report["reload_keeps_completed_project"] = bool(read()["export_id"])
    report.update(status="passed", finished_at=time.time())
    persist()
    print("NARRATION_STEPS_DESKTOP_ACCEPTANCE_PASSED", flush=True)
except Exception as e:
    report.update(
        status="failed", error=str(e) or type(e).__name__, finished_at=time.time()
    )
    persist()
    raise
