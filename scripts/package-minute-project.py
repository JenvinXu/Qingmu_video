"""Copy the verified minute project into the packaged workspace and re-export it."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")
root = Path(__file__).resolve().parents[1]
dev_data = root / "data"
native_data = Path(os.environ["APPDATA"]) / "LimeStudio" / "workspace"
runtime = json.loads((native_data / "runtime.json").read_text(encoding="utf-8"))
native_token = (native_data / "session-token").read_text(encoding="utf-8").strip()
dev_token = (dev_data / "session-token").read_text(encoding="utf-8").strip()
state = json.loads((dev_data / "reports/narration-minute-state.json").read_text(encoding="utf-8"))
dev = httpx.Client(
    base_url="http://127.0.0.1:4478",
    headers={"Authorization": "Bearer " + dev_token},
    timeout=120,
)
native = httpx.Client(
    base_url=runtime["backendUrl"],
    headers={"Authorization": "Bearer " + native_token},
    timeout=180,
)
source_project = dev.get("/api/projects/" + state["project_id"]).raise_for_status().json()
source_assets = {item["id"]: item for item in dev.get("/api/assets").raise_for_status().json()}

# Restore the user's requested low-cost text and visual routing in the packaged app.
settings = native.get("/api/settings").raise_for_status().json()
body = {
    key: settings[key]
    for key in (
        "base_url",
        "text_model",
        "llm_provider",
        "llm_base_url",
        "vision_model",
        "image_model",
        "video_model",
        "voice_provider",
        "voice_model",
        "voice",
        "video_seconds",
        "video_size",
    )
}
body.update(
    llm_provider="qianfan",
    text_model="deepseek-v4-flash",
    vision_model="kimi-k2.6",
    api_key="",
    llm_api_key="",
)
updated_settings = native.put("/api/settings", json=body)
updated_settings.raise_for_status()
if not updated_settings.json()["llm_key_configured"]:
    raise AssertionError("packaged Qianfan key was not preserved")

native_assets = native.get("/api/assets").raise_for_status().json()
existing = {
    item.get("description", "").removeprefix("一分钟口播验收素材 · "): item
    for item in native_assets
    if item.get("description", "").startswith("一分钟口播验收素材 · ")
}
mapping = {}
needed = {
    source_project.get("bgm_id"),
    *(
        ident
        for scene in source_project["scenes"]
        for ident in (
            scene.get("first_frame_id"),
            scene.get("video_id"),
            scene.get("audio_id"),
            scene.get("sfx_id"),
        )
    ),
}
for index, ident in enumerate(sorted(value for value in needed if value), 1):
    if ident in existing:
        mapping[ident] = existing[ident]["id"]
        continue
    source = source_assets[ident]
    path = dev_data / "media" / source["path"]
    print(f"IMPORT {index}/{len(needed)} {source['name']}", flush=True)
    with path.open("rb") as handle:
        imported = native.post(
            "/api/assets/import",
            data={
                "kind": source["kind"],
                "description": "一分钟口播验收素材 · " + ident,
                "voice": source.get("voice", ""),
            },
            files={"file": (source["name"] + path.suffix, handle, source["mime"])},
        ).raise_for_status().json()
    mapping[ident] = imported["id"]

title = "一分钟口播验收 · 稳定作息（完整版）"
projects = native.get("/api/projects").raise_for_status().json()
target = next((item for item in projects if item["title"] == title), None)
if target is None:
    target = native.post(
        "/api/projects",
        json={
            "kind": "narration",
            "title": title,
            "prompt": source_project["prompt"],
            "target_duration": 64,
            "scene_count": len(source_project["scenes"]),
            "aspect": source_project["aspect"],
            "subtitles": True,
        },
    ).raise_for_status().json()

scenes = []
for scene in source_project["scenes"]:
    scenes.append(
        {
            **scene,
            **{
                field: mapping.get(scene.get(field)) if scene.get(field) else None
                for field in (
                    "first_frame_id",
                    "video_id",
                    "audio_id",
                    "sfx_id",
                )
            },
            "asset_ids": [mapping.get(value, value) for value in scene.get("asset_ids", [])],
            "reference_ids": [mapping.get(value, value) for value in scene.get("reference_ids", [])],
        }
    )
target = native.patch(
    "/api/projects/" + target["id"],
    json={
        "revision": target["revision"],
        "prompt": source_project["prompt"],
        "script": source_project["script"],
        "synopsis": source_project["synopsis"],
        "scenes": scenes,
        "scene_count": len(scenes),
        "bgm_id": mapping[source_project["bgm_id"]],
        "bgm_volume": source_project["bgm_volume"],
        "bgm_ducking": source_project["bgm_ducking"],
        "subtitles": True,
    },
).raise_for_status().json()
job = native.post(
    f"/api/projects/{target['id']}/run", json={"action": "export", "scene_id": None}
).raise_for_status().json()
deadline = time.monotonic() + 900
while True:
    job = native.get("/api/jobs/" + job["id"]).raise_for_status().json()
    if job["status"] == "completed":
        break
    if job["status"] in {"failed", "cancelled"}:
        raise RuntimeError(job.get("error") or job.get("message"))
    if time.monotonic() > deadline:
        raise TimeoutError("packaged export timed out")
    time.sleep(1)
target = native.get("/api/projects/" + target["id"]).raise_for_status().json()
exported = next(
    item
    for item in native.get("/api/assets").raise_for_status().json()
    if item["id"] == target["export_id"]
)
video = native_data / "media" / exported["path"]
diagnostics = native.get("/api/diagnostics").raise_for_status().json()
ffmpeg = diagnostics["media"]["ffmpeg"]["path"]
subprocess.run(
    [ffmpeg, "-v", "error", "-i", str(video), "-f", "null", "NUL"],
    check=True,
    timeout=900,
)
if exported["info"]["duration"] < 60:
    raise AssertionError("packaged export is shorter than one minute")
report = {
    "status": "passed",
    "packaged": True,
    "project_id": target["id"],
    "export_id": exported["id"],
    "path": str(video),
    "duration": exported["info"]["duration"],
    "size": video.stat().st_size,
    "backend": runtime["backendUrl"],
    "checks": [
        "packaged backend accepted normalized scene schema",
        "all verified visuals, voices, AI video, BGM and SFX imported",
        "packaged FFmpeg re-export",
        "duration >= 60 seconds",
        "full decode",
        "Qianfan text and vision routing preserved",
    ],
}
(dev_data / "reports/packaged-minute-project.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
)
print("PACKAGED_MINUTE_PROJECT_PASSED", report["duration"], video, flush=True)
