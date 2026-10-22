"""Paid, real desktop workflow check. Uses the current user's encrypted settings."""

from __future__ import annotations
import argparse
import copy
import json
import os
from pathlib import Path
import sys
import time
import httpx
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=9225)
parser.add_argument("--project", help="Resume a previously created acceptance project")
args = parser.parse_args()
data = Path(os.environ["APPDATA"]) / "LimeStudio/workspace"
runtime = json.loads((data / "runtime.json").read_text(encoding="utf-8"))
token = (data / "session-token").read_text(encoding="utf-8").strip()
client = httpx.Client(
    base_url=runtime["backendUrl"],
    headers={"Authorization": "Bearer " + token},
    timeout=30,
)
out = root / "data/reports/refined-acceptance.json"
report = {
    "status": "running",
    "packaged": runtime["packaged"],
    "stages": [],
    "started_at": time.time(),
}
if args.project and out.exists():
    previous = json.loads(out.read_text(encoding="utf-8"))
    if previous.get("project_id") == args.project:
        report = previous
        report.setdefault("attempts", []).append(
            {
                "status": previous["status"],
                "error": previous.get("error"),
                "finished_at": previous.get("finished_at"),
            }
        )
        report.update(status="running", resumed_at=time.time())
        report.pop("error", None)
        report.pop("finished_at", None)


def persist():
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def read_project():
    response = client.get("/api/projects/" + report["project_id"])
    response.raise_for_status()
    return response.json()


def wait_job(action, started):
    deadline = time.monotonic() + (1600 if action == "video" else 700)
    last = ""
    while time.monotonic() < deadline:
        candidates = [
            job
            for job in client.get("/api/jobs").json()
            if job["project_id"] == report["project_id"]
            and job["action"] == action
            and job["created_at"] >= started - 1
        ]
        if candidates:
            job = candidates[0]
            message = job.get("message", "")
            if message != last:
                print(action, job["status"], message[:160], flush=True)
                last = message
            if job["status"] in {"completed", "failed", "cancelled"}:
                report["stages"].append(
                    {
                        "action": action,
                        "job_id": job["id"],
                        "status": job["status"],
                        "server_seconds": job.get("finished_at", time.time())
                        - job["created_at"],
                        "error": job.get("error"),
                    }
                )
                persist()
                assert job["status"] == "completed", job.get("error") or job
                return job
        time.sleep(1)
    raise TimeoutError(action + " did not complete")


