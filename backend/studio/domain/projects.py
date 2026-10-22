from __future__ import annotations
import time
from ..core.store import store
from ..library.service import asset
from ..library.references import resolve_references
from .models import CreateProject, ProjectPatch, Storyboard, Scene
from .script_format import drama_segments
from .timing import planned_durations, synchronize
from .dialogue import normalize_dialogue_timing


def create(value: CreateProject):
    for ident in value.asset_ids:
        asset(ident)
    data = value.model_dump()
    if value.kind == "narration" and value.scene_count is None:
        data["scene_count"] = 3
    return store.save(
        "project",
        {
            **data,
            "revision": 1,
            "created_at": time.time(),
            "synopsis": "",
            "script": "",
            "scenes": [],
            "export_id": None,
            "export_revision": None,
            "status": "draft",
            "bgm_id": None,
            "bgm_volume": 0.12,
            "bgm_ducking": True,
            "pending_videos": {},
        },
    )


def _normalized_scenes(project: dict):
    scenes, migrated = [], False
    dialogue_cues = (
        "说台词",
        "说出",
        "说道",
        "低声说",
        "轻声说",
        "厉声说",
        "开口说",
        "台词：",
    )
    for raw in project.get("scenes", []):
        scene = Scene.model_validate(raw).model_dump()
        legacy_text = raw.get("narration", "").strip()
        video_prompt = raw.get("video_prompt", "")
        first_asset = scene.get("asset_ids", [None])[0] if scene.get("asset_ids") else None
        speaker = None
        if first_asset:
            try:
                speaker = asset(first_asset)
            except KeyError:
                pass
        if (
            project.get("kind") == "drama"
            and "dialogue" not in raw
            and legacy_text
            and legacy_text in video_prompt
            and any(cue in video_prompt for cue in dialogue_cues)
            and speaker
            and speaker["kind"] == "character"
        ):
            scene.update(
                dialogue=legacy_text,
                speaker_id=first_asset,
                narration="",
                audio_id=None,
                status="video_ready" if scene.get("video_id") else scene["status"],
            )
            migrated = True
        scene, timing_changed = normalize_dialogue_timing(scene)
        migrated = migrated or timing_changed
        scenes.append(scene)
    return scenes, migrated


def get(ident):
    project = store.get("project", ident)
    scenes, migrated = _normalized_scenes(project)
    if migrated:
        previous = project["revision"]
        project = {
            **project,
            "scenes": scenes,
            "revision": previous + 1,
            "export_id": None,
            "export_revision": None,
            "status": "storyboard",
        }
        store.save("project", project, revision=previous)
    return {**project, "scenes": scenes}


def validate_scene_ids(scenes, *, pool=None):
    ids = [s["id"] for s in scenes]
    if len(set(ids)) != len(ids):
        raise ValueError("镜头 ID 不能重复")
    for scene in scenes:
        if scene.get("dialogue", "").strip() and scene.get("narration", "").strip():
            raise ValueError("同一分镜不能同时安排人物对白和旁白，请拆到相邻分镜")
        if scene.get("dialogue", "").strip():
            start, end = scene.get("dialogue_start"), scene.get("dialogue_end")
            if start is None or end is None or not (0 <= start < end <= scene["duration"]):
                raise ValueError("人物对白字幕时间必须位于本分镜时长内，且结束时间晚于开始时间")
        for ident in [*scene.get("asset_ids", []), *scene.get("reference_ids", [])]:
            value = asset(ident)
            if (
                pool is not None
                and value["kind"] in {"character", "prop"}
                and ident not in pool
            ):
                raise ValueError("分镜角色和物品必须来自本作品配置的资产")
        speaker_id = scene.get("speaker_id")
        if speaker_id:
            speaker = asset(speaker_id)
            if speaker["kind"] != "character":
                raise ValueError("说话角色必须选择角色资产")
            if pool is not None and speaker_id not in pool:
                raise ValueError("说话角色必须来自本作品配置的角色")
            if not scene.get("asset_ids") or scene["asset_ids"][0] != speaker_id:
                raise ValueError("说话角色必须排在本分镜角色资产第一项")
        if pool is not None and scene.get("dialogue", "").strip():
            configured_characters = [
                ident for ident in pool if asset(ident)["kind"] == "character"
            ]
            if configured_characters and not speaker_id:
                raise ValueError("人物对白需要选择说话角色")
        resolve_references(scene, allow_documents=pool is None)
        for field, allowed in (
            ("first_frame_id", {"image", "character", "prop"}),
            ("video_id", {"video"}),
            ("audio_id", {"voice", "music"}),
            ("sfx_id", {"voice", "music"}),
        ):
            if scene.get(field) and asset(scene[field])["kind"] not in allowed:
                raise ValueError("绑定素材类型不匹配：" + field)
        if scene.get("first_frame_id") and not asset(scene["first_frame_id"])[
            "mime"
        ].startswith("image/"):
            raise ValueError("首帧参考必须为真实图片")


