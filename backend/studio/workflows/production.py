from __future__ import annotations
import math
import hashlib
import json
from ..core.store import store
from ..domain import projects
from ..domain.models import CharacterCreate, ProjectPatch
from ..domain.dialogue import dialogue_window
from ..domain.timing import MAX_DRAMA_SCENE_SECONDS
from ..jobs.manager import jobs
from ..library.service import asset, collect
from ..library.sources import search_videos
from ..library.characters import create_character
from ..media.frames import previous_tail
from ..providers.agnes import Agnes
from ..providers.voice import synthesize
from ..media.editor import export_project
from ..library.references import resolve_references
from ..agent import prompts


def scene_by_id(project, ident):
    for scene in project["scenes"]:
        if scene["id"] == ident:
            return scene
    raise ValueError("找不到指定镜头")


def require_running(job_id):
    if store.get("job", job_id)["status"] != "running":
        raise ValueError("任务已取消，已完成的素材保留在素材库")


def update_scene(project_id, scene_id, **changes):
    project = projects.get(project_id)
    scene = scene_by_id(project, scene_id)
    scene.update(changes)
    return projects.commit(project, scenes=project["scenes"], status="producing")


async def attach_previous_tail(project_id, scene_id, job_id=None):
    project = projects.get(project_id)
    value = await previous_tail(project, scene_id)
    if job_id:
        require_running(job_id)
    current = projects.get(project_id)
    if current["revision"] != project["revision"]:
        from ..core.store import Conflict

        raise Conflict("提取期间作品发生变化，请重试")
    scene = scene_by_id(current, scene_id)
    refs = list(dict.fromkeys([*scene.get("reference_ids", []), value["id"]]))
    updated = projects.patch(
        project_id,
        ProjectPatch(
            revision=current["revision"],
            scenes=[
                {**s, "reference_ids": refs} if s["id"] == scene_id else s
                for s in current["scenes"]
            ],
        ),
    )
    return {"asset": value, "project": updated}


async def make_character(value: CharacterCreate, job_id=None):
    photo = None
    if value.image_prompt.strip():
        photo = await Agnes(image_model=value.image_model).image(
            value.image_prompt, "1:1", [], value.name + " · 照片"
        )
    if job_id:
        require_running(job_id)
    return create_character(value, photo)


