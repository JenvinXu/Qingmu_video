import pytest
from fastapi.testclient import TestClient
from studio.api.app import app
from studio.core.paths import TOKEN
from studio.core.store import store
from studio.agent import prompts
from studio.domain import projects
from studio.domain.models import CreateProject, ProjectPatch, Storyboard
from studio.domain.script_format import drama_segments


def test_prompt_versions_validation_and_rendered_stage_use_saved_text():
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer " + TOKEN}
        entries = client.get("/api/prompts", headers=headers).json()
        original = next(p for p in entries if p["id"] == "drama_storyboard")
        endpoint = "/api/prompts/drama_storyboard"
        payload = {
            "revision": original["revision"],
            "text": original["text"] + "\n自定义要求：每镜 7 秒。",
        }
        changed = client.put(endpoint, headers=headers, json=payload)
        assert changed.status_code == 200
        assert client.put(endpoint, headers=headers, json=payload).status_code == 409
        bad = client.put(
            endpoint,
            headers=headers,
            json={"revision": changed.json()["revision"], "text": "{unknown_variable}"},
        )
        assert bad.status_code == 422
        project = projects.create(
            CreateProject(kind="drama", prompt="想法", asset_ids=[])
        )
        project = projects.commit(project, script="（0-5秒）分镜1：保留用户原文")
        rendered, used = prompts.prepare(project, "storyboard")
        assert "自定义要求：每镜 7 秒。" in rendered and "保留用户原文" in rendered
        assert "只能" in rendered and "不虚构 ID" in rendered
        assert (
            next(p for p in used if p["id"] == "drama_storyboard")["revision"]
            == changed.json()["revision"]
        )
        prompts.update(original["id"], original["text"], changed.json()["revision"])


def test_adapted_creative_skills_are_editable_and_composed_by_drama_stage():
    catalog = {entry["id"]: entry for entry in prompts.catalog()}
    assert catalog["skill_screenwriting"]["group"] == "创作 Skills"
    assert catalog["skill_visual_video"]["group"] == "创作 Skills"
    assert catalog["agnes_prompt_adapter"]["group"] == "创作 Skills"
    assert catalog["agent_rules"]["title"] == "系统提示词"

    project = projects.create(
        CreateProject(
            kind="drama",
            prompt="两位旧友在停电的车站争夺一封信",
            target_duration=10,
            shot_duration=5,
        )
    )
    idea, idea_versions = prompts.prepare(project, "idea")
    assert "ScreenwritingSkill" in idea and "五段递进" in idea
    assert "VisualVideoSkill" not in idea
    assert {item["id"] for item in idea_versions} >= {
        "agent_rules",
        "skill_screenwriting",
        "drama_idea",
    }

    project = projects.save_script(
        project["id"],
        "（0-5秒）分镜1：林岚攥住信封。\n（5-10秒）分镜2：周野松开手。",
        "主题：信任；人物：林岚、周野；场景：停电车站；物品：旧信封。",
    )
    board, board_versions = prompts.prepare(project, "storyboard")
    assert "VisualVideoSkill" in board and "AgnesPromptAdapter" in board
    assert "image_prompt 只写第一帧静态瞬间" in board
    assert "video_prompt 从首帧继续" in board
    assert "dialogue 只保存人物实际说出的原句" in board
    assert "speaker_id 指向说话角色" in board
    assert "视频模型生成自然对白" in board
    assert "narration 只保存明确标记的少量画外旁白" in board
    assert {item["id"] for item in board_versions} >= {
        "skill_visual_video",
        "agnes_prompt_adapter",
        "drama_storyboard",
    }


def test_storyboard_keeps_the_screenwriting_production_design():
    project = projects.create(
        CreateProject(kind="drama", target_duration=5, shot_duration=5)
    )
    project = projects.save_script(
        project["id"],
        "（0-5秒）分镜1：女孩把旧车票递给朋友。",
        "人物：女孩与朋友；场景：车站；物品：旧车票。",
    )
    saved = projects.save_storyboard(
        project["id"],
        Storyboard(
            title="车站",
            synopsis="模型不应覆盖已完成的制作设计",
            script=project["script"],
            scenes=[
                {
                    "id": "one",
                    "title": "递出车票",
                    "description": "女孩把旧车票递给朋友。",
                    "duration": 5,
                }
            ],
        ),
    )
    assert saved["synopsis"] == "人物：女孩与朋友；场景：车站；物品：旧车票。"


def test_drama_script_markers_determine_count_and_copy_each_scene_verbatim():
    script = (
        "（0-5秒）分镜1：中景，女孩推开车站大门。\n"
        "（5-11秒）分镜2：特写，她把旧车票放进朋友掌心。"
    )
    segments = drama_segments(script, required=True)
    assert [(s["number"], s["duration"]) for s in segments] == [(1, 5), (2, 6)]
    project = projects.create(CreateProject(kind="drama"))
    project = projects.patch(
        project["id"], ProjectPatch(revision=project["revision"], script=script)
    )
    assert project["scene_count"] == 2
    board = Storyboard(
        title="车站重逢",
        synopsis="两位朋友重逢。",
        script="模型不得替换此原文",
        scenes=[
            {
                "id": str(index),
                "title": f"镜头 {index}",
                "description": segment["text"],
                "duration": segment["duration"],
            }
            for index, segment in enumerate(segments, start=1)
        ],
    )
    saved = projects.save_storyboard(project["id"], board)
    assert saved["script"] == script and saved["scene_count"] == 2
    assert [s["description"] for s in saved["scenes"]] == [s["text"] for s in segments]
    wrong = board.model_copy(deep=True)
    wrong.scenes[0].description = "概括后的文案"
    with pytest.raises(ValueError, match="原样复制"):
        projects.save_storyboard(project["id"], wrong)


