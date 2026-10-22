import pytest
from PIL import Image
from studio.core.paths import new_media_path, media_path
from studio.core.store import store
from studio.domain import projects
from studio.domain.models import (
    CreateProject,
    ProjectPatch,
    RunRequest,
    Storyboard,
    CharacterCreate,
)
from studio.library.characters import create_character
from studio.library.service import register, asset
from studio.media.process import executable, run_process
from studio.media.frames import previous_tail
from studio.providers.agnes import Agnes
from studio.providers import agnes as provider_module
from studio.library.references import resolve_references
from studio.workflows import production
from studio.agent import prompts


def media_fixture(kind="image", public=True):
    extension = {"image": ".png", "prop": ".png", "voice": ".mp3", "video": ".mp4"}[
        kind
    ]
    relative, path = new_media_path(extension)
    path.write_bytes(b"domain-fixture")
    return store.save(
        "asset",
        {
            "kind": kind,
            "name": kind,
            "path": relative,
            "source_url": "https://example.com/" + relative if public else None,
        },
    )


def test_storyboard_image_is_accepted_by_run_contract():
    request = RunRequest(action="storyboard_image", scene_id="one")

    assert request.action == "storyboard_image"
    assert request.scene_id == "one"


def board(ids=(), refs=()):
    return Storyboard(
        title="短剧",
        synopsis="test",
        scenes=[
            {
                "id": "one",
                "title": "窗边",
                "description": "小雨拿起信封。",
                "asset_ids": list(ids),
                "reference_ids": list(refs),
            }
        ],
    )


def test_autonomous_count_fixed_count_and_asset_pool_boundary():
    role = create_character(CharacterCreate(name="小雨"))
    outside = create_character(CharacterCreate(name="库中其他人"))
    project = projects.create(CreateProject(kind="drama"))
    assert project["scene_count"] is None and project["asset_ids"] == []
    project = projects.patch(
        project["id"],
        ProjectPatch(revision=project["revision"], asset_ids=[role["id"]]),
    )
    project = projects.save_storyboard(project["id"], board([role["id"]]))
    assert project["scene_count"] == 1
    for invalid in [board([outside["id"]]), board(refs=[outside["id"]])]:
        with pytest.raises(ValueError, match="资产"):
            projects.save_storyboard(project["id"], invalid)
    project = projects.patch(
        project["id"], ProjectPatch(revision=project["revision"], asset_ids=[])
    )
    assert project["scenes"][0]["asset_ids"] == []
    project = projects.patch(
        project["id"], ProjectPatch(revision=project["revision"], scene_count=2)
    )
    with pytest.raises(ValueError, match="数量"):
        projects.save_storyboard(project["id"], board())


def test_optional_portrait_and_voice_expand_once_and_enforce_combined_limits():
    portrait, voice = media_fixture(), media_fixture("voice")
    role = create_character(
        CharacterCreate(
            name="小雨", photo_asset_id=portrait["id"], voice_asset_id=voice["id"]
        )
    )
    assert asset(role["id"])["path"] == portrait["path"]
    scene = {
        "asset_ids": [role["id"]],
        "reference_ids": [voice["id"], role["id"]],
        "first_frame_id": portrait["id"],
    }
    refs = resolve_references(scene)
    assert [a["id"] for a in refs] == [portrait["id"], role["id"], voice["id"]]
    scene["reference_ids"] = [media_fixture("voice")["id"] for _ in range(3)]
    with pytest.raises(ValueError, match="3 个音色"):
        resolve_references(scene)
    scene = {
        "reference_ids": [media_fixture()["id"] for _ in range(30)],
        "first_frame_id": portrait["id"],
    }
    with pytest.raises(ValueError, match="30 张"):
        resolve_references(scene)
    with pytest.raises(ValueError, match="名称"):
        create_character(CharacterCreate(name=" "))


