"""Native workflow: uploaded portrait/voice/prop + extracted tail -> real video.

Use --resume to query persisted jobs without repeating generation requests.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
import httpx

sys.stdout.reconfigure(encoding="utf-8")
parser = argparse.ArgumentParser()
parser.add_argument("--resume", action="store_true")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
data = Path(os.environ["APPDATA"]) / "LimeStudio/workspace"
runtime = json.loads((data / "runtime.json").read_text(encoding="utf-8"))
client = httpx.Client(base_url=runtime["backendUrl"], timeout=180,
                     headers={"Authorization": "Bearer " + (data / "session-token").read_text().strip()})
out = root / "data/reports/drama-local-reference-test.json"
report = json.loads(out.read_text(encoding="utf-8")) if args.resume else {
    "status": "running", "native": True, "started_at": time.time(), "stages": {},
}


def persist():
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def call(method, url, body=None):
    response = client.request(method, url, json=body)
    response.raise_for_status()
    return response.json()


def read():
    return call("GET", "/api/projects/" + report["project_id"])


def patch(body):
    return call("PATCH", "/api/projects/" + report["project_id"], {"revision": read()["revision"], **body})


def job(key, body):
    if key not in report["stages"]:
        value = call("POST", "/api/projects/" + report["project_id"] + "/run", body)
        report["stages"][key] = {"job_id": value["id"], "request": body}
        persist()
    stage = report["stages"][key]
    deadline = time.monotonic() + 1000
    while time.monotonic() < deadline:
        value = call("GET", "/api/jobs/" + stage["job_id"])
        if value["status"] in {"completed", "failed", "cancelled"}:
            stage["result"] = value
            persist()
            assert value["status"] == "completed", value.get("error")
            return value["result"]
        time.sleep(0.5)
    raise TimeoutError("Use --resume to query the same generation job")


def upload(value, kind):
    with (data / "media" / value["path"]).open("rb") as file:
        response = client.post("/api/assets/import", data={"kind": kind},
                               files={"file": (value["name"] + Path(value["path"]).suffix, file, value["mime"])})
    response.raise_for_status()
    result = response.json()
    assert not result.get("source_url"), "Input must remain a genuine local upload"
    return result


try:
    if not report.get("setup_complete"):
        assets = call("GET", "/api/assets")
        probe = json.loads((root / "data/reports/local-reference-probe.json").read_text(encoding="utf-8"))
        assert probe["status"] == "passed"
        source_role = next(a for a in assets if a["id"] == probe["reference_asset_ids"][0])
        source_voice = next(a for a in assets if a["id"] == probe["reference_asset_ids"][1])
        source_prop = next(a for a in assets if a["id"] == "2bf89e8eb26e400f99b6c6b218005412")
        photo, voice, prop = upload(source_role, "image"), upload(source_voice, "voice"), upload(source_prop, "prop")
        role = call("POST", "/api/characters", {
            "name": "林小雨 · 本地参考", "photo_asset_id": photo["id"], "voice_asset_id": voice["id"],
            "description": "成年亚洲女性，短黑发、浅绿色衬衫", "voice_description": "清晰温柔的青年女声",
        })["asset"]
        assert not role.get("source_url") and role["voice_asset_id"] == voice["id"]
        project = call("POST", "/api/projects", {"kind": "drama", "title": "本地角色与音色参考实测", "subtitles": False})
        report.update(project_id=project["id"], role_id=role["id"], prop_id=prop["id"], photo_id=photo["id"], voice_id=voice["id"])
        patch({"asset_ids": [role["id"], prop["id"]], "scenes": [
            {"id": "previous", "title": "窗边", "description": "林小雨在窗边微笑。", "duration": 4, "video_id": probe["asset_id"]},
            {"id": "local-input", "title": "读信", "description": "林小雨在窗边拿起旧信封，对镜头轻轻微笑说你好。", "duration": 4,
             "video_seconds": 4, "video_size": "720P", "first_frame_id": photo["id"], "asset_ids": [role["id"], prop["id"]],
             "video_prompt": "保持 <Picture 1> 中人物的浅绿色衬衫和短黑发；使用人物照片和上一镜头尾帧保持人物和窗边环境一致，参考物品为旧信封，参考音频仅用于声音特征，用清晰温柔的中文女声说你好。中景静态镜头，轻轻微笑，自然窗光，无字幕。"},
        ]})
        tail = call("POST", "/api/projects/" + report["project_id"] + "/scenes/local-input/previous-tail")
        assert not tail["asset"].get("source_url") and tail["asset"]["id"] in tail["project"]["scenes"][1]["reference_ids"]
        report.update(tail_id=tail["asset"]["id"], setup_complete=True)
        persist()
        print("NATIVE_LOCAL_REFERENCE_INPUTS_READY", flush=True)
    caps = call("GET", "/api/settings/video-capabilities?model=agnes-video-2.5-flash")
    assert caps["public_urls"] is False and caps["images"] == 5
    job("local_reference_video", {"action": "video", "scene_id": "local-input"})
    assets = call("GET", "/api/assets")
    video = next(a for a in assets if a["id"] == read()["scenes"][1]["video_id"])
    expected = {report[k] for k in ("role_id", "prop_id", "photo_id", "voice_id", "tail_id")}
    # Video metadata records additional references; first frame is a separate scene binding.
    assert set(video["reference_ids"]) == expected - {report["photo_id"]} and video["provider_video_id"]
    assert read()["scenes"][1]["first_frame_id"] == report["photo_id"]
    for value in assets:
        if value["id"] in expected:
            assert not value.get("source_url"), "Never mutate inputs into hosted links"
    report["video"] = video
    exported = job("export", {"action": "export"})
    report["export"] = exported
    assert abs(exported["info"]["duration"] - 8) < 0.2
    subprocess.run([str(root / "release/win-unpacked/resources/media/ffmpeg.exe"), "-v", "error", "-xerror",
                    "-i", str(data / "media" / exported["path"]), "-f", "null", "-"],
                   check=True, capture_output=True, timeout=60)
    report.update(status="passed", checks=["实际上传角色照片、物品图片与音频", "角色关联声音自动展开",
        "上镜尾帧实际提取并加入参考", "4 本地图片 + 1 本地音频真实视频生成", "全部参考绑定完整且未伪造公开 URL",
        "8 秒实际合成和完整解码"], provider_capabilities=caps)
    if not report.get("duration_seconds"):
        report["duration_seconds"] = round(report["stages"]["export"]["result"]["finished_at"] - report["started_at"], 2)
    video_job = report["stages"]["local_reference_video"]["result"]
    report["video_job_seconds"] = round(video_job["finished_at"] - video_job["created_at"], 2)
    report["verified_at"] = time.time()
    persist()
    print("DRAMA_LOCAL_REFERENCE_NATIVE_PASSED", report.get("duration_seconds"), flush=True)
except Exception as error:
    report.update(status="failed", error=str(error))
    persist()
    raise
finally:
    client.close()
