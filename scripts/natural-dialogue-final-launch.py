"""Verify the final packaged app after a normal cold start."""

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import socket
import sys
import time

import httpx


sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = Path(os.environ["APPDATA"]) / "LimeStudio" / "workspace"
PROJECT_ID = "ea015234e5974074a8191917d78163e7"


def visible_window(pid: int) -> bool:
    found = False
    user32 = ctypes.windll.user32

    def callback(hwnd, _):
        nonlocal found
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if process_id.value == pid and user32.IsWindowVisible(hwnd):
            found = True
            return False
        return True

    user32.EnumWindows(ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(callback), 0)
    return found


deadline = time.monotonic() + 30
runtime = None
while time.monotonic() < deadline:
    try:
        runtime = json.loads((WORKSPACE / "runtime.json").read_text(encoding="utf-8-sig"))
        token = (WORKSPACE / "session-token").read_text(encoding="utf-8").strip()
        client = httpx.Client(
            base_url=runtime["backendUrl"],
            headers={"Authorization": "Bearer " + token},
            timeout=5,
        )
        diagnostics = client.get("/api/diagnostics").raise_for_status().json()
        break
    except (OSError, ValueError, httpx.HTTPError):
        time.sleep(0.5)
else:
    raise TimeoutError("final packaged backend did not become ready")

project = client.get("/api/projects/" + PROJECT_ID).raise_for_status().json()
prompts = {item["id"]: item for item in client.get("/api/prompts").raise_for_status().json()}
assets = client.get("/api/assets").raise_for_status().json()
dialogue = [scene for scene in project["scenes"] if scene["dialogue"].strip()]
narration = [scene for scene in project["scenes"] if scene["narration"].strip()]

with socket.socket() as probe:
    probe.settimeout(0.4)
    debugging_port_enabled = probe.connect_ex(("127.0.0.1", 9225)) == 0

assert runtime["packaged"] is True
assert visible_window(runtime["appPid"])
assert not debugging_port_enabled
assert diagnostics["agent"]["ready"] and diagnostics["agent"]["running"] == 0
assert diagnostics["media"]["ffmpeg"]["ready"]
assert len(project["scenes"]) == 6 and len(dialogue) == 4 and not narration
assert not any(scene["audio_id"] for scene in project["scenes"])
assert all(scene["speaker_id"] for scene in dialogue)
assert project["export_id"] and any(asset["id"] == project["export_id"] for asset in assets)
for key in ("skill_screenwriting", "skill_visual_video", "agnes_prompt_adapter"):
    assert prompts[key]["template_version"] == 10
assert "自然对白" in prompts["skill_screenwriting"]["text"]
assert "自然对白" in prompts["skill_visual_video"]["text"]
assert all(
    keyword in prompts["agnes_prompt_adapter"]["text"]
    for keyword in ("dialogue", "speaker_id", "口型同步")
)
dialogue_timings = []
for scene in dialogue:
    start = scene["dialogue_start"]
    end = scene["dialogue_end"]
    assert start is not None and end is not None
    assert 0 < start < end <= scene["duration"]
    dialogue_timings.append(
        {
            "scene_id": scene["id"],
            "start": start,
            "end": end,
            "duration": scene["duration"],
        }
    )

report = {
    "status": "passed",
    "app_pid": runtime["appPid"],
    "packaged": True,
    "version": runtime["version"],
    "window_visible": True,
    "debugging_port_enabled": False,
    "agent_ready": True,
    "agent_running_jobs": diagnostics["agent"]["running"],
    "ffmpeg_ready": True,
    "creative_skill_prompt_version": 10,
    "project_id": PROJECT_ID,
    "scene_count": len(project["scenes"]),
    "dialogue_scene_count": len(dialogue),
    "narration_scene_count": len(narration),
    "external_tts_tracks": sum(bool(scene["audio_id"]) for scene in project["scenes"]),
    "dialogue_timings": dialogue_timings,
    "export_id": project["export_id"],
}
(ROOT / "data/reports/drama-natural-dialogue-final-launch.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
)
(ROOT / "data/reports/subtitle-timing-final-launch.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
)
print("NATURAL_DIALOGUE_FINAL_LAUNCH_PASSED", report, flush=True)