@pytest.mark.asyncio
async def test_provider_sends_every_supported_reference_and_refuses_unsupported_before_submission(
    monkeypatch,
):
    provider = object.__new__(Agnes)
    provider.base = "https://example.com/v1"
    provider.settings = {"video_model": "agnes-video-2.5", "video_size": "720P"}
    calls = []

    async def request(method, endpoint, body=None, **kwargs):
        calls.append((method, body))
        return (
            {"video_id": "task"}
            if method == "POST"
            else {"status": "completed", "url": "https://example.com/result.mp4"}
        )

    async def download(url, target):
        target.write_bytes(b"result")

    async def register_result(relative, name, kind, **metadata):
        return {"id": "result", "kind": kind, "info": {}, **metadata}

    monkeypatch.setattr(provider, "request", request)
    monkeypatch.setattr(provider_module, "download", download)
    monkeypatch.setattr(provider_module, "register", register_result)
    first = asset(media_fixture()["id"])
    values = [asset(media_fixture()["id"]) for _ in range(7)] + [
        asset(media_fixture("voice")["id"]),
        asset(media_fixture("video")["id"]),
    ]
    result = await provider.video(
        "prompt", "9:16", 4, first, values, "test", lambda _: None
    )
    body = calls[0][1]
    assert body["mode"] == "reference" and len(body["images"]) == 8
    assert (
        "<Picture 1>：首帧构图" in body["prompt"]
        and "<Picture 8>" in body["prompt"]
        and "<Audio 1>" in body["prompt"]
        and "<Video 1>" in body["prompt"]
    )
    assert body["images"] == [
        first["source_url"],
        *[a["source_url"] for a in values if a["mime"].startswith("image/")],
    ]
    assert (
        len(body["audios"]) == 1
        and len(body["videos"]) == 1
        and result["reference_ids"] == [a["id"] for a in values]
    )
    calls.clear()
    for refs in [
        values + [asset(media_fixture()["id"])],
        [asset(media_fixture(public=False)["id"])],
    ]:
        with pytest.raises(ValueError):
            await provider.video(
                "prompt", "9:16", 4, first, refs, "test", lambda _: None
            )
        assert not calls
    provider.settings["video_model"] = "agnes-video-2.5-flash"
    with pytest.raises(ValueError, match="0 个视频"):
        await provider.video(
            "prompt",
            "9:16",
            4,
            None,
            [asset(media_fixture("video")["id"])],
            "test",
            lambda _: None,
        )
    assert not calls


@pytest.mark.asyncio
async def test_flash_transmits_uploaded_character_voice_and_local_first_frame(
    monkeypatch,
):
    from studio.library.service import data_uri

    photo, voice, first = [
        asset(a["id"])
        for a in (
            media_fixture(public=False),
            media_fixture("voice", public=False),
            media_fixture(public=False),
        )
    ]
    role = create_character(
        CharacterCreate(
            name="小雨",
            photo_asset_id=photo["id"],
            voice_asset_id=voice["id"],
        )
    )
    resolved = resolve_references(
        {"asset_ids": [role["id"]], "first_frame_id": first["id"]}
    )
    provider = object.__new__(Agnes)
    provider.base = "https://example.com/v1"
    provider.settings = {"video_model": "agnes-video-2.5-flash", "video_size": "720P"}
    calls = []

    async def request(method, endpoint, body=None, **kwargs):
        if method == "POST":
            calls.append(body)
            return {"video_id": "local-reference-task"}
        return {"status": "completed", "url": "https://example.com/result.mp4"}

    async def download(url, target):
        target.write_bytes(b"result")

    async def register_result(relative, name, kind, **metadata):
        return {"id": "result", "kind": kind, "info": {}, **metadata}

    monkeypatch.setattr(provider, "request", request)
    monkeypatch.setattr(provider_module, "download", download)
    monkeypatch.setattr(provider_module, "register", register_result)
    await provider.video(
        "人物说你好",
        "9:16",
        4,
        first,
        [a for a in resolved if a["id"] != first["id"]],
        "test",
        lambda _: None,
    )
    body = calls[-1]
    assert body["mode"] == "reference"
    assert body["images"] == [data_uri(first), data_uri(role)]
    assert body["audios"] == [data_uri(voice)]
    assert "<Picture 2>：小雨" in body["prompt"] and "<Audio 1>" in body["prompt"]
    await provider.video("首帧", "9:16", 4, first, [], "test", lambda _: None)
    assert calls[-1]["mode"] == "reference" and calls[-1]["images"] == [data_uri(first)]
    assert "audios" not in calls[-1]


