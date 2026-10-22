import asyncio
import importlib

import pytest

from studio.agent import tools as agent_tools
from studio.core.store import store
from studio.domain import projects
from studio.domain.models import CreateProject, Storyboard
from studio.jobs.manager import jobs


def drama_with_scene():
    project = projects.create(CreateProject(kind="drama", target_duration=5, shot_duration=5))
    return projects.save_storyboard(
        project["id"],
        Storyboard(
            title="灯",
            synopsis="一盏灯被重新点亮。",
            script="（0-5秒）分镜1：女孩点亮灯。",
            scenes=[
                {
                    "id": "one",
                    "title": "点灯",
                    "description": "女孩点亮灯。",
                    "duration": 5,
                    "video_seconds": 5,
                }
            ],
        ),
    )


@pytest.mark.asyncio
async def test_auto_production_bypasses_timed_agent_tool_when_storyboard_exists(monkeypatch):
    api_module = importlib.import_module("studio.api.app")
    project = drama_with_scene()
    called = []

    async def no_agent(*_args, **_kwargs):
        raise AssertionError("existing storyboard must not re-enter App Server")

    async def produce(project_id, job_id):
        called.append((project_id, job_id))
        return {"asset_id": "export-test"}

    monkeypatch.setattr(api_module, "agent_run", no_agent)
    monkeypatch.setattr(api_module.production, "produce", produce)
    result = await api_module._auto_produce(project["id"], "outer-job")
    assert result == {
        "planning": None,
        "production": {"asset_id": "export-test"},
    }
    assert called == [(project["id"], "outer-job")]


@pytest.mark.asyncio
async def test_agent_produce_tool_schedules_one_reusable_background_job(monkeypatch):
    project = drama_with_scene()
    outer = store.save(
        "job",
        {
            "action": "chat",
            "project_id": project["id"],
            "status": "running",
            "events": [],
        },
    )
    gate = asyncio.Event()

    async def produce(project_id, job_id):
        assert project_id == project["id"]
        gate.set()
        await asyncio.sleep(0.05)
        return {"asset_id": "export-test", "job_id": job_id}

    monkeypatch.setattr(agent_tools.production, "produce", produce)
    first = await agent_tools.execute(project["id"], outer["id"], "studio_produce", {})
    second = await agent_tools.execute(project["id"], outer["id"], "studio_produce", {})
    assert first["scheduled"] is True
    assert second["job_id"] == first["job_id"]
    await asyncio.wait_for(gate.wait(), timeout=1)
    for _ in range(50):
        child = store.get("job", first["job_id"])
        if child["status"] == "completed":
            break
        await asyncio.sleep(0.01)
    assert child["status"] == "completed"
    jobs.update(outer["id"], status="completed")
