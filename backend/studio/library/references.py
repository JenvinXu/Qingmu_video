"""Resolve a scene's library inputs and apply combined media reference limits."""

from __future__ import annotations
from ..library.service import asset


def resolve_references(scene, *, allow_documents=False):
    ids = list(
        dict.fromkeys([*scene.get("asset_ids", []), *scene.get("reference_ids", [])])
    )
    values = [asset(ident) for ident in ids]
    for value in list(values):
        if value["kind"] == "character" and value.get("voice_asset_id"):
            voice = asset(value["voice_asset_id"])
            if voice["kind"] != "voice":
                raise ValueError("角色音色需要上传的声音素材")
            if voice["id"] not in ids:
                values.append(voice)
                ids.append(voice["id"])
    if scene.get("first_frame_id") and scene["first_frame_id"] not in ids:
        values.insert(0, asset(scene["first_frame_id"]))
    images = [a for a in values if a["mime"].startswith("image/")]
    audios = [a for a in values if a["kind"] in {"voice", "music"}]
    videos = [a for a in values if a["kind"] == "video"]
    if len(images) > 30 or len(audios) > 3 or len(videos) > 3:
        raise ValueError(
            "每个分镜最多 30 张图片（含角色、物品、首帧）、3 个音色、3 个视频"
        )
    textual_characters = [
        a for a in values if a["kind"] == "character" and not a.get("path")
    ]
    documents = [a for a in values if allow_documents and a["kind"] == "document"]
    if len(images) + len(audios) + len(videos) + len(textual_characters) + len(
        documents
    ) != len(values):
        raise ValueError("视频参考只支持图片、声音和视频素材")
    return values
