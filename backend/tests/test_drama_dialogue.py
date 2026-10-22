import pytest

from studio.core.paths import new_media_path
from studio.core.store import store
from studio.domain import projects
from studio.domain.models import CharacterCreate, CreateProject, Storyboard
from studio.domain.dialogue import dialogue_window
from studio.library.characters import create_character
from studio.media.editor import ass_time, subtitles
from studio.providers.agnes import Agnes
from studio.workflows import production


def running_job(project_id: str, action: str):
    return store.save(
        "job", {"status": "running", "action": action, "project_id": project_id}
    )


def video_asset():
    relative, path = new_media_path(".mp4")
    path.write_bytes(b"video-fixture")
    return store.save(
        "asset",
        {
            "kind": "video",
            "name": "自然对白视频",
            "path": relative,
            "info": {
                "duration": 5,
                "streams": [{"codec_type": "video"}, {"codec_type": "audio"}],
            },
        },
    )


def dialogue_project():
    character = create_character(CharacterCreate(name="林岚"))
    project = projects.create(
        CreateProject(kind="drama", asset_ids=[character["id"]])
    )
    project = projects.save_storyboard(
        project["id"],
        Storyboard(
            title="雨夜车站",
            synopsis="人物通过对话解决冲突",
            scenes=[
                {
                    "id": "one",
                    "title": "拒绝离开",
                    "description": "林岚看着周野说出决定。",
                    "dialogue": "我不走，这盏灯必须亮起来。",
                    "speaker_id": character["id"],
                    "narration": "",
                    "video_prompt": "林岚抬眼，自然说出决定，周野沉默。",
                    "duration": 5,
                    "video_seconds": 5,
                    "asset_ids": [character["id"]],
                }
            ],
        ),
    )
    return project, character


def test_drama_dialogue_requires_speaker_and_is_separate_from_narration():
    project, character = dialogue_project()
    scene = project["scenes"][0]
    assert scene["dialogue"] and not scene["narration"]
    assert scene["speaker_id"] == scene["asset_ids"][0] == character["id"]
    assert 0 < scene["dialogue_start"] < scene["dialogue_end"] < scene["duration"]

    invalid = Storyboard(
        title="错误分镜",
        synopsis="错误",
        scenes=[
            {
                **scene,
                "dialogue": "人物台词",
                "narration": "同时出现的旁白",
            }
        ],
    )
    with pytest.raises(ValueError, match="不能同时"):
        projects.save_storyboard(project["id"], invalid)


def test_legacy_drama_tts_dialogue_is_migrated_without_deleting_video():
    character = create_character(CharacterCreate(name="周野"))
    project = projects.create(
        CreateProject(kind="drama", asset_ids=[character["id"]])
    )
    previous_revision = project["revision"]
    project.update(
        export_id="旧旁白成片",
        export_revision=previous_revision,
        scenes=[
            {
                "id": "legacy",
                "title": "解释真相",
                "description": "周野解释真相。",
                "narration": "我不是来偷。",
                "video_prompt": "周野压低声音说台词：我不是来偷。",
                "duration": 5,
                "asset_ids": [character["id"]],
                "video_id": "existing-video",
                "audio_id": "old-tts",
            }
        ],
    )
    store.save("project", project)

    migrated = projects.get(project["id"])
    scene = migrated["scenes"][0]
    assert scene["dialogue"] == "我不是来偷。"
    assert scene["speaker_id"] == character["id"]
    assert scene["narration"] == "" and scene["audio_id"] is None
    assert 0 < scene["dialogue_start"] < scene["dialogue_end"] < scene["duration"]
    assert scene["video_id"] == "existing-video"
    assert migrated["export_id"] is None
    assert migrated["revision"] == previous_revision + 1


@pytest.mark.asyncio
async def test_dialogue_is_sent_to_video_and_never_to_narration_tts(monkeypatch):
    project, _character = dialogue_project()
    generated = video_asset()
    prompts = []

    async def fake_video(self, prompt, *args, **kwargs):
        prompts.append(prompt)
        return generated

    async def forbidden_tts(*_args, **_kwargs):
        pytest.fail("人物自然对白不应调用旁白 TTS")

    monkeypatch.setattr(Agnes, "video", fake_video)
    monkeypatch.setattr(production, "synthesize", forbidden_tts)
    video_job = running_job(project["id"], "video")
    await production.generate_scene(project["id"], "one", "video", video_job["id"])
    assert "视频原声对白：在镜头第" in prompts[0]
    assert "秒期间，林岚用自然中文说" in prompts[0]
    assert "口型、呼吸、语气、表情和对方反应同步" in prompts[0]

    voice_job = running_job(project["id"], "voice")
    result = await production.generate_scene(
        project["id"], "one", "voice", voice_job["id"]
    )
    assert result == {"skipped": True, "reason": "该镜头未安排旁白"}


def test_natural_dialogue_creates_subtitles_without_external_audio():
    scene = {
        "dialogue": "我不走，这盏灯必须亮起来。",
        "narration": "",
        "duration": 5,
    }
    start, end = dialogue_window(scene)
    script = subtitles(
        scene,
        None,
        5,
        1280,
        720,
    )
    assert "这盏灯必须亮起来" in script
    assert start > 0 and f"Dialogue: 0,{ass_time(start)}," in script
    assert ass_time(end) in script


def test_explicit_dialogue_timing_controls_burned_subtitle_window():
    scene = {
        "dialogue": "现在开始说话。",
        "narration": "",
        "duration": 6,
        "dialogue_start": 2.2,
        "dialogue_end": 4.1,
    }
    script = subtitles(scene, None, 6, 1280, 720)
    assert "Dialogue: 0,0:00:02.20,0:00:04.10" in script
