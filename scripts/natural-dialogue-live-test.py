"""Exercise the packaged Agent's short-drama dialogue contract with real LLM calls."""

import json
import math
import os
from pathlib import Path
import sys
import time

import httpx


sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = Path(os.environ["APPDATA"]) / "LimeStudio" / "workspace"
SOURCE_PROJECT = "ea015234e5974074a8191917d78163e7"


def wait(client: httpx.Client, job: dict) -> dict:
    for _ in range(360):
        state = client.get("/api/jobs/" + job["id"]).json()
        if state["status"] in {"completed", "failed", "cancelled"}:
            if state["status"] != "completed":
                raise RuntimeError(state.get("error") or state["status"])
            return state
        time.sleep(0.5)
    raise TimeoutError(job["id"])


runtime = json.loads((WORKSPACE / "runtime.json").read_text(encoding="utf-8-sig"))
token = (WORKSPACE / "session-token").read_text(encoding="utf-8").strip()
client = httpx.Client(
    base_url=runtime["backendUrl"],
    headers={"Authorization": "Bearer " + token},
    timeout=30,
)
source = client.get("/api/projects/" + SOURCE_PROJECT).json()
created = client.post(
    "/api/projects",
    json={
        "kind": "drama",
        "title": "自然对白规则验证",
        "prompt": "台风夜，姐姐想独自修好父亲留下的站灯，弟弟赶来阻止；两人争执后发现列车即将进站，决定一起点亮灯。用人物对话推动冲突和和解，不要逐镜旁白。",
        "aspect": "16:9",
        "target_duration": 15,
        "shot_duration": 5,
        "video_size": "720P",
        "asset_ids": source["asset_ids"],
    },
).json()
stages = []
try:
    for action in ("idea", "storyboard"):
        job = client.post(
            f"/api/projects/{created['id']}/run", json={"action": action}
        ).json()
        finished = wait(client, job)
        stages.append(
            {
                "action": action,
                "job_id": job["id"],
                "status": finished["status"],
            }
        )
        print(action.upper() + "_PASSED", flush=True)
    project = client.get("/api/projects/" + created["id"]).json()
    scenes = project["scenes"]
    dialogue = [scene for scene in scenes if scene.get("dialogue", "").strip()]
    narration = [scene for scene in scenes if scene.get("narration", "").strip()]
    assert len(scenes) == 3
    assert len(dialogue) >= math.ceil(len(scenes) * 0.6)
    assert len(narration) <= math.floor(len(scenes) * 0.2)
    assert all(
        scene.get("speaker_id")
        and scene["asset_ids"]
        and scene["asset_ids"][0] == scene["speaker_id"]
        for scene in dialogue
    )
    assert not any(scene.get("audio_id") for scene in scenes)
    assert all(
        scene["dialogue"] in scene["video_prompt"]
        and "口型" in scene["video_prompt"]
        for scene in dialogue
    )
    report = {
        "status": "passed",
        "packaged": runtime["packaged"],
        "project_id": created["id"],
        "stages": stages,
        "scene_count": len(scenes),
        "dialogue_scene_count": len(dialogue),
        "narration_scene_count": len(narration),
        "external_tts_tracks": sum(bool(scene.get("audio_id")) for scene in scenes),
        "scenes": [
            {
                "title": scene["title"],
                "dialogue": scene["dialogue"],
                "speaker_id": scene.get("speaker_id"),
                "narration": scene["narration"],
                "natural_video_prompt": "口型" in scene["video_prompt"],
            }
            for scene in scenes
        ],
    }
    (ROOT / "data/reports/drama-natural-dialogue-agent.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("NATURAL_DIALOGUE_AGENT_PASSED", flush=True)
finally:
    client.delete("/api/projects/" + created["id"])
