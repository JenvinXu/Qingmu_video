from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator
from .timing import MIN_DRAMA_SCENE_SECONDS, MAX_DRAMA_SCENE_SECONDS


class Settings(BaseModel):
    base_url: str = "https://api.agnes-ai.cn/v1"
    text_model: str = "agnes-2.5-flash"
    llm_provider: Literal["media", "qianfan", "custom"] = "media"
    llm_base_url: str = "https://qianfan.baidubce.com/v2"
    llm_api_key: str = ""
    vision_model: str = "kimi-k2.6"
    image_model: str = "agnes-image-2.5-flash"
    video_model: str = "agnes-video-2.5-flash"
    voice_provider: Literal["edge", "openai"] = "edge"
    voice_model: str = "tts-1"
    voice: str = "zh-CN-XiaoxiaoNeural"
    video_seconds: int = Field(default=5, ge=MIN_DRAMA_SCENE_SECONDS, le=MAX_DRAMA_SCENE_SECONDS)
    video_size: str = "720P"
    api_key: str = ""
    video_api_key: str = ""


class Scene(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=6000)
    dialogue: str = Field(default="", max_length=3000)
    speaker_id: str | None = Field(default=None, max_length=80)
    dialogue_start: float | None = Field(default=None, ge=0, le=120)
    dialogue_end: float | None = Field(default=None, ge=0, le=120)
    narration: str = Field(default="", max_length=3000)
    voice: str = Field(default="", max_length=160)
    image_prompt: str = Field(default="", max_length=6000)
    video_prompt: str = Field(default="", max_length=6000)
    image_model: str = Field(default="", max_length=200)
    video_model: str = Field(default="", max_length=200)
    aspect: Literal["9:16", "16:9", "1:1"] | None = None
    video_seconds: int | None = Field(
        default=None,
        ge=MIN_DRAMA_SCENE_SECONDS,
        le=MAX_DRAMA_SCENE_SECONDS,
    )
    video_size: Literal["720P", "1080P", "1K", "2K"] | None = None
    material_query: str = Field(default="", max_length=500)
    match_reason: str = Field(default="", max_length=2000)
    match_score: int | None = Field(default=None, ge=0, le=100)
    duration: float = Field(default=5, ge=0.5, le=120)
    trim_in: float = Field(default=0, ge=0, le=3600)
    asset_ids: list[str] = Field(default_factory=list, max_length=36)
    reference_ids: list[str] = Field(default_factory=list, max_length=36)
    first_frame_id: str | None = None
    video_id: str | None = None
    audio_id: str | None = None
    sfx_id: str | None = None
    sfx_volume: float = Field(default=0.35, ge=0, le=2)
    sfx_offset: float = Field(default=0, ge=0, le=120)
    status: str = "draft"


class Storyboard(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    synopsis: str = Field(min_length=1, max_length=12000)
    script: str = Field(default="", max_length=30000)
    scenes: list[Scene] = Field(min_length=1, max_length=40)


class CreateProject(BaseModel):
    kind: Literal["narration", "drama"]
    title: str = Field(default="未命名作品", min_length=1, max_length=120)
    prompt: str = Field(default="", max_length=16000)
    aspect: Literal["9:16", "16:9", "1:1"] = "9:16"
    target_duration: int = Field(default=30, ge=5, le=300)
    shot_duration: int = Field(
        default=6,
        ge=MIN_DRAMA_SCENE_SECONDS,
        le=MAX_DRAMA_SCENE_SECONDS,
    )
    scene_count: int | None = Field(default=None, ge=1, le=40)
    video_size: Literal["720P", "1080P", "1K", "2K"] = "720P"
    subtitles: bool = True
    voice: str = "zh-CN-XiaoxiaoNeural"
    asset_ids: list[str] = Field(default_factory=list, max_length=80)


class ProjectPatch(BaseModel):
    revision: int
    title: str | None = Field(default=None, max_length=120)
    prompt: str | None = Field(default=None, max_length=16000)
    aspect: Literal["9:16", "16:9", "1:1"] | None = None
    target_duration: int | None = Field(default=None, ge=5, le=300)
    shot_duration: int | None = Field(
        default=None,
        ge=MIN_DRAMA_SCENE_SECONDS,
        le=MAX_DRAMA_SCENE_SECONDS,
    )
    scene_count: int | None = Field(default=None, ge=1, le=40)
    video_size: Literal["720P", "1080P", "1K", "2K"] | None = None
    script: str | None = Field(default=None, max_length=30000)
    synopsis: str | None = Field(default=None, max_length=12000)
    asset_ids: list[str] | None = Field(default=None, max_length=80)
    scenes: list[Scene] | None = Field(default=None, max_length=40)
    subtitles: bool | None = None
    voice: str | None = None
    bgm_id: str | None = None
    bgm_volume: float | None = Field(default=None, ge=0, le=1)
    bgm_ducking: bool | None = None


class RunRequest(BaseModel):
    action: Literal[
        "idea",
        "storyboard",
        "plan",
        "auto",
        "image",
        "storyboard_image",
        "video",
        "voice",
        "images",
        "videos",
        "voices",
        "materials",
        "export",
    ]
    scene_id: str | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=12000)


class PromptPatch(BaseModel):
    revision: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=20000)


class AssetMeta(BaseModel):
    kind: Literal["character", "prop", "image", "video", "voice", "music", "document"]
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=3000)
    voice: str = ""
    voice_asset_id: str | None = None
    voice_description: str = Field(default="", max_length=3000)


class CharacterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    photo_asset_id: str | None = None
    voice_asset_id: str | None = None
    description: str = Field(default="", max_length=3000)
    voice_description: str = Field(default="", max_length=3000)
    image_prompt: str = Field(default="", max_length=6000)
    image_model: str = ""

    @field_validator("name")
    @classmethod
    def required_name(cls, value):
        if not value.strip():
            raise ValueError("请填写角色名称")
        return value.strip()


class CollectRequest(BaseModel):
    url: str = Field(max_length=2000)
    name: str = Field(default="网络素材", max_length=200)
    license: str = Field(default="用户提供，使用前确认授权", max_length=500)
    provider: str = Field(default="", max_length=80)
    page_url: str = Field(default="", max_length=2000)
    license_url: str = Field(default="", max_length=2000)
    description: str = Field(default="", max_length=4000)
    search_query: str = Field(default="", max_length=500)
    match_score: int | None = Field(default=None, ge=0, le=100)
    match_reason: str = Field(default="", max_length=2000)
    artist: str = Field(default="", max_length=500)