async def generate_scene(project_id, scene_id, action, job_id, progress=30):
    project = projects.get(project_id)
    scene = scene_by_id(project, scene_id)
    refs = resolve_references(scene, allow_documents=project["kind"] == "narration")
    context = "\n".join(
        f"{a['kind']} · {a['name']}：{a.get('description', '')}"
        + (
            f"；声音描述：{a['voice_description']}"
            if a.get("voice_description")
            else ""
        )
        for a in refs
    )
    jobs.event(
        job_id,
        action,
        f"{scene['title']} · {'生成首帧' if action == 'image' else '生成九宫格故事版' if action == 'storyboard_image' else '生成视频' if action == 'video' else '制作旁白'}",
        progress,
    )
    if action in {"image", "storyboard_image"}:
        image_refs = [
            a
            for a in resolve_references(
                {**scene, "first_frame_id": None},
                allow_documents=project["kind"] == "narration",
            )
            if a.get("mime", "").startswith("image/")
        ]
        if len(image_refs) >= 30:
            raise ValueError(
                f"生成{'故事版' if action == 'storyboard_image' else '首帧'}需要预留 1 个图片位置，请将输入图片减少到 29 张以内"
            )
        model = Agnes(image_model=scene.get("image_model"))
        if action == "storyboard_image":
            entry = prompts.read("drama_scene_storyboard")
            image_prompt = prompts.render(
                entry,
                {
                    "scene_title": scene["title"],
                    "scene_description": scene["description"],
                    "scene_image_prompt": scene.get("image_prompt") or "未单独填写，以分镜文案为准",
                    "scene_video_prompt": scene.get("video_prompt") or "未单独填写，以分镜文案为准",
                    "aspect": scene.get("aspect") or project["aspect"],
                    "reference_context": context or "当前没有已绑定参考素材，请保持九格内部一致。",
                },
            )
        else:
            image_prompt = (
                (scene["image_prompt"] or scene["description"])
                + "\n保持参考主体一致：\n"
                + context
            )
        value = await model.image(
            image_prompt,
            "1:1" if action == "storyboard_image" else (scene.get("aspect") or project["aspect"]),
            image_refs,
            scene["title"] + (" · 九宫格故事版" if action == "storyboard_image" else " · 首帧"),
        )
        require_running(job_id)
        if action == "storyboard_image":
            current = projects.get(project_id)
            current_scene = scene_by_id(current, scene_id)
            refs = list(
                dict.fromkeys(
                    [*current_scene.get("reference_ids", []), value["id"]]
                )
            )
            projects.patch(
                project_id,
                ProjectPatch(
                    revision=current["revision"],
                    scenes=[
                        {**item, "reference_ids": refs}
                        if item["id"] == scene_id
                        else item
                        for item in current["scenes"]
                    ],
                ),
            )
        else:
            changes = {"first_frame_id": value["id"]}
            if not scene.get("video_id"):
                changes.update(
                    material_query=scene.get("material_query")
                    or scene.get("image_prompt")
                    or scene.get("description"),
                    match_reason="依据本段口播、主体动作和画面提示词生成专属画面",
                    match_score=100,
                    status="image_ready",
                )
            update_scene(project_id, scene_id, **changes)
            current = projects.get(project_id)
            current["pending_videos"].pop(scene_id, None)
            store.save("project", current)
    elif action == "video":
        model = Agnes(
            video_model=scene.get("video_model"),
            video_size=scene.get("video_size") or project.get("video_size"),
        )
        first = asset(scene["first_frame_id"]) if scene.get("first_frame_id") else None
        video_refs = [
            a for a in refs if a["id"] != scene.get("first_frame_id")
        ]
        if first and model.settings["video_model"] == "agnes-video-v2.0":
            # V2.0 accepts a public keyframe URL. Collected reference images keep
            # a license landing page as source_url rather than a hotlink. Their
            # visual information is already baked into the generated first frame,
            # so keep audio/video references and submit the first frame alone.
            video_refs = [
                a for a in video_refs if not a.get("mime", "").startswith("image/")
            ]
        signature = hashlib.sha256(
            json.dumps(
                {
                    "scene": {
                        k: scene.get(k)
                        for k in (
                            "first_frame_id",
                            "dialogue",
                            "speaker_id",
                            "dialogue_start",
                            "dialogue_end",
                            "video_prompt",
                            "description",
                            "asset_ids",
                            "reference_ids",
                        )
                    },
                    "model": model.settings["video_model"],
                    "size": model.settings["video_size"],
                    "seconds": math.ceil(scene["duration"]) if project["kind"] == "drama" else (scene.get("video_seconds") or model.settings["video_seconds"]),
                    "aspect": scene.get("aspect") or project["aspect"],
                    "base": model.base,
                    "reference_mapping_version": 1,
                    "reference_context": context,
                    "resolved_references": [
                        {
                            "id": a["id"],
                            "url": a.get("source_url"),
                            "updated_at": a.get("updated_at"),
                        }
                        for a in ([first] if first else []) + video_refs
                        if a
                    ],
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        existing = project.get("pending_videos", {}).get(scene_id)
        if existing and existing.get("signature") != signature:
            existing = None

        def created(pending):
            current = projects.get(project_id)
            current.setdefault("pending_videos", {})[scene_id] = {
                **pending,
                "signature": signature,
            }
            store.save("project", current)

        dialogue_instruction = ""
        if scene.get("dialogue", "").strip():
            speaker = (
                asset(scene["speaker_id"])
                if scene.get("speaker_id")
                else None
            )
            speaker_name = speaker["name"] if speaker else "画面中的说话角色"
            start, end = dialogue_window(scene) or (0, scene["duration"])
            dialogue_instruction = (
                f"\n视频原声对白：在镜头第 {start:g}-{end:g} 秒期间，"
                f"{speaker_name}用自然中文说“{scene['dialogue'].strip()}”。"
                "口型、呼吸、语气、表情和对方反应同步；保留现场环境声，不添加画外旁白。"
            )
        elif scene.get("narration", "").strip():
            dialogue_instruction = "\n本镜没有人物对白，保留自然环境声；旁白由后期单独混入。"
        value = await model.video(
            (scene["video_prompt"] or scene["description"])
            + dialogue_instruction
            + "\n"
            + context,
            scene.get("aspect") or project["aspect"],
            math.ceil(scene["duration"]) if project["kind"] == "drama" else (scene.get("video_seconds") or model.settings["video_seconds"]),
            first,
            video_refs,
            scene["title"] + " · 视频",
            lambda message: jobs.event(job_id, "video", message, progress),
            existing,
            created,
        )
        require_running(job_id)
        update_scene(
            project_id,
            scene_id,
            video_id=value["id"],
            trim_in=0,
            material_query=scene.get("material_query")
            or scene.get("video_prompt")
            or scene.get("description"),
            match_reason=(
                "依据短剧人物、对白、参考素材和运动提示词生成含自然原声的专属视频"
                if project["kind"] == "drama"
                else "依据所选口播片段、参考素材和运动提示词生成专属视频"
            ),
            match_score=100,
            status="video_ready",
        )
        current = projects.get(project_id)
        current["pending_videos"].pop(scene_id, None)
        store.save("project", current)
    elif action == "voice":
        if not scene["narration"].strip():
            return {"skipped": True, "reason": "该镜头未安排旁白"}
        chosen = scene.get("voice") or project["voice"]
        value = await synthesize(scene["narration"], chosen, scene["title"] + " · 旁白")
        require_running(job_id)
        voice_duration = round(value["info"]["duration"] + 0.25, 2)
        # Narration scenes follow the cleaned voice track so the editor does not
        # leave several seconds of dead air after a short sentence. Drama keeps
        # its authored integer shot length because visual timing leads there.
        actual_duration = (
            min(MAX_DRAMA_SCENE_SECONDS, math.ceil(max(scene["duration"], voice_duration)))
            if project["kind"] == "drama"
            else voice_duration
        )
        update_scene(
            project_id,
            scene_id,
            audio_id=value["id"],
            duration=actual_duration,
            **({"video_seconds": actual_duration} if project["kind"] == "drama" else {}),
            status="voice_ready",
        )
    else:
        raise ValueError("不支持的镜头操作")
    return {
        "asset_id": value["id"],
        "kind": value["kind"],
        "info": value.get("info"),
        "name": value["name"],
    }


async def export(project_id, job_id):
    project = projects.get(project_id)
    require_running(job_id)
    if (
        project.get("export_id")
        and project.get("export_revision") == project["revision"]
    ):
        result = asset(project["export_id"])
        jobs.event(job_id, "export", "复用已校验的最新成片", 99)
        return {
            "asset_id": result["id"],
            "project_id": project_id,
            "info": result["info"],
            "path": result["path"],
            "reused": True,
        }
    jobs.event(job_id, "export", "开始剪辑和字幕合成", 85)
    result = await export_project(
        project,
        lambda message, value: jobs.event(
            job_id, "export", message, 85 + round(14 * value)
        ),
    )
    current = projects.get(project_id)
    if current["revision"] != project["revision"]:
        raise ValueError("导出期间作品发生更新，请重新导出")
    current.update(
        export_id=result["id"], export_revision=current["revision"], status="completed"
    )
    store.save("project", current)
    return {
        "asset_id": result["id"],
        "project_id": project_id,
        "info": result["info"],
        "path": result["path"],
    }


async def generate_stage(project_id, job_id, stage):
    """Generate only missing media in one stage; never advance or export."""
    if stage not in {"images", "videos", "voices"}:
        raise ValueError("不支持的制作阶段")
    project = projects.get(project_id)
    if not project["scenes"]:
        raise ValueError("请先保存画面片段")
    results, skipped = [], []
    for index, original in enumerate(project["scenes"]):
        require_running(job_id)
        scene = scene_by_id(projects.get(project_id), original["id"])
        ready = (
            scene.get("first_frame_id") or scene.get("video_id")
            if stage == "images"
            else (
                scene.get("video_id") and (scene.get("match_score") or 0) >= 58
                if stage == "videos"
                else scene.get("audio_id") or not scene["narration"].strip()
            )
        )
        if ready:
            skipped.append(scene["id"])
            continue
        progress = 10 + round(80 * index / len(project["scenes"]))
        if stage == "videos":
            if not scene.get("first_frame_id"):
                results.append(
                    await generate_scene(
                        project_id, scene["id"], "image", job_id, progress
                    )
                )
            results.append(
                await generate_scene(
                    project_id, scene["id"], "video", job_id, progress + 4
                )
            )
        else:
            results.append(
                await generate_scene(
                    project_id,
                    scene["id"],
                    "image" if stage == "images" else "voice",
                    job_id,
                    progress,
                )
            )
    return {"stage": stage, "generated": results, "reused_scene_ids": skipped}


async def collect_scene_video(project_id, scene_id, job_id, progress=20, threshold=58):
    """Find, download and bind the best licensed video for one narration scene."""
    project = projects.get(project_id)
    scene = scene_by_id(project, scene_id)
    if project["kind"] != "narration":
        raise ValueError("自动素材搜集目前只用于口播作品")
    if scene.get("video_id"):
        return {"reused": True, "asset_id": scene["video_id"]}
    query = (scene.get("material_query") or scene.get("description") or "").strip()
    if len(query) < 2:
        raise ValueError(f"片段「{scene['title']}」缺少可用的素材搜索词")
    jobs.event(job_id, "materials", f"{scene['title']} · 多站点检索视频", progress)
    candidates = await search_videos(query)
    require_running(job_id)
    suitable = [candidate for candidate in candidates if candidate["score"] >= threshold]
    errors = []
    for candidate in suitable[:4]:
        try:
            value = await collect(
                candidate["url"],
                candidate["name"] or f"{scene['title']} · 搜集视频",
                candidate.get("license") or "请查看来源页确认授权",
                provider=candidate.get("provider"),
                page_url=candidate.get("page_url"),
                license_url=candidate.get("license_url"),
                description=candidate.get("description"),
                artist=candidate.get("artist"),
                search_query=query,
                match_score=candidate["score"],
                match_reason=candidate.get("match_reason"),
            )
            require_running(job_id)
            if value["kind"] != "video":
                raise ValueError("候选链接没有返回视频")
            reason = (
                f"{candidate.get('provider', '公开素材')} 视频与本段检索词匹配；"
                f"{candidate.get('match_reason', '')}。来源和许可已保存。"
            )
            update_scene(
                project_id,
                scene_id,
                video_id=value["id"],
                first_frame_id=None,
                material_query=query,
                match_reason=reason,
                match_score=candidate["score"],
                status="video_ready",
            )
            return {
                "asset_id": value["id"],
                "provider": candidate.get("provider"),
                "score": candidate["score"],
                "query": query,
            }
        except Exception as error:
            errors.append(str(error))
    return {
        "asset_id": None,
        "query": query,
        "best_score": candidates[0]["score"] if candidates else 0,
        "reason": "没有达到匹配阈值的可下载视频，进入 AI 视频补画",
        "errors": errors[:3],
    }


async def collect_materials(project_id, job_id):
    project = projects.get(project_id)
    if project["kind"] != "narration" or not project["scenes"]:
        raise ValueError("请先完成口播画面拆分")
    results = []
    for index, scene in enumerate(project["scenes"]):
        require_running(job_id)
        results.append(
            await collect_scene_video(
                project_id,
                scene["id"],
                job_id,
                8 + round(82 * index / max(1, len(project["scenes"]))),
            )
        )
    return {
        "stage": "materials",
        "matched": sum(bool(result.get("asset_id")) for result in results),
        "fallback": sum(not result.get("asset_id") for result in results),
        "results": results,
    }


async def produce(project_id, job_id):
    project = projects.get(project_id)
    if not project["scenes"]:
        raise ValueError("请先保存完整分镜")
    ids = [s["id"] for s in project["scenes"]]
    if project["kind"] == "narration":
        await collect_materials(project_id, job_id)
    for index, ident in enumerate(ids):
        progress = 15 + round(65 * index / len(ids))
        scene = scene_by_id(projects.get(project_id), ident)
        if not scene.get("first_frame_id") and not scene.get("video_id"):
            await generate_scene(project_id, ident, "image", job_id, progress)
        scene = scene_by_id(projects.get(project_id), ident)
        if not scene.get("video_id"):
            await generate_scene(project_id, ident, "video", job_id, progress + 8)
        scene = scene_by_id(projects.get(project_id), ident)
        if scene["narration"].strip() and not scene.get("audio_id"):
            await generate_scene(project_id, ident, "voice", job_id, progress + 12)
    return await export(project_id, job_id)
