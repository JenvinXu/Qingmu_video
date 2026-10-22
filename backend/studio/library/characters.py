"""Characters are optional portraits plus optional reusable recorded voices."""

from __future__ import annotations
from ..core.store import store
from ..domain.models import CharacterCreate
from .service import asset


def voice_metadata(voice_asset_id):
    if voice_asset_id and asset(voice_asset_id)["kind"] != "voice":
        raise ValueError("角色声音必须为声音素材")


def create_character(value: CharacterCreate, photo=None):
    if not value.name.strip():
        raise ValueError("请填写角色名称")
    voice_metadata(value.voice_asset_id)
    photo = photo or (asset(value.photo_asset_id) if value.photo_asset_id else None)
    if photo and not photo.get("mime", "").startswith("image/"):
        raise ValueError("角色照片需要图片素材")
    return store.save(
        "asset",
        {
            **(
                {
                    k: v
                    for k, v in photo.items()
                    if k not in {"id", "updated_at", "project_id"}
                }
                if photo
                else {
                    "path": "",
                    "thumbnail": None,
                    "mime": "application/x-studio-character",
                    "size": 0,
                    "info": {},
                    "source": "local",
                    "license": "用户创建",
                }
            ),
            "name": value.name,
            "kind": "character",
            "description": value.description,
            "voice": "",
            "voice_asset_id": value.voice_asset_id,
            "voice_description": value.voice_description,
        },
    )
