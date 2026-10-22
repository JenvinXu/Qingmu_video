"""Stdio MCP exposing exactly the same domain commands as the desktop agent."""

from __future__ import annotations
import json
import os
import sys
from pathlib import Path
import httpx

root = Path(__file__).resolve().parents[1]
data = Path(os.environ.get("LIME_DATA_DIR", root / "data"))
base = os.environ.get("LIME_BACKEND_URL", "http://127.0.0.1:4318")
token = (data / "session-token").read_text(encoding="utf-8").strip()
sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")
definitions = [
    {
        "name": "studio_create_character",
        "description": "创建可选照片/声音的角色，生成照片返回后台任务。",
        "inputSchema": {
            "type": "object",
            "properties": {
                k: {"type": "string"}
                for k in [
                    "name",
                    "photo_asset_id",
                    "voice_asset_id",
                    "description",
                    "voice_description",
                    "image_prompt",
                    "image_model",
                ]
            },
            "required": ["name"],
        },
    },
    {
        "name": "studio_previous_tail",
        "description": "提取上一分镜实际尾帧并作为本镜图片参考。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "scene_id": {"type": "string"},
            },
            "required": ["project_id", "scene_id"],
        },
    },
    {
        "name": "studio_inspect_asset",
        "description": "使用独立视觉模型观察真实图片资产，不修改素材描述。",
        "inputSchema": {
            "type": "object",
            "properties": {"asset_id": {"type": "string"}},
            "required": ["asset_id"],
        },
    },
    {
        "name": "studio_projects",
        "description": "列出作品与当前状态",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "studio_assets",
        "description": "列出真实素材库",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "studio_run",
        "description": "制作作品或指定镜头，返回后台任务。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "action": {
                    "type": "string",
                    "enum": [
                        "idea",
                        "storyboard",
                        "plan",
                        "auto",
                        "image",
                        "video",
                        "voice",
                        "images",
                        "voices",
                        "export",
                    ],
                },
                "scene_id": {"type": "string"},
            },
            "required": ["project_id", "action"],
        },
    },
    {
        "name": "studio_status",
        "description": "读取真实任务、步骤和错误",
        "inputSchema": {
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
            "required": ["job_id"],
        },
    },
    {
        "name": "studio_chat",
        "description": "让 Codex 用自然语言控制作品，修改分镜、绑定资产与重新剪辑",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "message": {"type": "string"},
            },
            "required": ["project_id", "message"],
        },
    },
    {
        "name": "studio_diagnostics",
        "description": "读取模型、媒体和本地服务能力",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def call(name, args):
    with httpx.Client(
        base_url=base, headers={"Authorization": "Bearer " + token}, timeout=30
    ) as client:
        if name == "studio_create_character":
            r = client.post("/api/characters", json=args)
        elif name == "studio_previous_tail":
            r = client.post(
                "/api/projects/"
                + args["project_id"]
                + "/scenes/"
                + args["scene_id"]
                + "/previous-tail"
            )
        elif name == "studio_inspect_asset":
            r = client.post("/api/assets/" + args["asset_id"] + "/analyze")
        elif name == "studio_projects":
            r = client.get("/api/projects")
        elif name == "studio_assets":
            r = client.get("/api/assets")
        elif name == "studio_status":
            r = client.get("/api/jobs/" + args["job_id"])
        elif name == "studio_diagnostics":
            r = client.get("/api/diagnostics")
        elif name == "studio_run":
            r = client.post(
                "/api/projects/" + args["project_id"] + "/run",
                json={"action": args["action"], "scene_id": args.get("scene_id")},
            )
        elif name == "studio_chat":
            r = client.post(
                "/api/projects/" + args["project_id"] + "/chat",
                json={"message": args["message"]},
            )
        else:
            raise ValueError("未注册工具")
        r.raise_for_status()
        return r.json()


for line in sys.stdin:
    try:
        message = json.loads(line)
        ident = message.get("id")
        method = message.get("method")
        if ident is None:
            continue
        if method == "initialize":
            requested = message.get("params", {}).get("protocolVersion")
            version = (
                requested
                if requested in {"2024-11-05", "2025-03-26", "2025-06-18"}
                else "2024-11-05"
            )
            result = {
                "protocolVersion": version,
                "serverInfo": {"name": "lime-studio", "version": "1.0.0"},
                "capabilities": {"tools": {}},
            }
        elif method == "tools/list":
            result = {"tools": definitions}
        elif method == "ping":
            result = {}
        elif method == "tools/call":
            params = message["params"]
            value = call(params["name"], params.get("arguments", {}))
            result = {
                "content": [
                    {"type": "text", "text": json.dumps(value, ensure_ascii=False)}
                ],
                "isError": False,
            }
        else:
            raise ValueError("未实现方法")
        output = {"jsonrpc": "2.0", "id": ident, "result": result}
    except Exception as error:
        output = {
            "jsonrpc": "2.0",
            "id": message.get("id") if "message" in locals() else None,
            "error": {"code": -32603, "message": str(error)},
        }
    print(json.dumps(output, ensure_ascii=False), flush=True)
