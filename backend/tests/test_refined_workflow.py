import copy
import pytest
from studio.domain import projects
from studio.domain.models import CreateProject, ProjectPatch, Storyboard
from studio.core.store import store
from studio.workflows import production
from studio.core.paths import new_media_path


def binding_fixture(kind, name, info=None):
    # Domain binding fixtures; decoding is covered by the real FFmpeg regression.
    relative, path = new_media_path(".png" if kind == "image" else ".mp4")
    path.write_bytes(b"domain-binding-fixture")
    return store.save(
        "asset", {"kind": kind, "name": name, "path": relative, "info": info or {}}
    )


def test_existing_video_survives_frame_removal_and_generation_setting_changes():
    image = binding_fixture("image", "frame")
    video = binding_fixture("video", "clip")
    project = projects.create(CreateProject(kind="drama"))
    project = projects.save_storyboard(
        project["id"],
        Storyboard(
            title="历史兼容",
            synopsis="test",
            scenes=[
                {
                    "id": "one",
                    "title": "一",
                    "description": "窗边",
                    "first_frame_id": image["id"],
                    "video_id": video["id"],
                }
            ],
        ),
    )
    for scene in project["scenes"]:
        for key in (
            "image_model",
            "video_model",
            "aspect",
            "video_seconds",
            "video_size",
        ):
            scene.pop(key, None)
    store.save("project", project)
    scene = {**project["scenes"][0], "duration": 4}
    changed = projects.patch(
        project["id"],
        ProjectPatch(
            revision=project["revision"],
            scenes=[scene],
            scene_count=1,
            script="用户文案",
            asset_ids=[image["id"]],
        ),
    )
    assert changed["scenes"][0]["first_frame_id"] == image["id"]
    assert changed["scenes"][0]["video_id"] == video["id"]
    scene = {
        **changed["scenes"][0],
        "first_frame_id": None,
        "video_size": "1080P",
        "video_prompt": "新的运动要求",
    }
    changed = projects.patch(
        project["id"], ProjectPatch(revision=changed["revision"], scenes=[scene])
    )
    assert changed["scenes"][0]["first_frame_id"] is None
    assert changed["scenes"][0]["video_id"] == video["id"]
    with pytest.raises(KeyError):
        projects.patch(
            project["id"],
            ProjectPatch(revision=changed["revision"], asset_ids=["missing"]),
        )


@pytest.mark.asyncio
async def test_scene_overrides_reach_provider_and_pending_signature_changes(
    monkeypatch,
):
    calls = []
    image = binding_fixture("image", "frame")
    existing_video = binding_fixture("video", "existing")

    class Provider:
        def __init__(self, **overrides):
            self.settings = {
                "video_model": overrides.get("video_model") or "default-video",
                "video_size": overrides.get("video_size") or "720P",
                "video_seconds": 5,
            }
            self.base = "https://public.example/v1"
            self.overrides = overrides

        async def image(self, *args):
            calls.append(("image", self.overrides, args))
            return image

        async def video(self, *args):
            calls.append(("video", self.overrides, args))
            args[-1]({"video_id": "task", "model": self.settings["video_model"]})
            raise RuntimeError("temporary provider interruption")

    monkeypatch.setattr(production, "Agnes", Provider)
    project = projects.create(CreateProject(kind="drama", aspect="9:16"))
    project = projects.save_storyboard(
        project["id"],
        Storyboard(
            title="test",
            synopsis="test",
            scenes=[
                {
                    "id": "one",
                    "title": "一",
                    "description": "窗边",
                    "image_model": "custom-image",
                    "video_model": "custom-video",
                    "aspect": "16:9",
                    "video_seconds": 4,
                    "duration": 4,
                    "video_size": "1080P",
                    "video_id": existing_video["id"],
                }
            ],
        ),
    )
    job = store.save(
        "job", {"status": "running", "action": "video", "project_id": project["id"]}
    )
    await production.generate_scene(project["id"], "one", "image", job["id"])
    assert calls[0][1]["image_model"] == "custom-image" and calls[0][2][1] == "16:9"
    assert projects.get(project["id"])["scenes"][0]["video_id"] == existing_video["id"]
    with pytest.raises(RuntimeError):
        await production.generate_scene(project["id"], "one", "video", job["id"])
    assert calls[-1][1] == {"video_model": "custom-video", "video_size": "1080P"}
    assert calls[-1][2][1:3] == ("16:9", 4)
    original = projects.get(project["id"])
    old_signature = original["pending_videos"]["one"]["signature"]
    scene = {**original["scenes"][0], "video_seconds": 6}
    updated = projects.patch(
        project["id"], ProjectPatch(revision=original["revision"], scenes=[scene])
    )
    assert not updated["pending_videos"]
    # A leftover task must not be reused when effective global model defaults change either.
    updated["pending_videos"] = copy.deepcopy(original["pending_videos"])
    updated["scenes"][0]["video_model"] = "another-video"
    store.save("project", updated)
    with pytest.raises(RuntimeError):
        await production.generate_scene(project["id"], "one", "video", job["id"])
    assert calls[-1][2][-2] is None
    assert (
        projects.get(project["id"])["pending_videos"]["one"]["signature"]
        != old_signature
    )
    store.delete("job", job["id"])


@pytest.mark.asyncio
async def test_generated_video_resets_trim_from_collected_source(monkeypatch):
    image = binding_fixture("image", "frame")
    old_video = binding_fixture("video", "existing")
    video = binding_fixture("video", "generated")

    class Provider:
        settings = {
            "video_model": "generated-video",
            "video_size": "720P",
            "video_seconds": 5,
        }
        base = "https://public.example/v1"

        def __init__(self, **_overrides):
            pass

        async def video(self, *_args):
            return video

    monkeypatch.setattr(production, "Agnes", Provider)
    project = projects.create(CreateProject(kind="narration"))
    project = projects.save_storyboard(
        project["id"],
        Storyboard(
            title="test",
            synopsis="test",
            scenes=[
                {
                    "id": "one",
                    "title": "电商仓库",
                    "description": "仓库打包发货",
                    "narration": "早期电商仓库正在打包发货。",
                    "video_prompt": "纸箱沿传送带移动",
                    "first_frame_id": image["id"],
                    "video_id": old_video["id"],
                    "trim_in": 15,
                }
            ],
        ),
    )
    job = store.save(
        "job", {"status": "running", "action": "video", "project_id": project["id"]}
    )

    await production.generate_scene(project["id"], "one", "video", job["id"])

    scene = projects.get(project["id"])["scenes"][0]
    assert scene["video_id"] == video["id"]
    assert scene["trim_in"] == 0
    assert store.get("asset", old_video["id"])["name"] == "existing"