def commit(project, **changes):
    previous = project["revision"]
    project = {**project, **changes, "revision": previous + 1}
    project["export_id"] = None
    project["export_revision"] = None
    return store.save("project", project, revision=previous)


def patch(ident, value: ProjectPatch):
    project = get(ident)
    if value.revision != project["revision"]:
        from ..core.store import Conflict

        raise Conflict("作品已更新，请刷新后重试")
    changes = value.model_dump(exclude_unset=True, exclude={"revision"})
    for asset_id in changes.get("asset_ids") or []:
        asset(asset_id)
    if "asset_ids" in changes and changes["asset_ids"] is None:
        raise ValueError("资产配置不能为 null")
    if (
        project["kind"] == "drama"
        and "asset_ids" in changes
        and "scenes" not in changes
    ):
        pool = set(changes["asset_ids"])
        existing = project["scenes"]
        changes["scenes"] = []
        for original in existing:
            scene = Scene.model_validate(original).model_dump()
            for field in ("asset_ids", "reference_ids"):
                scene[field] = [
                    a
                    for a in scene[field]
                    if asset(a)["kind"] not in {"character", "prop"} or a in pool
                ]
            changes["scenes"].append(scene)
    if changes.get("bgm_id") and asset(changes["bgm_id"])["kind"] not in {
        "music",
        "voice",
    }:
        raise ValueError("配乐需要音频素材")
    if "scenes" in changes:
        if changes["scenes"] is None:
            raise ValueError("分镜列表不能为 null")
        # exclude_unset on ProjectPatch also strips nested defaults. Normalize both
        # sides so legacy scenes do not lose media merely by acquiring new fields.
        changes["scenes"] = [
            normalize_dialogue_timing(Scene.model_validate(scene).model_dump())[0]
            for scene in changes["scenes"]
        ]
        if project["kind"] == "drama":
            synchronize(changes["scenes"], project["scenes"])
            changes["scenes"] = [
                normalize_dialogue_timing(scene)[0] for scene in changes["scenes"]
            ]
        validate_scene_ids(
            changes["scenes"],
            pool=(
                changes.get("asset_ids", project.get("asset_ids", []))
                if project["kind"] == "drama"
                else None
            ),
        )
        old = {s["id"]: Scene.model_validate(s).model_dump() for s in project["scenes"]}
        for scene in changes["scenes"]:
            previous = old.get(scene["id"], {})
            if any(
                scene.get(k) != previous.get(k)
                for k in (
                    "image_prompt",
                    "description",
                    "asset_ids",
                    "image_model",
                    "aspect",
                )
            ):
                # A new image input invalidates the generated frame. The selected
                # video is a durable edit decision and stays bound until the user
                # explicitly replaces it or a new video finishes generating.
                if scene.get("first_frame_id") == previous.get("first_frame_id"):
                    scene["first_frame_id"] = None
                project["pending_videos"].pop(scene["id"], None)
            elif any(
                scene.get(k) != previous.get(k)
                for k in (
                    "dialogue",
                    "speaker_id",
                    "dialogue_start",
                    "dialogue_end",
                    "video_prompt",
                    "video_model",
                    "video_size",
                    "first_frame_id",
                    "reference_ids",
                )
            ):
                # Configuration changes affect the next generation only. Keep the
                # current clip visible on the preview and timeline in the meantime.
                project["pending_videos"].pop(scene["id"], None)
            if scene.get("video_seconds") != previous.get("video_seconds"):
                project["pending_videos"].pop(scene["id"], None)
            if any(
                scene.get(key) != previous.get(key) for key in ("narration", "voice")
            ) and scene.get("audio_id") == previous.get("audio_id"):
                scene["audio_id"] = None
        changes["status"] = "storyboard"
    if project["kind"] == "drama" and "script" in changes:
        segments = drama_segments(changes["script"] or "")
        changes["scene_count"] = len(segments) or None
    if changes.get("voice") != project.get("voice") and "voice" in changes:
        changes.setdefault("scenes", project["scenes"])
        for scene in changes["scenes"]:
            if not scene.get("voice"):
                scene["audio_id"] = None
    if (
        project["kind"] == "narration"
        and "scene_count" in changes
        and changes["scene_count"] is None
    ):
        raise ValueError("口播片段数量不能为空")
    return commit(project, **changes)


