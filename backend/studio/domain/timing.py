"""One planned duration for a drama scene, generation request and timeline."""

from __future__ import annotations
import math

MIN_DRAMA_SCENE_SECONDS = 1
MAX_DRAMA_SCENE_SECONDS = 30
MAX_STORYBOARD_SCENES = 40


def planned_durations(target_duration: int, shot_duration: int) -> list[int]:
    """Return the exact integer shot plan, with only the final shot allowed shorter."""

    if target_duration < 1 or not MIN_DRAMA_SCENE_SECONDS <= shot_duration <= MAX_DRAMA_SCENE_SECONDS:
        raise ValueError("分镜时长配置无效")
    full, remainder = divmod(target_duration, shot_duration)
    values = [shot_duration] * full + ([remainder] if remainder else [])
    if len(values) > MAX_STORYBOARD_SCENES:
        raise ValueError(
            f"当前设置会产生 {len(values)} 个分镜，最多支持 {MAX_STORYBOARD_SCENES} 个；请增加分镜时长"
        )
    return values


def synchronize(scenes, previous=()):
    lookup = {scene["id"]: scene for scene in previous}
    for scene in scenes:
        old = lookup.get(scene["id"])
        value = scene["duration"]
        if (
            old
            and value == old["duration"]
            and scene.get("video_seconds") is not None
            and scene.get("video_seconds") != old.get("video_seconds")
        ):
            value = scene["video_seconds"]
        scene["duration"] = min(
            MAX_DRAMA_SCENE_SECONDS,
            max(MIN_DRAMA_SCENE_SECONDS, math.ceil(value)),
        )
        scene["video_seconds"] = scene["duration"]
    return scenes
