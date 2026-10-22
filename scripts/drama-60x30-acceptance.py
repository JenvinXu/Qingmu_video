"""Real Agent regression: a 60-second drama with 30-second shots is exactly 2 x 30."""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")
root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--native", action="store_true")
parser.add_argument("--keep", action="store_true")
args = parser.parse_args()
data = Path(os.environ["APPDATA"]) / "LimeStudio/workspace" if args.native else root / "data"
runtime_file = data / ("runtime.json" if args.native else "dev-services.json")
runtime = json.loads(runtime_file.read_text(encoding="utf-8-sig"))
base = (
    runtime["backendUrl"]
    if args.native
    else "http://127.0.0.1:" + str(runtime["backend_port"])
)
token = (data / "session-token").read_text(encoding="utf-8").strip()
client = httpx.Client(base_url=base, headers={"Authorization": "Bearer " + token}, timeout=30)
project = None


def call(method, path, body=None):
    response = client.request(method, path, json=body)
    if response.is_error:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:1200]}")
    return response.json()


def run(project_id, action, timeout=300):
    started = call("POST", f"/api/projects/{project_id}/run", {"action": action})
    job_id = (started.get("job") or started)["id"]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = call("GET", "/api/jobs/" + job_id)
        if job["status"] == "completed":
            return job
        if job["status"] in {"failed", "cancelled"}:
            raise RuntimeError(job.get("error") or job.get("message") or job["status"])
        time.sleep(0.5)
    raise TimeoutError(f"{action} did not finish in {timeout}s")


def script_durations(script):
    matches = re.findall(r"[（(](\d+)[-–—~至](\d+)秒?[）)]\s*分镜\s*0*\d+\s*[：:]", script)
    return [int(end) - int(start) for start, end in matches]


try:
    project = call(
        "POST",
        "/api/projects",
        {
            "kind": "drama",
            "title": "60秒双分镜回归验收",
            "prompt": "一粒种子在雨后破土，最终长成迎着朝阳的小树。",
            "target_duration": 60,
            "shot_duration": 30,
        },
    )
    run(project["id"], "idea")
    after_idea = call("GET", "/api/projects/" + project["id"])
    assert after_idea["scene_count"] == 2
    assert script_durations(after_idea["script"]) == [30, 30]
    run(project["id"], "storyboard")
    completed = call("GET", "/api/projects/" + project["id"])
    durations = [scene["duration"] for scene in completed["scenes"]]
    video_seconds = [scene["video_seconds"] for scene in completed["scenes"]]
    assert completed["scene_count"] == 2
    assert durations == [30, 30]
    assert video_seconds == [30, 30]
    report = {
        "status": "passed",
        "native": args.native,
        "project_id": project["id"] if args.keep else None,
        "target_duration": 60,
        "shot_duration": 30,
        "script_durations": [30, 30],
        "scene_durations": durations,
        "video_seconds": video_seconds,
        "verified_at": time.time(),
    }
    output = root / "data/reports" / (
        "drama-60x30-native.json" if args.native else "drama-60x30-dev.json"
    )
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("DRAMA_60X30_ACCEPTANCE_PASSED", json.dumps(report, ensure_ascii=False))
finally:
    if project and not args.keep:
        try:
            call("DELETE", "/api/projects/" + project["id"])
        except Exception:
            pass
    client.close()