@pytest.mark.asyncio
async def test_first_frame_creation_reserves_its_slot_before_a_paid_request(
    monkeypatch,
):
    values = [media_fixture()["id"] for _ in range(30)]
    project = projects.create(CreateProject(kind="drama"))
    project = projects.save_storyboard(project["id"], board(refs=values))
    job = store.save(
        "job", {"status": "running", "action": "image", "project_id": project["id"]}
    )

    def unexpected_provider(**kwargs):
        raise AssertionError("capacity must be checked before contacting the provider")

    monkeypatch.setattr(production, "Agnes", unexpected_provider)
    with pytest.raises(ValueError, match="预留"):
        await production.generate_scene(project["id"], "one", "image", job["id"])
    assert projects.get(project["id"])["scenes"][0]["reference_ids"] == values
    assert projects.get(project["id"])["scenes"][0]["first_frame_id"] is None


@pytest.mark.asyncio
async def test_storyboard_image_uses_editable_prompt_and_binds_generated_grid(monkeypatch):
    project = projects.create(CreateProject(kind="drama", title="雨夜来信", aspect="9:16"))
    project = projects.save_storyboard(project["id"], board())
    job = store.save(
        "job",
        {
            "status": "running",
            "action": "storyboard_image",
            "project_id": project["id"],
        },
    )
    generated = media_fixture()
    request = {}

    class FakeAgnes:
        def __init__(self, **kwargs):
            request["model"] = kwargs.get("image_model")

        async def image(self, prompt, aspect, references, name):
            request.update(
                prompt=prompt,
                aspect=aspect,
                reference_ids=[value["id"] for value in references],
                name=name,
            )
            return generated

    monkeypatch.setattr(production, "Agnes", FakeAgnes)
    await production.generate_scene(
        project["id"], "one", "storyboard_image", job["id"]
    )
    scene = projects.get(project["id"])["scenes"][0]
    template = prompts.read("drama_scene_storyboard")
    assert template["group"] == "短剧" and "三行三列" in template["text"]
    assert "小雨拿起信封" in request["prompt"] and "九个连续画面" in request["prompt"]
    assert request["aspect"] == "1:1" and request["name"].endswith("九宫格故事版")
    assert scene["reference_ids"] == [generated["id"]]
    assert scene["first_frame_id"] is None


@pytest.mark.asyncio
async def test_previous_tail_uses_trimmed_last_frame_and_reuses_extraction():
    relative, path = new_media_path(".mp4")
    await run_process(
        [
            executable("ffmpeg"),
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=red:s=256x256:d=1:r=24",
            "-f",
            "lavfi",
            "-i",
            "color=blue:s=256x256:d=1:r=24",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0[v]",
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        30,
    )
    video = await register(relative, "两色测试.mp4", "video")
    project = {
        "id": "test",
        "scenes": [
            {
                "id": "one",
                "title": "上镜",
                "video_id": video["id"],
                "trim_in": 0.1,
                "duration": 0.6,
            },
            {"id": "two"},
        ],
    }
    tail = await previous_tail(project, "two")
    with Image.open(media_path(tail["path"])) as image:
        red, green, blue = image.convert("RGB").getpixel((128, 128))
        assert red > 200 and blue < 30
    assert (await previous_tail(project, "two"))["id"] == tail["id"]
    project["scenes"][0]["duration"] = 1.6
    blue_tail = await previous_tail(project, "two")
    assert blue_tail["id"] != tail["id"]
    with Image.open(media_path(blue_tail["path"])) as image:
        red, green, blue = image.convert("RGB").getpixel((128, 128))
        assert blue > 200 and red < 30
