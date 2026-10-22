"""Extract the last displayed frame of the preceding edited scene, with reuse."""

from __future__ import annotations
import hashlib
import json
from ..core.paths import new_media_path, media_path
from ..core.store import store
from ..library.service import asset, register
from .process import executable, run_process


async def previous_tail(project, scene_id):
    index = next(
        (i for i, s in enumerate(project["scenes"]) if s["id"] == scene_id), -1
    )
    if index < 1:
        raise ValueError("当前分镜没有上一分镜")
    previous = project["scenes"][index - 1]
    if not previous.get("video_id"):
        raise ValueError("上一分镜尚未生成视频")
    video = asset(previous["video_id"])
    end = min(
        video["info"]["duration"], previous.get("trim_in", 0) + previous["duration"]
    )
    signature = hashlib.sha256(
        json.dumps([video["id"], end], sort_keys=True).encode()
    ).hexdigest()
    cached = next(
        (a for a in store.list("asset", 1000) if a.get("tail_signature") == signature),
        None,
    )
    if cached:
        return asset(cached["id"])
    relative, path = new_media_path(".jpg")
    start = max(0, end - 0.25)
    try:
        await run_process(
            [
                executable("ffmpeg"),
                "-y",
                "-v",
                "error",
                "-ss",
                str(start),
                "-i",
                str(media_path(video["path"])),
                "-vf",
                f"trim=duration={end - start},reverse,setpts=PTS-STARTPTS",
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(path),
            ],
            60,
        )
        return await register(
            relative,
            previous["title"] + " · 尾帧",
            "image",
            source="extracted",
            license=video.get("license", "用户素材"),
            project_id=project["id"],
            source_asset_id=video["id"],
            tail_signature=signature,
        )
    except BaseException:
        path.unlink(missing_ok=True)
        raise
