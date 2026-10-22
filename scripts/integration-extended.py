"""Live reference-image, Codex trim/export, and MCP checks. Uses configured services."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import httpx

sys.stdout.reconfigure(encoding="utf-8")
root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:4348")
args = parser.parse_args()
data = root / "data"
client = httpx.Client(
    base_url=args.url,
    headers={"Authorization": "Bearer " + (data / "session-token").read_text().strip()},
    timeout=120,
)


def api(path, method="GET", **kwargs):
    r = client.request(method, path, **kwargs)
    r.raise_for_status()
    return r.json()


def wait(job):
    last = ""
    deadline = time.monotonic() + 1500
    while time.monotonic() < deadline:
        value = api("/api/jobs/" + job["id"])
        if value["message"] != last:
            print(value["message"], flush=True)
            last = value["message"]
        if value["status"] in {"completed", "failed", "cancelled"}:
            assert value["status"] == "completed", value.get("error")
            return value
        time.sleep(4)
    raise TimeoutError("Live integration did not finish")


projects = api("/api/projects")
original = next(p for p in projects if p["kind"] == "drama" and p.get("export_id"))
assets = {a["id"]: a for a in api("/api/assets")}
frame = assets[original["scenes"][0]["first_frame_id"]]
with (data / "media" / frame["path"]).open("rb") as file:
    character = api(
        "/api/assets/import",
        "POST",
        files={"file": ("青年主角.png", file, "image/png")},
        data={
            "kind": "character",
            "description": "短棕色卷发青年，浅绿色衬衫，温暖电影风格；保持参考人物五官和服装",
            "voice": "zh-CN-YunxiNeural",
        },
    )
prop_job = api(
    "/api/assets/generate",
    "POST",
    json={
        "name": "旧信封",
        "kind": "prop",
        "prompt": "一封泛黄的旧信封和展开的米白色信纸，干净白色背景，温暖电影质感，只展示物品，不要文字标记",
    },
)
prop_result = wait(prop_job)
prop_id = prop_result["result"]["asset_id"]
project = api(
    "/api/projects",
    "POST",
    json={
        "kind": "drama",
        "title": "参考示例 · 青年与旧信",
        "scene_count": 1,
        "aspect": "16:9",
    },
)
scene = {
    "id": "reference-scene",
    "title": "青年读信",
    "description": "同一位浅绿色衬衫青年，在窗边拿起旧信封。",
    "image_prompt": "参考角色照片中的青年，保持完全相同的五官、卷发和浅绿色衬衫；他站在暖阳窗边，拿着参考物品图片中的泛黄信封，电影中景，无文字。",
    "narration": "",
    "duration": 5,
    "asset_ids": [character["id"], prop_id],
}
api(
    "/api/projects/" + project["id"],
    "PATCH",
    json={"revision": project["revision"], "scenes": [scene]},
)
image_job = api(
    "/api/projects/" + project["id"] + "/run",
    "POST",
    json={"action": "image", "scene_id": "reference-scene"},
)
wait(image_job)
reference = api("/api/projects/" + project["id"])
result = next(
    a for a in api("/api/assets") if a["id"] == reference["scenes"][0]["first_frame_id"]
)
assert set(result["reference_ids"]) == {character["id"], prop_id}
print("REFERENCE_IMAGE_PASSED", flush=True)
clone = api(
    "/api/projects",
    "POST",
    json={
        "kind": "drama",
        "title": "Codex 重剪示例",
        "aspect": "16:9",
        "scene_count": 2,
        "target_duration": 9,
    },
)
clone = api(
    "/api/projects/" + clone["id"],
    "PATCH",
    json={"revision": clone["revision"], "scenes": original["scenes"]},
)
job = api(
    "/api/projects/" + clone["id"] + "/chat",
    "POST",
    json={
        "message": "只重新剪辑，禁止重新生成图片、视频、旁白。把第二个镜头时长改成4秒，源视频入点设为0.5秒；第一镜头保持5秒。所有已绑定的真实视频和旁白保持不变。调用软件工具保存修改，然后导出完整9秒视频。不要改画面描述、提示词或旁白文案。"
    },
)
wait(job)
edited = api("/api/projects/" + clone["id"])
assert (
    edited["export_id"]
    and edited["scenes"][1]["duration"] == 4
    and edited["scenes"][1]["trim_in"] == 0.5
)
assert [s["video_id"] for s in edited["scenes"]] == [
    s["video_id"] for s in original["scenes"]
]
export = next(a for a in api("/api/assets") if a["id"] == edited["export_id"])
assert 8.9 < export["info"]["duration"] < 9.2
print("CODEX_REEDIT_PASSED", flush=True)
messages = [
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-06-18"},
    },
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "studio_diagnostics", "arguments": {}},
    },
]
process = subprocess.run(
    [sys.executable, str(root / "scripts/mcp_server.py")],
    input="".join(json.dumps(v) + "\n" for v in messages),
    capture_output=True,
    text=True,
    encoding="utf-8",
    timeout=30,
    env={**os.environ, "LIME_BACKEND_URL": args.url, "LIME_DATA_DIR": str(data)},
)
responses = [json.loads(line) for line in process.stdout.splitlines()]
assert responses[0]["result"]["protocolVersion"] == "2025-06-18"
assert len(responses[1]["result"]["tools"]) == 6
assert json.loads(responses[2]["result"]["content"][0]["text"])["media"]["ffmpeg"][
    "ready"
]
report = {
    "status": "passed",
    "reference_project": project["id"],
    "character": character["id"],
    "prop": prop_id,
    "reference_image": result["id"],
    "codex_reedit_project": edited["id"],
    "export": export["id"],
    "info": export["info"],
    "mcp_tools": 6,
}
(data / "reports/integration-extended.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
)
print("EXTENDED_INTEGRATION_PASSED", flush=True)
