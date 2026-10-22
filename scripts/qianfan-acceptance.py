"""Bounded live LLM acceptance: Codex saves text/board and calls real visual tool.

Does not generate paid images or videos. Credentials are read only by the backend.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
import httpx

sys.stdout.reconfigure(encoding="utf-8")
root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--native", action="store_true")
args = parser.parse_args()
data = (
    Path(os.environ["APPDATA"]) / "LimeStudio/workspace"
    if args.native
    else root / "data"
)
if args.native:
    base = json.loads((data / "runtime.json").read_text(encoding="utf-8"))["backendUrl"]
else:
    base = "http://127.0.0.1:" + str(
        json.loads((data / "dev-services.json").read_text(encoding="utf-8-sig"))[
            "backend_port"
        ]
    )
token = (data / "session-token").read_text(encoding="utf-8").strip()
out = (
    root
    / "data/reports"
    / ("qianfan-native-acceptance.json" if args.native else "qianfan-acceptance.json")
)
report = {
    "status": "running",
    "native": args.native,
    "stages": [],
    "started_at": time.time(),
}


def persist():
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


with httpx.Client(
    base_url=base, headers={"Authorization": "Bearer " + token}, timeout=180
) as client:

    def call(method, url, body=None):
        r = client.request(method, url, json=body)
        if r.is_error:
            raise RuntimeError(f"Local API HTTP {r.status_code}: {r.text[:2000]}")
        return r.json()

    def run(endpoint, body):
        job = call("POST", endpoint, body)
        report["stages"].append({"job_id": job["id"], "request": body})
        persist()
        deadline = time.monotonic() + 240
        while True:
            value = call("GET", "/api/jobs/" + job["id"])
            if value["status"] in {"failed", "cancelled"}:
                raise RuntimeError(value.get("error") or value.get("message"))
            if value["status"] == "completed":
                report["stages"][-1]["result"] = value
                persist()
                return value
            if time.monotonic() > deadline:
                call("POST", "/api/jobs/" + job["id"] + "/cancel")
                raise TimeoutError("LLM acceptance exceeded four minutes")
            time.sleep(0.5)

    try:
        settings = call("GET", "/api/settings")
        assert (
            settings["llm_provider"] == "qianfan"
            and settings["text_model"] == "deepseek-v4-flash"
            and settings["vision_model"] == "kimi-k2.6"
        )
        assert settings["key_configured"] and settings["llm_key_configured"]
        assert settings["base_url"] == "https://api.agnes-ai.cn/v1"
        assert (
            not {"api_key", "llm_api_key", "encrypted_key", "encrypted_llm_key"}
            & settings.keys()
        )
        report["settings"] = {
            k: settings[k]
            for k in [
                "llm_provider",
                "llm_base_url",
                "text_model",
                "vision_model",
                "base_url",
                "image_model",
                "video_model",
            ]
        }
        models = call("GET", "/api/settings/models?service=llm")
        assert {"deepseek-v4-flash", "kimi-k2.6"} <= set(models)
        project = call(
            "POST",
            "/api/projects",
            {
                "kind": "narration",
                "title": "千帆接入验证",
                "prompt": "讲述窗边一杯热茶带来的片刻平静",
                "target_duration": 10,
                "scene_count": 2,
            },
        )
        pid = project["id"]
        report["project_id"] = pid
        persist()
        run("/api/projects/" + pid + "/run", {"action": "idea"})
        project = call("GET", "/api/projects/" + pid)
        assert (
            project["script"].strip()
            and not project["scenes"]
            and not project["export_id"]
        )
        report["idea_script"] = project["script"]
        custom = "窗边，一杯热茶慢慢升起白雾。放下手机，让心静一静。"
        call(
            "PATCH",
            "/api/projects/" + pid,
            {"revision": project["revision"], "script": custom},
        )
        run("/api/projects/" + pid + "/run", {"action": "storyboard"})
        project = call("GET", "/api/projects/" + pid)
        assert len(project["scenes"]) == 2 and project["script"] == custom
        assert (
            "".join(s["narration"] for s in project["scenes"]).replace(" ", "")
            == custom
        )
        picture = next(
            a
            for a in call("GET", "/api/assets")
            if a["mime"].startswith("image/") and a["source"] == "generated"
        )
        report["visual_asset"] = {
            "id": picture["id"],
            "name": picture["name"],
            "path": picture["path"],
        }
        run(
            "/api/projects/" + pid + "/chat",
            {
                "message": f"调用 studio_inspect_asset 观察图片资产 {picture['id']} 的实际画面，不要根据文件名或描述猜测。根据工具返回的画面写一句中文旁白，用 studio_save_script 保存到当前作品。只保存文案，不生成或绑定媒体，不改变分镜，不导出。"
            },
        )
        traces = call("GET", "/api/traces")
        job_ids = {stage["job_id"] for stage in report["stages"]}
        relevant = [
            t
            for t in traces
            if t.get("job_id") in job_ids
            or (
                t.get("kind") in {"agent_model", "llm_model"}
                and t.get("updated_at", 0) >= report["started_at"]
            )
        ]
        report["traces"] = relevant
        tools = {t.get("tool") for t in relevant if t.get("event") == "tool_completed"}
        assert {
            "studio_context",
            "studio_save_script",
            "studio_save_storyboard",
            "studio_inspect_asset",
        } <= tools, tools
        assert any(
            t.get("model") == "kimi-k2.6" and t.get("status") == "completed"
            for t in relevant
        )
        assert any(
            t.get("model") == "deepseek-v4-flash" and t.get("status") == "completed"
            for t in relevant
        )
        project = call("GET", "/api/projects/" + pid)
        assert (
            project["script"] != custom
            and project["script"].strip()
            and not project["export_id"]
        )
        assert all(
            not s.get("first_frame_id")
            and not s.get("video_id")
            and not s.get("audio_id")
            for s in project["scenes"]
        )
        report["visual_script"] = project["script"]
        report["checks"] = [
            "independent encrypted LLM/media settings",
            "real account model discovery",
            "Codex + DeepSeek native Responses tool roundtrip",
            "idea writes script only",
            "custom script split without rewriting",
            "real Kimi image pixels through Codex tool",
            "visual result saved by text agent",
            "no generated media or export",
        ]
        report["status"] = "passed"
        print(
            json.dumps(
                {
                    "status": "passed",
                    "native": args.native,
                    "project_id": pid,
                    "checks": report["checks"],
                },
                ensure_ascii=False,
            )
        )
    except Exception as error:
        report.update(status="failed", error=str(error))
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False))
        raise
    finally:
        report["duration_seconds"] = round(time.time() - report["started_at"], 2)
        persist()
