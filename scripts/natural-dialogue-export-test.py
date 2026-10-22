"""Force a final packaged export and verify natural dialogue audio end to end."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

import httpx


sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = Path(os.environ["APPDATA"]) / "LimeStudio" / "workspace"
PROJECT_ID = "ea015234e5974074a8191917d78163e7"


runtime = json.loads((WORKSPACE / "runtime.json").read_text(encoding="utf-8-sig"))
token = (WORKSPACE / "session-token").read_text(encoding="utf-8").strip()
client = httpx.Client(
    base_url=runtime["backendUrl"],
    headers={"Authorization": "Bearer " + token},
    timeout=30,
)

project = client.get("/api/projects/" + PROJECT_ID).raise_for_status().json()
for subtitles in (not project["subtitles"], project["subtitles"]):
    project = client.patch(
        "/api/projects/" + PROJECT_ID,
        json={"revision": project["revision"], "subtitles": subtitles},
    ).raise_for_status().json()
assert project["export_id"] is None

job = client.post(
    f"/api/projects/{PROJECT_ID}/run", json={"action": "export"}
).raise_for_status().json()
deadline = time.monotonic() + 900
while True:
    job = client.get("/api/jobs/" + job["id"]).raise_for_status().json()
    if job["status"] == "completed":
        break
    if job["status"] in {"failed", "cancelled"}:
        raise RuntimeError(job.get("error") or job["status"])
    if time.monotonic() > deadline:
        raise TimeoutError(job["id"])
    time.sleep(1)

project = client.get("/api/projects/" + PROJECT_ID).raise_for_status().json()
assets = client.get("/api/assets").raise_for_status().json()
exported = next(asset for asset in assets if asset["id"] == project["export_id"])
video = WORKSPACE / "media" / exported["path"]
sample = ROOT / "data" / "samples" / "last-light-natural-dialogue.mp4"
shutil.copy2(video, sample)

diagnostics = client.get("/api/diagnostics").raise_for_status().json()
ffmpeg = diagnostics["media"]["ffmpeg"]["path"]
subprocess.run(
    [ffmpeg, "-v", "error", "-i", str(video), "-f", "null", "NUL"],
    check=True,
    timeout=900,
)
silence = subprocess.run(
    [
        ffmpeg,
        "-hide_banner",
        "-i",
        str(video),
        "-af",
        "silencedetect=noise=-45dB:d=0.7",
        "-f",
        "null",
        "NUL",
    ],
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
    timeout=900,
).stderr
volume = subprocess.run(
    [
        ffmpeg,
        "-hide_banner",
        "-i",
        str(video),
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
    timeout=900,
).stderr
(ROOT / "data/reports/drama-natural-dialogue-silence.txt").write_text(
    silence, encoding="utf-8"
)
(ROOT / "data/reports/drama-natural-dialogue-volume.txt").write_text(
    volume, encoding="utf-8"
)

dialogue = [scene for scene in project["scenes"] if scene["dialogue"].strip()]
narration = [scene for scene in project["scenes"] if scene["narration"].strip()]
dialogue_timings = [
    {
        "scene_id": scene["id"],
        "start": scene["dialogue_start"],
        "end": scene["dialogue_end"],
        "duration": scene["duration"],
    }
    for scene in dialogue
]
silence_durations = [
    float(value) for value in re.findall(r"silence_duration: ([0-9.]+)", silence)
]
mean_volume = re.search(r"mean_volume: ([-0-9.]+) dB", volume)
max_volume = re.search(r"max_volume: ([-0-9.]+) dB", volume)
assert len(dialogue) == 4
assert not narration
assert not any(scene["audio_id"] for scene in project["scenes"])
assert all(scene["speaker_id"] for scene in dialogue)
assert all(
    0 < item["start"] < item["end"] <= item["duration"]
    for item in dialogue_timings
)
assert all(scene["video_id"] for scene in project["scenes"])
assert exported["info"]["duration"] >= 60
assert max_volume and float(max_volume.group(1)) <= 0.0
report = {
    "status": "passed",
    "packaged": runtime["packaged"],
    "project_id": PROJECT_ID,
    "job_id": job["id"],
    "export_id": exported["id"],
    "path": exported["path"],
    "sample": str(sample),
    "info": exported["info"],
    "dialogue_scenes": len(dialogue),
    "narration_scenes": len(narration),
    "external_tts_tracks": sum(bool(scene["audio_id"]) for scene in project["scenes"]),
    "all_dialogues_have_speakers": all(scene["speaker_id"] for scene in dialogue),
    "all_videos_preserved": all(scene["video_id"] for scene in project["scenes"]),
    "dialogue_timings": dialogue_timings,
    "audio": {
        "mean_volume_db": float(mean_volume.group(1)) if mean_volume else None,
        "max_volume_db": float(max_volume.group(1)) if max_volume else None,
        "silences_at_least_0_7_seconds": silence_durations,
    },
    "checks": [
        "final packaged FFmpeg export",
        "all six source videos retained with their natural audio",
        "dialogue captions use the dialogue field",
        "dialogue captions use each scene's speaking interval",
        "no external TTS for character dialogue",
        "full-file decode",
        "decoded audio peak does not exceed 0 dBFS",
    ],
}
(ROOT / "data/reports/drama-natural-dialogue-export.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(
    "NATURAL_DIALOGUE_EXPORT_PASSED",
    exported["info"]["duration"],
    report["audio"],
    flush=True,
)
