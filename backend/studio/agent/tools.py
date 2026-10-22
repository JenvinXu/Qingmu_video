from __future__ import annotations
from ..core.store import store
from ..domain import projects
from ..domain.models import Storyboard, ProjectPatch, Scene, CharacterCreate
from ..library.service import asset
from ..jobs.manager import jobs
from ..workflows import production
from ..providers.settings import read_settings
from ..providers.llm import LLM


async def execute(project_id: str, job_id: str, name: str, args: dict):
    project = projects.get(project_id)
    if job_id:
        job = store.get("job", job_id)
        if job["status"] != "running":
            raise ValueError("任务已结束，不能继续修改项目")
        if job.get("project_id") not in {None, project_id}:
            raise ValueError("工具请求与当前作品不匹配")
    if name == "studio_inspect_asset":
        return await LLM().inspect_asset(
            args["asset_id"],
            args.get("question")
            or "描述图片中的人物、物品、环境、构图和颜色，供视频创作参考。",
        )
    if name == "studio_previous_tail":
        return await production.attach_previous_tail(
            project_id, args["scene_id"], job_id
        )
    if name == "studio_create_character":
        value = await production.make_character(
            CharacterCreate.model_validate(args), job_id
        )
        current = projects.get(project_id)
        updated = projects.patch(
            project_id,
            ProjectPatch(
                revision=current["revision"],
                asset_ids=[*current.get("asset_ids", []), value["id"]],
            ),
        )
        return {"asset": value, "revision": updated["revision"]}
    if name == "studio_context":
        return {
            "project": project,
            "models": read_settings(),
            "assets": [
                {
                    k: a.get(k)
                    for k in (
                        "id",
                        "name",
                        "kind",
                        "description",
                        "voice",
                        "voice_asset_id",
                        "voice_description",
                        "source_url",
                        "license",
                        "info",
                        "text",
                    )
                }
                for a in store.list("asset", 80)
                if a.get("source") != "export"
                and (
                    project["kind"] != "drama"
                    or a["id"] in project.get("asset_ids", [])
                )
            ],
        }
    if name == "studio_save_storyboard":
        value = projects.save_storyboard(project_id, Storyboard.model_validate(args))
        jobs.event(job_id, "storyboard", f"已保存 {len(value['scenes'])} 个镜头", 15)
        return {"revision": value["revision"], "scenes": value["scenes"]}
    if name == "studio_save_script":
        value = projects.save_script(
            project_id, args["script"], args.get("synopsis", "")
        )
        jobs.event(job_id, "script", "文案已保存", 95)
        return {"revision": value["revision"], "script": value["script"]}
    if name == "studio_produce":
        child = jobs.start_production(
            project_id,
            lambda production_job_id: production.produce(
                project_id, production_job_id
            ),
        )
        return {
            "scheduled": True,
            "job_id": child["id"],
            "status": child["status"],
            "message": "真实媒体制作已交给后台任务；界面会持续显示进度。不要重复提交。",
        }
    if name == "studio_generate_stage":
        return await production.generate_stage(project_id, job_id, args["stage"])
    if name == "studio_generate_scene":
        return await production.generate_scene(
            project_id, args["scene_id"], args["action"], job_id
        )
    if name == "studio_export":
        return await production.export(project_id, job_id)
    if name == "studio_edit_scene":
        scene = production.scene_by_id(project, args["scene_id"])
        permitted = {
            "title",
            "description",
            "dialogue",
            "speaker_id",
            "dialogue_start",
            "dialogue_end",
            "narration",
            "voice",
            "image_prompt",
            "video_prompt",
            "image_model",
            "video_model",
            "aspect",
            "video_seconds",
            "video_size",
            "material_query",
            "match_reason",
            "match_score",
            "duration",
            "trim_in",
            "asset_ids",
            "reference_ids",
            "first_frame_id",
            "video_id",
            "audio_id",
            "sfx_id",
            "sfx_volume",
            "sfx_offset",
        }
        changes = args.get("changes", {})
        if set(changes) - permitted:
            raise ValueError("镜头修改包含未知字段")
        updated = Scene.model_validate({**scene, **changes}).model_dump()
        scenes = [updated if s["id"] == scene["id"] else s for s in project["scenes"]]
        return projects.patch(
            project_id, ProjectPatch(revision=project["revision"], scenes=scenes)
        )
    if name == "studio_reorder":
        ids = args["scene_ids"]
        lookup = {s["id"]: s for s in project["scenes"]}
        if len(ids) != len(lookup) or set(ids) != set(lookup):
            raise ValueError("排序必须包含所有镜头且每镜一次")
        return projects.patch(
            project_id,
            ProjectPatch(revision=project["revision"], scenes=[lookup[i] for i in ids]),
        )
    if name == "studio_bind_asset":
        scene = production.scene_by_id(project, args["scene_id"])
        value = asset(args["asset_id"])
        role = args.get("role", "reference")
        if role == "reference":
            scene["asset_ids"] = list(dict.fromkeys(scene["asset_ids"] + [value["id"]]))
        else:
            field = {
                "first_frame": "first_frame_id",
                "video": "video_id",
                "audio": "audio_id",
                "sound_effect": "sfx_id",
            }.get(role)
            if not field:
                raise ValueError("未知素材角色")
            scene[field] = value["id"]
            if project["kind"] == "narration" and role in {"first_frame", "video"}:
                scene["match_reason"] = (
                    f"素材「{value['name']}」与本段口播的主体、地点和动作已确认对应"
                )
                scene["match_score"] = max(scene.get("match_score") or 0, 80)
        return projects.patch(
            project_id,
            ProjectPatch(revision=project["revision"], scenes=project["scenes"]),
        )
    raise ValueError("未注册的软件操作工具：" + name)
