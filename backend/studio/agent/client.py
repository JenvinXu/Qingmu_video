from __future__ import annotations
import os
import re
import httpx
from ..core.paths import INTERNAL_TOKEN
from ..domain import projects
from ..jobs.manager import jobs
from ..core.store import store
from .prompts import prepare


def gateway_url():
    return os.environ.get("LIME_AGENT_URL", "http://127.0.0.1:4319")


def _gateway_error(result: httpx.Response) -> str:
    try:
        value = result.json()
        return str(value.get("error") or value.get("detail") or result.text)
    except (ValueError, AttributeError):
        return result.text


def _provider_error_detail(value: str) -> str:
    """Turn provider/network errors into concise UI text without hiding evidence."""
    text = (value or "").strip()
    lowered = text.lower()
    request = re.search(r"request id:\s*([^)'\"\s}]+)", text, re.IGNORECASE)
    request_suffix = f"；请求 ID：{request.group(1)}" if request else ""
    if "video_queue_full" in lowered or "video_queue_unavailable" in lowered or "视频队列已满" in text:
        return f"视频模型队列已满，请稍后重试（HTTP 503 / video_queue_full{request_suffix}）"
    if "fetch failed" in lowered or "winerror 10054" in lowered or "connection reset" in lowered:
        return f"与模型服务的连接中断（原始错误：{text[:500]}），请稍后重试"
    if "http 401" in lowered or "unauthorized" in lowered or "invalid api key" in lowered:
        return f"模型 API Key 无效或已失效（原始错误：{text[:500]}），请在模型设置中更新"
    if "http 403" in lowered or "forbidden" in lowered:
        return f"当前 API Key 没有调用该模型的权限（原始错误：{text[:500]}）"
    if "http 429" in lowered or "rate limit" in lowered:
        return f"模型服务请求过于频繁或额度不足（原始错误：{text[:500]}），请稍后重试"
    return text[:1200] or "模型服务没有返回具体错误"


def _failed_stage(job_id: str) -> str:
    try:
        job = store.get("job", job_id)
    except KeyError:
        return "视频制作"
    stage = job.get("stage", "")
    labels = {
        "image": "首帧生成",
        "storyboard_image": "故事版生成",
        "video": "视频生成",
        "voice": "旁白生成",
        "export": "视频导出",
        "materials": "素材搜集",
    }
    action_markers = {
        "image": ("生成首帧",),
        "storyboard_image": ("生成九宫格故事版",),
        "video": ("生成视频",),
        "voice": ("制作旁白",),
        "export": ("开始剪辑", "成片"),
        "materials": ("检索视频", "素材"),
    }
    markers = action_markers.get(stage, ())
    for event in reversed(job.get("events", [])):
        message = str(event.get("message", ""))
        if event.get("stage") == stage and any(marker in message for marker in markers):
            return message
    return labels.get(stage, "视频制作")


def _unfinished_export_error(response: dict, job_id: str) -> str:
    failure = response.get("last_tool_failure") or {}
    raw = str(failure.get("error") or "").strip()
    if raw:
        return (
            f"{_failed_stage(job_id)}失败：{_provider_error_detail(raw)}。"
            "已完成的分镜和素材已保留，可直接重试未完成部分。"
        )
    message = str(response.get("message") or "").strip()
    if message:
        return "视频没有完成导出：" + message[:1200]
    return "视频没有完成导出，Agent 未返回具体原因；请在连接与验收中查看任务记录"


async def agent_run(project_id, job_id, message, action="chat"):
    project = projects.get(project_id)
    initial_revision = project["revision"]
    initial_script = project.get("script", "")
    message, prompt_versions = prepare(project, action, message)
    store.save(
        "trace",
        {
            "kind": "prompt",
            "job_id": job_id,
            "project_id": project_id,
            "event": "prompt_applied",
            "templates": prompt_versions,
            "message": message,
        },
    )
    jobs.event(job_id, "agent", "Codex 正在理解要求并操作工作台", 5)
    async with httpx.AsyncClient(timeout=httpx.Timeout(3600, connect=15)) as client:
        result = await client.post(
            gateway_url() + "/agent/run",
            headers={"Authorization": "Bearer " + INTERNAL_TOKEN},
            json={
                "projectId": project_id,
                "jobId": job_id,
                "kind": project["kind"],
                "message": message,
                "action": action,
            },
        )
        if result.is_error:
            raise RuntimeError(
                "Codex 执行失败：" + _provider_error_detail(_gateway_error(result))
            )
        response = result.json()
    final = projects.get(project_id)
    if action == "idea" and (
        final["revision"] <= initial_revision or not final.get("script", "").strip()
    ):
        raise ValueError(
            "Codex 没有保存有效文案：" + response.get("message", "")[:1200]
        )
    if action == "storyboard":
        if (
            final["revision"] <= initial_revision
            or not final.get("scenes")
            or (
                project.get("scene_count")
                and len(final.get("scenes", [])) != project["scene_count"]
            )
        ):
            raise ValueError("Codex 保存的分镜数量与要求不一致，请重试")
        if final.get("script") != initial_script:
            # The user's script remains authoritative even if the model paraphrases it.
            final = projects.commit(final, script=initial_script)
        if project["kind"] == "narration" and "".join(
            "".join(scene["narration"].split()) for scene in final["scenes"]
        ) != "".join(initial_script.split()):
            raise ValueError("口播分段没有完整保留原文，请重试或在画面设置中修正旁白")
    if action == "auto" and not final.get("export_id"):
        raise ValueError(_unfinished_export_error(response, job_id))
    if action == "plan" and not final.get("scenes"):
        raise ValueError(
            "Codex 没有保存有效分镜：" + response.get("message", "")[:1200]
        )
    return {**response, "project_id": project_id, "asset_id": final.get("export_id")}


async def cancel_agent(job_id):
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                gateway_url() + "/agent/cancel",
                json={"jobId": job_id},
                headers={"Authorization": "Bearer " + INTERNAL_TOKEN},
            )
    except httpx.HTTPError:
        pass