def test_drama_prompt_uses_saved_shot_duration_as_exact_plan():
    project = projects.create(
        CreateProject(kind="drama", prompt="地铁站重逢", target_duration=60, shot_duration=8)
    )
    rendered, _ = prompts.prepare(project, "idea")
    assert "单个分镜时长：8 秒" in rendered
    assert "共 8 个分镜，时长依次为 [8, 8, 8, 8, 8, 8, 8, 4] 秒" in rendered
    assert "禁止为了叙事结构自行增减、均分、合并或拆分分镜" in rendered


def test_generated_sixty_second_script_requires_two_thirty_second_scenes():
    project = projects.create(
        CreateProject(kind="drama", target_duration=60, shot_duration=30)
    )
    wrong = (
        "（0-20秒）分镜1：第一段。\n"
        "（20-40秒）分镜2：第二段。\n"
        "（40-60秒）分镜3：第三段。"
    )
    with pytest.raises(ValueError, match="要求 2 个分镜.*30、30 秒"):
        projects.save_script(project["id"], wrong)
    saved = projects.save_script(
        project["id"],
        "（0-30秒）分镜1：第一段。\n（30-60秒）分镜2：第二段。",
    )
    assert saved["scene_count"] == 2
    assert [segment["duration"] for segment in drama_segments(saved["script"])] == [30, 30]


def test_generated_non_divisible_duration_uses_short_final_scene():
    project = projects.create(
        CreateProject(kind="drama", target_duration=65, shot_duration=30)
    )
    saved = projects.save_script(
        project["id"],
        (
            "（0-30秒）分镜1：第一段。\n"
            "（30-60秒）分镜2：第二段。\n"
            "（60-65秒）分镜3：收束。"
        ),
    )
    assert [segment["duration"] for segment in drama_segments(saved["script"])] == [30, 30, 5]


@pytest.mark.parametrize("seconds", [1, 7, 13, 29, 30])
def test_drama_duration_accepts_every_integer_through_thirty(seconds):
    project = projects.create(
        CreateProject(kind="drama", shot_duration=seconds)
    )
    assert project["shot_duration"] == seconds
    project = projects.save_storyboard(
        project["id"],
        Storyboard(
            title="t",
            synopsis="s",
            scenes=[
                {
                    "id": "one",
                    "title": "t",
                    "description": "d",
                    "duration": seconds,
                    "video_seconds": seconds,
                }
            ],
        ),
    )
    assert project["scenes"][0]["duration"] == seconds
    assert project["scenes"][0]["video_seconds"] == seconds


def test_drama_duration_rejects_values_over_thirty():
    with pytest.raises(ValueError, match="less than or equal to 30"):
        CreateProject(kind="drama", shot_duration=31)
    with pytest.raises(ValueError, match="单镜最长 30 秒"):
        drama_segments("（0-31秒）分镜1：超长分镜", required=True)


def test_drama_duration_is_shared_without_discarding_existing_video():
    project = projects.create(CreateProject(kind="drama"))
    project = projects.save_storyboard(
        project["id"],
        Storyboard(
            title="t",
            synopsis="s",
            scenes=[
                {
                    "id": "one",
                    "title": "t",
                    "description": "d",
                    "duration": 5.2,
                    "video_seconds": 4,
                }
            ],
        ),
    )
    assert (
        project["scenes"][0]["duration"] == project["scenes"][0]["video_seconds"] == 6
    )
    # Changing the old generation field alone also updates the timeline duration.
    scene = {**project["scenes"][0], "video_seconds": 7}
    project = projects.patch(
        project["id"], ProjectPatch(revision=project["revision"], scenes=[scene])
    )
    assert (
        project["scenes"][0]["duration"] == project["scenes"][0]["video_seconds"] == 7
    )
    project["export_id"] = "previous-export"
    store.save("project", project)
    scene = {**project["scenes"][0], "duration": 8}
    project = projects.patch(
        project["id"], ProjectPatch(revision=project["revision"], scenes=[scene])
    )
    assert (
        project["scenes"][0]["duration"] == project["scenes"][0]["video_seconds"] == 8
    )
    assert project["export_id"] is None


@pytest.mark.asyncio
async def test_video_duration_outside_app_range_does_not_call_provider(monkeypatch):
    from studio.providers.agnes import Agnes

    async def forbidden(*args, **kwargs):
        pytest.fail("Invalid duration reached provider")

    monkeypatch.setattr(Agnes, "request", forbidden)
    with pytest.raises(ValueError, match="1–30"):
        await Agnes().video("prompt", "9:16", 31, None, [], "scene", lambda _: None)
