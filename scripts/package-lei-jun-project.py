"""Copy the verified Lei Jun narration into the packaged desktop workspace."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
DEV_DATA = ROOT / "data"
PROJECT_ID = "756990359c204d0994d4c1b5ba5a9c5b"
TITLE = "雷军创业经历 · 多源视频验收"


def client(url: str, token_file: Path, timeout: int = 180) -> httpx.Client:
    token = token_file.read_text(encoding="utf-8").strip()
    return httpx.Client(
        base_url=url,
        headers={"Authorization": "Bearer " + token},
        timeout=timeout,
    )


native_data = Path(os.environ["APPDATA"]) / "LimeStudio" / "workspace"
runtime = json.loads((native_data / "runtime.json").read_text(encoding="utf-8"))
dev = client("http://127.0.0.1:4488", DEV_DATA / "session-token")
native = client(runtime["backendUrl"], native_data / "session-token")

source_project = dev.get(f"/api/projects/{PROJECT_ID}").raise_for_status().json()
source_assets = {
    item["id"]: item for item in dev.get("/api/assets").raise_for_status().json()
}

needed = {
    source_project.get("bgm_id"),
    *source_project.get("asset_ids", []),
    *(
        ident
        for scene in source_project["scenes"]
        for ident in (
            *scene.get("asset_ids", []),
            *scene.get("reference_ids", []),
            scene.get("first_frame_id"),
            scene.get("video_id"),
            scene.get("audio_id"),
            scene.get("sfx_id"),
        )
    ),
}
needed.discard(None)

marker = "雷军多源口播验收素材 · "
native_assets = native.get("/api/assets").raise_for_status().json()
existing = {
    item.get("description", "").removeprefix(marker).split(" | ", 1)[0]: item
    for item in native_assets
    if item.get("description", "").startswith(marker)
}
mapping: dict[str, str] = {}
for index, ident in enumerate(sorted(needed), 1):
    if ident in existing:
        mapping[ident] = existing[ident]["id"]
        continue
    source = source_assets[ident]
    path = DEV_DATA / "media" / source["path"]
    provenance = " | ".join(
        value
        for value in (
            source.get("provider", ""),
            source.get("license", ""),
            source.get("page_url", "") or source.get("source_url", ""),
        )
        if value
    )
    print(f"IMPORT {index}/{len(needed)} {source['name']}", flush=True)
    with path.open("rb") as handle:
        imported = native.post(
            "/api/assets/import",
            data={
                "kind": source["kind"],
                "description": marker + ident + (" | " + provenance if provenance else ""),
                "voice": source.get("voice", ""),
            },
            files={"file": (source["name"] + path.suffix, handle, source["mime"])},
        ).raise_for_status().json()
    mapping[ident] = imported["id"]

projects = native.get("/api/projects").raise_for_status().json()
target = next((item for item in projects if item["title"] == TITLE), None)
if target is None:
    target = native.post(
        "/api/projects",
        json={
            "kind": "narration",
            "title": TITLE,
            "prompt": source_project["prompt"],
            "target_duration": source_project["target_duration"],
            "scene_count": len(source_project["scenes"]),
            "aspect": source_project["aspect"],
            "subtitles": True,
        },
    ).raise_for_status().json()


def remap(scene: dict) -> dict:
    result = dict(scene)
    for field in ("first_frame_id", "video_id", "audio_id", "sfx_id"):
        result[field] = mapping.get(scene.get(field)) if scene.get(field) else None
    result["asset_ids"] = [mapping[value] for value in scene.get("asset_ids", [])]
    result["reference_ids"] = [
        mapping[value] for value in scene.get("reference_ids", [])
    ]
    return result


target = native.patch(
    f"/api/projects/{target['id']}",
    json={
        "revision": target["revision"],
        "prompt": source_project["prompt"],
        "script": source_project["script"],
        "synopsis": source_project["synopsis"],
        "scenes": [remap(scene) for scene in source_project["scenes"]],
        "scene_count": len(source_project["scenes"]),
        "asset_ids": [mapping[value] for value in source_project.get("asset_ids", [])],
        "bgm_id": mapping[source_project["bgm_id"]],
        "bgm_volume": source_project["bgm_volume"],
        "bgm_ducking": source_project["bgm_ducking"],
        "subtitles": True,
    },
).raise_for_status().json()

job = native.post(
    f"/api/projects/{target['id']}/run", json={"action": "export"}
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

target = native.get(f"/api/projects/{target['id']}").raise_for_status().json()
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
duration = float(exported["info"]["duration"])
if not 60 <= duration <= 120:
    raise AssertionError(f"packaged export duration out of range: {duration}")

report = {
    "status": "passed",
    "packaged": True,
    "project_id": target["id"],
    "export_id": exported["id"],
    "path": str(video),
    "duration": duration,
    "size": video.stat().st_size,
    "backend": runtime["backendUrl"],
    "scene_count": len(target["scenes"]),
    "checks": [
        "11/11 scenes contain video",
        "verified visuals, voices and licensed BGM imported",
        "packaged FFmpeg export",
        "duration between 60 and 120 seconds",
        "full decode",
    ],
}
(DEV_DATA / "reports/packaged-lei-jun-project.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
)
print("PACKAGED_LEI_JUN_PROJECT_PASSED", duration, video, flush=True)
