"""Create and verify a real 60+ second narration project through public APIs."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")
parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:4468")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
data = root / "data"
reports = data / "reports"
state_path = reports / "narration-minute-state.json"
report_path = reports / "narration-minute-acceptance.json"
token = (data / "session-token").read_text(encoding="utf-8").strip()
client = httpx.Client(
    base_url=args.url,
    headers={"Authorization": "Bearer " + token},
    timeout=httpx.Timeout(90, connect=15),
)


def save_state(value):
    state_path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}


def project():
    return client.get("/api/projects/" + state["project_id"]).raise_for_status().json()


def wait_job(ident, timeout=3600):
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        value = client.get("/api/jobs/" + ident).raise_for_status().json()
        marker = f"{value['status']} {value.get('progress', 0)}% {value.get('message', '')}"
        if marker != last:
            print(marker, flush=True)
            last = marker
        if value["status"] == "completed":
            return value
        if value["status"] in {"failed", "cancelled"}:
            raise RuntimeError(value.get("error") or value.get("message") or marker)
        time.sleep(1)
    raise TimeoutError("job timeout: " + ident)


def run(action, scene_id=None, retries=1):
    last = None
    for attempt in range(1, retries + 1):
        print(f"RUN {action} {scene_id or ''} attempt {attempt}", flush=True)
        response = client.post(
            f"/api/projects/{state['project_id']}/run",
            json={"action": action, "scene_id": scene_id},
        )
        response.raise_for_status()
        try:
            return wait_job(response.json()["id"])
        except Exception as cause:  # keep completed assets and retry only missing work
            last = cause
            print(f"RETRYABLE {action}: {cause}", flush=True)
            time.sleep(min(12, attempt * 3))
    raise last


def patch(**changes):
    current = project()
    response = client.patch(
        "/api/projects/" + current["id"],
        json={"revision": current["revision"], **changes},
    )
    response.raise_for_status()
    return response.json()


if not state.get("project_id"):
    created = client.post(
        "/api/projects",
        json={
            "kind": "narration",
            "title": "一分钟口播验收 · 从晨光到好睡眠",
            "prompt": (
                "面向工作节奏忙乱的年轻人，讲清楚如何用早晨接触自然光、白天安排轻运动、"
                "下午减少拖延、睡前建立固定收尾仪式，让一天更清醒、晚上更容易放松。"
                "语气自然可信，给出能立刻执行的小步骤，不虚构研究数据。"
            ),
            "target_duration": 64,
            "scene_count": 8,
            "aspect": "9:16",
            "subtitles": True,
        },
    ).raise_for_status().json()
    state = {"project_id": created["id"]}
    save_state(state)

current = project()
if not current.get("script", "").strip():
    run("idea", retries=2)
current = project()
if len(current.get("scenes", [])) != 8:
    run("storyboard", retries=2)
current = project()
if len(current["scenes"]) != 8:
    raise AssertionError(f"expected 8 scenes, got {len(current['scenes'])}")
if sum(scene["duration"] for scene in current["scenes"]) < 60:
    raise AssertionError("storyboard and real voice durations do not reach 60 seconds")

if any(not (scene.get("first_frame_id") or scene.get("video_id")) for scene in current["scenes"]):
    run("images", retries=4)
current = project()
if any(not scene.get("audio_id") for scene in current["scenes"] if scene["narration"].strip()):
    run("voices", retries=3)
current = project()

# Exercise the user-selected segment AI video path on a central segment.
video_scene = current["scenes"][2]
if not video_scene.get("video_id"):
    seconds = min(30, max(1, round(video_scene["duration"])))
    scenes = [
        {**scene, "video_seconds": seconds}
        if scene["id"] == video_scene["id"]
        else scene
        for scene in current["scenes"]
    ]
    patch(scenes=scenes)
    try:
        run("video", video_scene["id"], retries=2)
    except RuntimeError as flash_error:
        # The Flash queue can be saturated independently. The configured media
        # account also exposes the full-capacity v2 route, so retry the same
        # selected segment there without regenerating any prior asset.
        current = project()
        scenes = [
            {**scene, "video_model": "agnes-video-v2.0"}
            if scene["id"] == video_scene["id"]
            else scene
            for scene in current["scenes"]
        ]
        patch(scenes=scenes)
        state["video_flash_error"] = str(flash_error)
        state["video_fallback_model"] = "agnes-video-v2.0"
        save_state(state)
        run("video", video_scene["id"], retries=5)

# Add a real Creative Commons soundtrack and a CC0 morning bird sound effect.
if not state.get("bgm_id"):
    bgm = client.post(
        "/api/library/collect",
        json={
            "url": "https://cdn.freesound.org/previews/353/353156_3492460-hq.mp3",
            "name": "Soundscape · Last 31 · 背景音乐",
            "license": "CC BY 4.0 · Tri-Tachyon · freesound.org/s/353156",
        },
    ).raise_for_status().json()
    bgm = client.patch(
        "/api/assets/" + bgm["id"],
        json={
            "kind": "music",
            "name": bgm["name"],
            "description": "平静钢琴与环境氛围，用于口播低音量背景",
        },
    ).raise_for_status().json()
    state["bgm_id"] = bgm["id"]
    save_state(state)
if not state.get("sfx_id"):
    effect = client.post(
        "/api/library/collect",
        json={
            "url": "https://cdn.freesound.org/previews/463/463903_7241289-hq.mp3",
            "name": "Birds In Spring · 清晨鸟声",
            "license": "CC0 1.0 · BurghRecords · freesound.org/s/463903",
        },
    ).raise_for_status().json()
    state["sfx_id"] = effect["id"]
    save_state(state)

current = project()
scenes = []
for index, scene in enumerate(current["scenes"]):
    scenes.append(
        {
            **scene,
            **(
                {
                    "sfx_id": state["sfx_id"],
                    "sfx_volume": 0.13,
                    "sfx_offset": 0.4,
                }
                if index == 0
                else {}
            ),
        }
    )
patch(
    scenes=scenes,
    bgm_id=state["bgm_id"],
    bgm_volume=0.08,
    bgm_ducking=True,
    subtitles=True,
)
current = project()
if not current.get("export_id") or current.get("export_revision") != current["revision"]:
    run("export", retries=2)
current = project()
assets = {asset["id"]: asset for asset in client.get("/api/assets").raise_for_status().json()}
exported = assets[current["export_id"]]
target = data / "media" / exported["path"]
diagnostics = client.get("/api/diagnostics").raise_for_status().json()
ffmpeg = diagnostics["media"]["ffmpeg"]["path"]
ffprobe = diagnostics["media"]["ffprobe"]["path"]
probe = json.loads(
    subprocess.check_output(
        [
            ffprobe,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(target),
        ],
        text=True,
        encoding="utf-8",
    )
)
actual_duration = float(probe["format"]["duration"])
if actual_duration < 60:
    raise AssertionError(f"final duration {actual_duration:.3f}s is below 60s")
subprocess.run(
    [ffmpeg, "-v", "error", "-i", str(target), "-f", "null", "NUL"],
    check=True,
    timeout=900,
)
volume = subprocess.run(
    [
        ffmpeg,
        "-hide_banner",
        "-i",
        str(target),
        "-vn",
        "-af",
        "volumedetect",
        "-f",
        "null",
        "NUL",
    ],
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
    timeout=300,
).stderr
contact = reports / "narration-minute-contact-sheet.jpg"
subprocess.run(
    [
        ffmpeg,
        "-v",
        "error",
        "-y",
        "-i",
        str(target),
        "-vf",
        "fps=1/8,scale=200:-1,tile=4x2",
        "-frames:v",
        "1",
        str(contact),
    ],
    check=True,
    timeout=300,
)

# Use the configured vision model to describe every bound first frame. These
# descriptions plus the exact scene text make semantic mismatch review auditable.
previous_report = (
    json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
)
previous_vision = {
    item.get("asset_id"): item
    for item in previous_report.get("vision_review", [])
    if item.get("asset_id")
}
vision = []
for index, scene in enumerate(current["scenes"], 1):
    frame_id = scene.get("first_frame_id")
    if not frame_id:
        continue
    if frame_id in previous_vision:
        vision.append(
            {
                **previous_vision[frame_id],
                "scene": index,
                "title": scene["title"],
                "narration": scene["narration"],
                "match_reason": scene.get("match_reason"),
                "match_score": scene.get("match_score"),
            }
        )
        continue
    print(f"VISION {index}/8", flush=True)
    result = client.post(f"/api/assets/{frame_id}/analyze", timeout=180)
    result.raise_for_status()
    vision.append(
        {
            "scene": index,
            "title": scene["title"],
            "narration": scene["narration"],
            "asset_id": frame_id,
            "match_reason": scene.get("match_reason"),
            "match_score": scene.get("match_score"),
            "vision_description": result.json()["description"],
        }
    )

report = {
    "status": "passed",
    "project_id": current["id"],
    "title": current["title"],
    "target_duration": current["target_duration"],
    "timeline_duration": sum(scene["duration"] for scene in current["scenes"]),
    "actual_duration": actual_duration,
    "scene_count": len(current["scenes"]),
    "script_characters": len("".join(current["script"].split())),
    "selected_ai_video_scene": {
        "id": current["scenes"][2]["id"],
        "title": current["scenes"][2]["title"],
        "video_id": current["scenes"][2]["video_id"],
    },
    "sound": {
        "voice_scenes": sum(bool(scene.get("audio_id")) for scene in current["scenes"]),
        "bgm_id": current["bgm_id"],
        "bgm_volume": current["bgm_volume"],
        "bgm_ducking": current["bgm_ducking"],
        "sfx_scenes": sum(bool(scene.get("sfx_id")) for scene in current["scenes"]),
        "volume_detect_tail": volume[-1200:],
    },
    "export": {
        "asset_id": exported["id"],
        "path": str(target),
        "size": target.stat().st_size,
        "streams": [
            {
                "codec_type": stream.get("codec_type"),
                "codec_name": stream.get("codec_name"),
                "width": stream.get("width"),
                "height": stream.get("height"),
            }
            for stream in probe["streams"]
        ],
        "full_decode": "passed",
        "contact_sheet": str(contact),
    },
    "vision_review": vision,
}
report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print("NARRATION_MINUTE_ACCEPTANCE_PASSED", actual_duration, target, flush=True)