try:
    assert (
        runtime["packaged"] and client.get("/api/diagnostics").json()["key_configured"]
    )
    assets = client.get("/api/assets").json()
    refs = [
        asset["id"]
        for kind in ("character", "prop")
        for asset in assets
        if asset["kind"] == kind
    ][:16]
    if args.project:
        report["project_id"] = args.project
        project = read_project()
    else:
        response = client.post(
            "/api/projects",
            json={
                "kind": "drama",
                "title": "精修样例 • 窗边旧信",
                "prompt": "青年在窗边拾起一封旧信，读完后微笑。两个镜头，简短自然的画面。",
                "aspect": "16:9",
                "target_duration": 8,
                "scene_count": 2,
                "asset_ids": refs,
            },
        )
        response.raise_for_status()
        project = response.json()
        report["project_id"] = project["id"]
    persist()
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:" + str(args.port))
        page = browser.contexts[0].pages[0]
        page.get_by_role("button", name="我的作品", exact=True).click()
        page.get_by_role(
            "button", name="打开作品" + project["title"], exact=True
        ).wait_for(timeout=15000)
        page.get_by_role(
            "button", name="打开作品" + project["title"], exact=True
        ).click()
        if not project["script"]:
            page.get_by_role("button", name="我的想法", exact=True).click()
            page.get_by_role("textbox", name="我的想法", exact=True).fill(
                project["prompt"]
            )
            started = time.time()
            page.get_by_role("button", name="生成文案", exact=True).click()
            wait_job("idea", started)
            page.get_by_role("textbox", name="视频文案", exact=True).wait_for(
                timeout=15000
            )
            project = read_project()
            assert project["script"].strip() and not project["scenes"]
            report["generated_script"] = project["script"]
            report["idea_creates_only_script"] = True
            persist()
        if not project["scenes"]:
            page.get_by_role("button", name="视频文案", exact=True).click()
            custom_script = "午后，青年在窗边拾起一封旧信。他展开信纸，读完后露出微笑。"
            page.get_by_role("textbox", name="视频文案", exact=True).fill(custom_script)
            page.get_by_label("分镜数量").fill("2")
            started = time.time()
            page.get_by_role("button", name="一键分镜", exact=True).click()
            wait_job("storyboard", started)
            page.locator(".storyboard-card").first.wait_for(timeout=15000)
            project = read_project()
            assert len(project["scenes"]) == 2 and project["script"] == custom_script
            report["custom_script_preserved"] = True
            report["storyboard_count"] = len(project["scenes"])
            persist()
        page.get_by_role("button", name="视频制作", exact=True).click()
        page.locator(".timeline-clip").first.click()
        if not project["scenes"][0].get("first_frame_id"):
            page.get_by_label("首帧图片模型").select_option("agnes-image-2.5-flash")
            page.get_by_label("视频生成模型").select_option("agnes-video-2.5-flash")
            page.get_by_label("视频比例").select_option("16:9")
            page.get_by_label("视频时长").select_option("4")
            started = time.time()
            page.get_by_role("button", name="生成首帧", exact=True).click()
            wait_job("image", started)
            project = read_project()
        if not project["scenes"][0].get("video_id"):
            started = time.time()
            page.get_by_role("button", name="生成视频", exact=True).click()
            wait_job("video", started)
            project = read_project()
        first = project["scenes"][0]
        assert first["video_seconds"] == 4 and first["aspect"] == "16:9"
        generated = client.get("/api/assets").json()
        video_asset = next(
            asset for asset in generated if asset["id"] == first["video_id"]
        )
        frame_asset = next(
            asset for asset in generated if asset["id"] == first["first_frame_id"]
        )
        assert (
            video_asset["model"] == "agnes-video-2.5-flash"
            and frame_asset["model"] == "agnes-image-2.5-flash"
        )
        # Providers can return extra frames. The requested edit duration, not
        # container length, determines preview and export boundaries.
        assert video_asset["info"]["duration"] >= first["duration"] + first["trim_in"]
        report["generated_media"] = {
            "image_id": frame_asset["id"],
            "video_id": video_asset["id"],
            "provider_video_id": video_asset["provider_video_id"],
            "video_info": video_asset["info"],
            "parameters": {
                key: first.get(key)
                for key in (
                    "image_model",
                    "video_model",
                    "aspect",
                    "video_seconds",
                    "video_size",
                )
            },
        }
        page.get_by_role("button", name="整片预览", exact=True).click()
        page.get_by_role("button", name="播放整片", exact=True).click()
        deadline = time.monotonic() + 30
        while not page.locator(".sequence-stage video").evaluate(
            "(v) => v.currentTime > .5"
        ):
            assert time.monotonic() < deadline
            time.sleep(0.2)
        page.get_by_role("button", name="播放整片", exact=True).wait_for(timeout=15000)
        preview = page.locator(".sequence-controls").inner_text()
        assert "00:04.0" in preview, preview
        actual_stop = page.locator(".sequence-stage video").evaluate(
            "(v) => v.currentTime"
        )
        assert 3.9 <= actual_stop <= 4.2, actual_stop
        report["actual_partial_preview_played"] = True
        report["partial_preview_seconds"] = first["duration"]
        page.screenshot(
            path=str(root / "data/reports/desktop-partial-preview.png"), full_page=True
        )
        # Reuse the real generated clip to verify editing without a second paid video.
        scenes = copy.deepcopy(project["scenes"])
        scenes[0]["narration"] = ""
        scenes[1].update(
            video_id=first["video_id"],
            first_frame_id=first["first_frame_id"],
            trim_in=0.5,
            duration=2,
            narration="",
        )
        response = client.patch(
            "/api/projects/" + project["id"],
            json={"revision": project["revision"], "scenes": scenes},
        )
        response.raise_for_status()
        project = response.json()
        started = time.time()
        response = client.post(
            "/api/projects/" + project["id"] + "/run", json={"action": "export"}
        )
        response.raise_for_status()
        job = wait_job("export", started)
        project = read_project()
        assert project["export_id"] and abs(job["result"]["info"]["duration"] - 6) < 0.3
        report["edit_uses_reused_video"] = True
        report["export"] = job["result"]
        report["status"] = "passed"
        report["finished_at"] = time.time()
        persist()
        print("REFINED_DESKTOP_ACCEPTANCE_PASSED", flush=True)
except Exception as error:
    report.update(
        status="failed",
        error=str(error) or type(error).__name__,
        finished_at=time.time(),
    )
    persist()
    raise
