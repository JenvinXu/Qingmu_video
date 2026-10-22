"""Live Codex drama asset selection, generated portrait/frame/video, tail and edit.

Use --resume to query already-recorded jobs; completed media are reused.
"""

import argparse
import json
import os
import sys
import time
import subprocess
from pathlib import Path
import httpx

sys.stdout.reconfigure(encoding="utf-8")
root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--native", action="store_true")
parser.add_argument("--resume", action="store_true")
args = parser.parse_args()
data = (
    Path(os.environ["APPDATA"]) / "LimeStudio/workspace"
    if args.native
    else root / "data"
)
base = (
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
out = (
    root
    / "data/reports"
    / (
        "drama-input-native-acceptance.json"
        if args.native
        else "drama-input-acceptance.json"
    )
)
report = (
    json.loads(out.read_text(encoding="utf-8"))
    if args.resume
    else {
        "status": "running",
        "native": args.native,
        "started_at": time.time(),
        "stages": {},
        "checks": [],
    }
)


def persist():
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


client = httpx.Client(
    base_url=base, headers={"Authorization": "Bearer " + token}, timeout=180
)


def call(method, url, body=None):
    r = client.request(method, url, json=body)
    if r.is_error:
        raise RuntimeError(f"Local API HTTP {r.status_code}: {r.text[:1200]}")
    return r.json()


def job(key, endpoint, body, timeout=420):
    stage = report["stages"].get(key)
    if not stage:
        value = call("POST", endpoint, body)
        stage = {"job_id": (value.get("job") or value)["id"], "request": body}
        report["stages"][key] = stage
        persist()
    deadline = time.monotonic() + timeout
    while True:
        value = call("GET", "/api/jobs/" + stage["job_id"])
        if value["status"] in {"completed", "failed", "cancelled"}:
            stage["result"] = value
            persist()
            if value["status"] != "completed":
                raise RuntimeError(value.get("error") or value.get("message"))
            return value.get("result", {})
        if time.monotonic() > deadline:
            raise TimeoutError(
                "Acceptance is still running; use --resume to query the same job"
            )
        time.sleep(0.5)


def read():
    return call("GET", "/api/projects/" + report["project_id"])


def patch(body):
    return call(
        "PATCH",
        "/api/projects/" + report["project_id"],
        {"revision": read()["revision"], **body},
    )


try:
    report["status"] = "running"
    persist()
    if not report.get("project_id"):
        project = call(
            "POST",
            "/api/projects",
            {"kind": "drama", "title": "短剧资产与参考实测", "target_duration": 12},
        )
        assert project["scene_count"] is None and project["asset_ids"] == []
        report["project_id"] = project["id"]
        persist()
    if not report.get("character_id"):
        value = job(
            "character",
            "/api/characters",
            {
                "name": "林小雨",
                "description": "成年女性，短黑发，浅绿色衬衫，温暖电影质感",
                "image_prompt": "成年亚洲女性青年，短黑发，浅绿色衬衫，正面半身角色参考照片，干净浅灰背景，自然窗光，温暖电影质感，不要文字标记",
                "image_model": "agnes-image-2.5-flash",
            },
        )
        report["character_id"] = value["asset_id"]
        persist()
    if not report.get("setup_complete"):
        assets = call("GET", "/api/assets")
        prop = next(a for a in assets if a["kind"] == "prop" and a.get("source_url"))
        role = next(a for a in assets if a["id"] == report["character_id"])
        assert role["source_url"] and role["mime"].startswith("image/")
        report["prop_id"] = prop["id"]
        script = f"第一段：林小雨穿着浅绿色衬衫来到窗边，拿起桌上的{prop['name']}，展开信纸阅读。\n第二段：林小雨放下信纸，望向窗外，露出释然的微笑。"
        patch(
            {
                "script": script,
                "asset_ids": [role["id"], prop["id"]],
                "scene_count": None,
            }
        )
        report["script"] = script
        report["setup_complete"] = True
        persist()
    endpoint = "/api/projects/" + report["project_id"] + "/run"
    job("automatic_storyboard", endpoint, {"action": "storyboard"})
    if not report.get("automatic_verified"):
        project = read()
        assert (
            project["scene_count"] is None
            and project["script"] == report["script"]
            and 1 <= len(project["scenes"]) <= 40
        )
        pool = {report["character_id"], report["prop_id"]}
        assert all(set(s["asset_ids"]) <= pool for s in project["scenes"])
        assert any(report["character_id"] in s["asset_ids"] for s in project["scenes"])
        assert any(report["prop_id"] in s["asset_ids"] for s in project["scenes"])
        report["automatic_scene_count"] = len(project["scenes"])
        report["automatic_scenes"] = project["scenes"]
        patch({"scene_count": 2})
        report["automatic_verified"] = True
        persist()
    job("fixed_storyboard", endpoint, {"action": "storyboard"})
    if not report.get("fixed_verified"):
        project = read()
        assert (
            len(project["scenes"]) == project["scene_count"] == 2
            and project["script"] == report["script"]
        )
        assert all(
            set(s["asset_ids"]) <= set(project["asset_ids"]) for s in project["scenes"]
        )
        assert (
            report["character_id"] in project["scenes"][0]["asset_ids"]
            and report["prop_id"] in project["scenes"][0]["asset_ids"]
        )
        report["fixed_scenes"] = project["scenes"]
        scenes = [
            {**s, "duration": 4, "video_seconds": 4, "video_size": "720P"}
            for s in project["scenes"]
        ]
        patch({"scenes": scenes})
        report["fixed_verified"] = True
        persist()
    scene_id = read()["scenes"][0]["id"]
    job("first_frame", endpoint, {"action": "image", "scene_id": scene_id})
    job(
        "reference_video",
        endpoint,
        {"action": "video", "scene_id": scene_id},
        timeout=1000,
    )
    project = read()
    if not report.get("video_verified"):
        assets = call("GET", "/api/assets")
        first = project["scenes"][0]
        generated_video = next(a for a in assets if a["id"] == first["video_id"])
        frame = next(a for a in assets if a["id"] == first["first_frame_id"])
        assert {report["character_id"], report["prop_id"]} <= set(
            generated_video["reference_ids"]
        )
        assert {report["character_id"], report["prop_id"]} <= set(
            frame["reference_ids"]
        )
        assert (
            generated_video["provider_video_id"]
            and generated_video["info"]["duration"] >= 4
        )
        other = next(
            a
            for a in assets
            if a["kind"] == "video"
            and a["id"] != generated_video["id"]
            and a.get("source") == "generated"
            and a.get("info", {}).get("duration", 0) >= 4
        )
        scenes = project["scenes"]
        scenes[1]["video_id"] = other["id"]
        patch({"scenes": scenes})
        report["video"] = generated_video
        report["first_frame_id"] = frame["id"]
        report["video_verified"] = True
        persist()
    if not report.get("tail_verified"):
        project = read()
        value = call(
            "POST",
            "/api/projects/"
            + project["id"]
            + "/scenes/"
            + project["scenes"][1]["id"]
            + "/previous-tail",
        )
        assert value["asset"]["source_asset_id"] == project["scenes"][0]["video_id"]
        assert value["asset"]["id"] in value["project"]["scenes"][1]["reference_ids"]
        # Binding a new input invalidates the second output; reuse its known clip for edit.
        scenes = value["project"]["scenes"]
        scenes[1]["video_id"] = project["scenes"][1]["video_id"]
        patch({"scenes": scenes})
        report["tail_asset_id"] = value["asset"]["id"]
        report["tail_verified"] = True
        persist()
    result = job("export", endpoint, {"action": "export"})
    project = read()
    assert project["export_id"] == result["asset_id"]
    executable = (
        root / "release/win-unpacked/resources/media/ffmpeg.exe"
        if args.native
        else root / "build-resources/media/ffmpeg.exe"
    )
    subprocess.run(
        [
            str(executable),
            "-v",
            "error",
            "-xerror",
            "-i",
            str(data / "media" / result["path"]),
            "-f",
            "null",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    assert abs(result["info"]["duration"] - 8) < 0.2
    report["export"] = result
    report["checks"] = [
        "空白项目默认自动分镜数量",
        "真实角色照片生成",
        "Codex 自动镜数和固定 2 镜，文案完整保留",
        "角色物品由 LLM 从用户资产池选择",
        "首帧实际使用角色/物品图片",
        "3 图参考模式真实视频生成",
        "真实裁切尾帧绑定",
        "8 秒 MP4 实际合成和完整解码",
    ]
    report["provider_capabilities"] = call(
        "GET", "/api/settings/video-capabilities?model=agnes-video-2.5-flash"
    )
    report["status"] = "passed"
    if not args.resume:
        report["duration_seconds"] = round(time.time() - report["started_at"], 2)
    report["verified_at"] = time.time()
    report["model_job_span_seconds"] = round(
        max(v["result"]["finished_at"] for v in report["stages"].values())
        - min(v["result"]["created_at"] for v in report["stages"].values()),
        2,
    )
    persist()
    print("DRAMA_INPUT_ACCEPTANCE_PASSED", report["duration_seconds"], flush=True)
except Exception as error:
    report["status"] = "failed"
    report["error"] = str(error)
    persist()
    raise
finally:
    client.close()
