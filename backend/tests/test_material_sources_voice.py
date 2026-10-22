import pytest

from studio.core.paths import new_media_path
from studio.core.store import store
from studio.domain import projects
from studio.domain.models import CreateProject, Storyboard
from studio.library.sources import rank_candidate, search_videos
from studio.media.process import executable, run_process
from studio.providers.voice import clean_voice_audio
from studio.providers.agnes import Agnes
from studio.workflows import production


def test_material_ranking_uses_real_term_coverage():
    exact = rank_candidate(
        "Lei Jun Xiaomi product launch",
        {
            "provider": "wikimedia",
            "kind": "video",
            "name": "Lei Jun at Xiaomi product launch",
            "description": "Founder presenting a new phone on stage",
        },
    )
    generic = rank_candidate(
        "Lei Jun Xiaomi product launch",
        {
            "provider": "archive",
            "kind": "video",
            "name": "Business office",
            "description": "People working at desks",
        },
    )
    assert exact["score"] >= 90 and exact["score"] > generic["score"]
    assert {"lei", "jun", "xiaomi", "product", "launch"}.issubset(
        set(exact["matched_terms"])
    )


def test_material_ranking_rejects_description_only_archive_matches():
    value = rank_candidate(
        "Hong Kong skyline",
        {
            "provider": "internet_archive",
            "kind": "video",
            "name": "Unrelated archived recording",
            "description": "A page mentioning Hong Kong skyline among many tags",
        },
    )
    assert value["score"] < 58
    assert value["title_matched_terms"] == []


@pytest.mark.asyncio
async def test_video_submission_retries_explicit_queue_unavailable(monkeypatch):
    model = object.__new__(Agnes)
    model.base = "https://media.example/v1"
    model.settings = {
        "video_model": "agnes-video-2.5-flash",
        "video_size": "720P",
    }
    posts = 0

    async def request(method, endpoint, payload=None, **kwargs):
        nonlocal posts
        if method == "POST":
            posts += 1
            if posts == 1:
                raise RuntimeError(
                    '模型接口 HTTP 503: {"code":"video_queue_unavailable"}'
                )
            return {"video_id": "video-1"}
        return {"status": "failed", "error": "test stop after submission"}

    async def no_sleep(_):
        return None

    monkeypatch.setattr(model, "request", request)
    monkeypatch.setattr("studio.providers.agnes.asyncio.sleep", no_sleep)
    messages = []
    with pytest.raises(RuntimeError, match="test stop after submission"):
        await model.video(
            "prompt",
            "9:16",
            5,
            None,
            [],
            "test",
            messages.append,
        )
    assert posts == 2
    assert any("视频队列暂满" in message for message in messages)


@pytest.mark.asyncio
async def test_image_submission_retries_explicit_full_queue(monkeypatch):
    model = object.__new__(Agnes)
    model.base = "https://media.example/v1"
    model.settings = {"image_model": "agnes-image-2.1-flash"}
    model.headers = {}
    posts = 0

    async def request(method, endpoint, payload=None, **kwargs):
        nonlocal posts
        posts += 1
        if posts == 1:
            raise RuntimeError('模型接口 HTTP 503: {"message":"生图队列已满"}')
        return {"data": []}

    async def no_sleep(_):
        return None

    monkeypatch.setattr(model, "request", request)
    monkeypatch.setattr("studio.providers.agnes.asyncio.sleep", no_sleep)
    with pytest.raises(RuntimeError, match="未返回图片"):
        await model.image("prompt", "9:16", [], "test")
    assert posts == 2


@pytest.mark.asyncio
async def test_multisource_search_deduplicates_and_orders(monkeypatch):
    async def first(query):
        return [
            {
                "provider": "wikimedia",
                "kind": "video",
                "name": "Wuhan University campus students",
                "description": query,
                "url": "https://media.example/one.mp4",
                "page_url": "https://example.org/one",
            }
        ]

    async def second(query):
        return [
            {
                "provider": "archive",
                "kind": "video",
                "name": "Campus",
                "description": "unrelated",
                "url": "https://media.example/two.mp4",
                "page_url": "https://example.org/two",
            },
            {
                "provider": "archive",
                "kind": "video",
                "name": "duplicate",
                "description": "unrelated",
                "url": "https://media.example/duplicate.mp4",
                "page_url": "https://example.org/one",
            },
        ]

    monkeypatch.setitem(
        __import__("studio.library.sources", fromlist=["VIDEO_PROVIDERS"]).VIDEO_PROVIDERS,
        "first",
        first,
    )
    monkeypatch.setitem(
        __import__("studio.library.sources", fromlist=["VIDEO_PROVIDERS"]).VIDEO_PROVIDERS,
        "second",
        second,
    )
    values = await search_videos(
        "Wuhan University campus students", {"first", "second"}
    )
    assert len(values) == 2
    assert values[0]["page_url"] == "https://example.org/one"
    assert values[0]["score"] > values[1]["score"]


@pytest.mark.asyncio
async def test_collected_video_is_bound_only_above_threshold(monkeypatch):
    project = projects.create(CreateProject(kind="narration", scene_count=1))
    project = projects.save_storyboard(
        project["id"],
        Storyboard(
            title="口播",
            synopsis="test",
            script="雷军创办小米。",
            scenes=[
                {
                    "id": "one",
                    "title": "创办小米",
                    "description": "雷军和团队创业",
                    "narration": "雷军创办小米。",
                    "material_query": "Lei Jun Xiaomi startup team",
                }
            ],
        ),
    )
    relative, path = new_media_path(".mp4")
    path.write_bytes(b"fixture")
    video = store.save(
        "asset",
        {
            "kind": "video",
            "name": "real clip",
            "path": relative,
            "info": {"duration": 8, "streams": [{"codec_type": "video"}]},
        },
    )
    job = store.save(
        "job", {"status": "running", "action": "materials", "project_id": project["id"]}
    )

    async def candidates(query):
        return [
            {
                "provider": "wikimedia",
                "kind": "video",
                "name": "Lei Jun Xiaomi startup team",
                "description": query,
                "url": "https://media.example/clip.mp4",
                "page_url": "https://example.org/clip",
                "license": "CC BY 4.0",
                "score": 91,
                "match_reason": "全部检索要点命中",
            }
        ]

    async def collected(*args, **kwargs):
        return video

    monkeypatch.setattr(production, "search_videos", candidates)
    monkeypatch.setattr(production, "collect", collected)
    result = await production.collect_scene_video(
        project["id"], "one", job["id"]
    )
    scene = projects.get(project["id"])["scenes"][0]
    assert result["asset_id"] == video["id"]
    assert scene["video_id"] == video["id"] and scene["match_score"] == 91


@pytest.mark.asyncio
async def test_voice_cleanup_removes_long_pause(tmp_path):
    source, target = tmp_path / "raw.mp3", tmp_path / "clean.mp3"
    await run_process(
        [
            executable("ffmpeg"),
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.8",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=mono:d=1.2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=550:duration=0.8",
            "-filter_complex",
            "[0:a][1:a][2:a]concat=n=3:v=0:a=1[a]",
            "-map",
            "[a]",
            str(source),
        ],
        30,
    )
    timing = await clean_voice_audio(source, target)
    assert timing["original_duration"] > 2.7
    assert 1.5 < timing["cleaned_duration"] < 2.2
    assert timing["silence_reduced_seconds"] > 0.6