def save_script(ident: str, script: str, synopsis: str = ""):
    if not script.strip() or len(script) > 30000 or len(synopsis) > 12000:
        raise ValueError("文案需要 1–30000 个字符")
    project = get(ident)
    changes = {"script": script, "synopsis": synopsis}
    if project["kind"] == "drama":
        segments = drama_segments(script, required=True)
        require_generated_timing(project, segments)
        changes["scene_count"] = len(segments)
    return commit(project, **changes)


def save_storyboard(ident: str, value: Storyboard):
    scenes = [normalize_dialogue_timing(s.model_dump())[0] for s in value.scenes]
    project = get(ident)
    if project["kind"] == "drama":
        synchronize(scenes)
        authoritative_script = project.get("script") or value.script
        segments = drama_segments(
            authoritative_script, required=bool(authoritative_script)
        )
        # Planning/auto can create script and storyboard in one tool call. When
        # there is no user-authored script yet, apply the same exact timing gate
        # used by the dedicated idea step.
        if segments and not project.get("script"):
            require_generated_timing(project, segments)
        if segments:
            if len(scenes) != len(segments):
                raise ValueError("分镜数量必须与视频文案中的分镜标记一致")
            for scene, segment in zip(scenes, segments, strict=True):
                if scene["description"].strip() != segment["text"]:
                    raise ValueError(
                        f"分镜 {segment['number']} 的本分镜文案必须原样复制视频文案"
                    )
                if scene["duration"] != segment["duration"]:
                    raise ValueError(
                        f"分镜 {segment['number']} 的时长必须使用文案中的时间段"
                    )
    validate_scene_ids(
        scenes,
        pool=project.get("asset_ids", []) if project["kind"] == "drama" else None,
    )
    if (
        project["kind"] == "drama"
        and project.get("scene_count")
        and len(scenes) != project["scene_count"]
    ):
        raise ValueError("分镜数量必须符合用户填写的数量")
    if project["kind"] == "narration" and not all(
        s["narration"].strip() for s in scenes
    ):
        raise ValueError("口播的每个镜头需要旁白")
    return commit(
        project,
        **value.model_dump(exclude={"scenes", "script", "synopsis"}),
        synopsis=project.get("synopsis") or value.synopsis,
        script=(authoritative_script if project["kind"] == "drama" else value.script),
        scenes=scenes,
        scene_count=len(scenes),
        status="storyboard",
        pending_videos={},
    )


def require_generated_timing(project: dict, segments: list[dict]) -> None:
    expected = planned_durations(
        project["target_duration"], project.get("shot_duration") or 6
    )
    actual = [segment["duration"] for segment in segments]
    if actual != expected:
        expected_text = "、".join(str(value) for value in expected)
        actual_text = "、".join(str(value) for value in actual)
        raise ValueError(
            f"当前设置要求 {len(expected)} 个分镜，时长依次为 {expected_text} 秒；"
            f"不能保存 {len(actual)} 个分镜（{actual_text} 秒），请按设置重新生成"
        )
