import pytest
from studio.core.paths import new_media_path
from studio.core.store import store
from studio.domain import projects
from studio.domain.models import CreateProject, ProjectPatch, Storyboard
from studio.workflows import production
from studio.agent import client as agent_client


def fixture_asset(kind):
    relative, path = new_media_path(".png" if kind == "image" else ".mp3")
    path.write_bytes(b"domain-fixture")
    return store.save(
        "asset", {"kind": kind, "name": kind, "path": relative, "info": {"duration": 8}}
    )


def project_with_scenes(scenes):
    project = projects.create(CreateProject(kind="narration", scene_count=len(scenes)))
    return projects.save_storyboard(
        project["id"],
        Storyboard(
            title="口播",
            synopsis="test",
            script="午后的光。给自己片刻安静。",
            scenes=scenes,
        ),
    )


def job_for(project, action):
    return store.save(
        "job", {"status": "running", "action": action, "project_id": project["id"]}
    )


def test_narration_match_evidence_and_sound_effect_persist():
    image, effect = fixture_asset("image"), fixture_asset("voice")
    project = project_with_scenes(
        [
            {
                "id": "matched",
                "title": "一",
                "description": "晨光下打开窗户",
                "narration": "午后的光。给自己片刻安静。",
                "material_query": "sunlight open window calm room",
                "match_reason": "画面包含文案中的阳光、窗户和安静室内",
                "match_score": 94,
                "first_frame_id": image["id"],
                "sfx_id": effect["id"],
                "sfx_volume": 0.3,
                "sfx_offset": 0.5,
            }
        ]
    )
    scene = project["scenes"][0]
    assert scene["material_query"] == "sunlight open window calm room"
    assert scene["match_score"] == 94
    assert scene["sfx_id"] == effect["id"] and scene["sfx_offset"] == 0.5


@pytest.mark.asyncio
async def test_batch_stages_only_fill_missing_media_and_respect_cancellation(
    monkeypatch,
):
    image, audio = fixture_asset("image"), fixture_asset("voice")
    project = project_with_scenes(
        [
            {
                "id": "ready",
                "title": "一",
                "description": "光",
                "narration": "午后的光。",
                "first_frame_id": image["id"],
                "audio_id": audio["id"],
            },
            {
                "id": "missing",
                "title": "二",
                "description": "窗边",
                "narration": "给自己片刻安静。",
            },
        ]
    )
    calls = []

    async def generate(project_id, scene_id, action, job_id, progress):
        calls.append((scene_id, action))
        return {"asset_id": action}

    monkeypatch.setattr(production, "generate_scene", generate)
    for stage, action in [("images", "image"), ("voices", "voice")]:
        job = job_for(project, stage)
        result = await production.generate_stage(project["id"], job["id"], stage)
        assert result["reused_scene_ids"] == ["ready"]
        assert calls[-1] == ("missing", action)
        assert len(result["generated"]) == 1
    assert calls == [("missing", "image"), ("missing", "voice")]
    cancelled = store.save(
        "job", {"status": "cancelled", "action": "images", "project_id": project["id"]}
    )
    with pytest.raises(ValueError, match="取消"):
        await production.generate_stage(project["id"], cancelled["id"], "images")
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_per_clip_voice_reaches_tts_and_global_edits_preserve_overrides(
    monkeypatch,
):
    image, audio = fixture_asset("image"), fixture_asset("voice")
    project = project_with_scenes(
        [
            {
                "id": "one",
                "title": "一",
                "description": "光",
                "narration": "午后的光。",
                "voice": "zh-CN-YunxiNeural",
                "first_frame_id": image["id"],
            },
            {
                "id": "two",
                "title": "二",
                "description": "窗边",
                "narration": "给自己片刻安静。",
                "audio_id": audio["id"],
            },
        ]
    )
    calls = []

    async def synthesize(text, voice, name):
        calls.append((text, voice))
        return audio

    monkeypatch.setattr(production, "synthesize", synthesize)
    job = job_for(project, "voice")
    await production.generate_scene(project["id"], "one", "voice", job["id"])
    changed = projects.get(project["id"])
    assert calls == [("午后的光。", "zh-CN-YunxiNeural")]
    assert changed["scenes"][0]["duration"] == 8.25
    changed = projects.patch(
        project["id"],
        ProjectPatch(revision=changed["revision"], voice="zh-CN-XiaoyiNeural"),
    )
    assert changed["scenes"][0]["audio_id"] == audio["id"]
    assert changed["scenes"][1]["audio_id"] is None
    scenes = changed["scenes"]
    scenes[0]["voice"] = "zh-CN-XiaoxiaoNeural"
    changed = projects.patch(
        project["id"], ProjectPatch(revision=changed["revision"], scenes=scenes)
    )
    assert changed["scenes"][0]["audio_id"] is None
    assert changed["scenes"][0]["first_frame_id"] == image["id"]


@pytest.mark.asyncio
async def test_narration_voice_shrinks_authored_scene_to_remove_dead_air(monkeypatch):
    audio = fixture_asset("voice")
    audio["info"]["duration"] = 3.5
    store.save("asset", audio)
    project = project_with_scenes(
        [
            {
                "id": "one",
                "title": "一",
                "description": "一句短旁白",
                "narration": "一句短旁白。",
                "duration": 10,
            }
        ]
    )

    async def synthesize(*_args):
        return audio

    monkeypatch.setattr(production, "synthesize", synthesize)
    job = job_for(project, "voice")
    await production.generate_scene(project["id"], "one", "voice", job["id"])

    changed = projects.get(project["id"])
    assert changed["scenes"][0]["duration"] == 3.75


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_text", [False, True])
async def test_narration_partition_validates_the_original_read_aloud_text(
    monkeypatch, wrong_text
):
    project = projects.create(CreateProject(kind="narration", scene_count=2))
    project = projects.save_script(project["id"], "午后的光。给自己片刻安静。")
    job = job_for(project, "storyboard")

    class Response:
        is_error = False

        def json(self):
            return {"message": "saved"}

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, headers, json):
            assert (
                "口播" in json["message"]
                and "不制作媒体" in json["message"]
                and "逐字" in json["message"]
            )
            projects.save_storyboard(
                project["id"],
                Storyboard(
                    title="口播",
                    synopsis="test",
                    script="model paraphrase",
                    scenes=[
                        {
                            "id": "one",
                            "title": "一",
                            "description": "光",
                            "narration": "午后的光。",
                        },
                        {
                            "id": "two",
                            "title": "二",
                            "description": "窗边",
                            "narration": "给自己片刻安静。"
                            if not wrong_text
                            else "被改写的口播。",
                        },
                    ],
                ),
            )
            return Response()

    monkeypatch.setattr(agent_client.httpx, "AsyncClient", Client)
    if wrong_text:
        with pytest.raises(ValueError, match="完整保留原文"):
            await agent_client.agent_run(project["id"], job["id"], "", "storyboard")
    else:
        await agent_client.agent_run(project["id"], job["id"], "", "storyboard")
    assert projects.get(project["id"])["script"] == project["script"]
