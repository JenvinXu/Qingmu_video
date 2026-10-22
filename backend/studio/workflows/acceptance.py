from __future__ import annotations
import hashlib
import json
import time
from ..core.paths import DATA, media_path
from ..core.store import store
from ..domain import projects
from ..domain.models import CreateProject
from ..jobs.manager import jobs
from ..agent.client import agent_run
from ..library.service import asset
from ..media.process import validate_video


async def acceptance(job_id: str, resume=False):
    report = {
        "id": job_id,
        "started_at": time.time(),
        "checks": [],
        "status": "running",
        "project_ids": [],
    }

    def check(name, detail):
        report["checks"].append(
            {"name": name, "status": "passed", "detail": detail, "time": time.time()}
        )
        (DATA / "reports" / f"{job_id}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    try:
        recent = store.list("report", 1)
        previous = (
            recent[0]
            if resume
            and recent
            and recent[0].get("status") == "failed"
            and recent[0].get("project_ids")
            else None
        )
        drama = (
            projects.get(previous["project_ids"][0])
            if previous
            else projects.create(
                CreateProject(
                    kind="drama",
                    title="验收 · 一封迟到的信",
                    scene_count=2,
                    target_duration=10,
                    aspect="16:9",
                    prompt="制作两个镜头的温暖微短剧：一位穿浅绿色衬衫的年轻人，在窗边发现一封旧信，读信后释然微笑。每镜只说一句不超过12字的中文旁白，两镜同一角色和服装，不需要复杂音效。",
                )
            )
        )
        report["project_ids"].append(drama["id"])
        jobs.update(job_id, acceptance_phase="drama")
        jobs.event(
            job_id, "acceptance", "验收短剧：Codex → 首帧 → 视频 → 旁白 → 剪辑", 3
        )
        await agent_run(drama["id"], job_id, "", "auto")
        drama = projects.get(drama["id"])
        if len(drama["scenes"]) != 2:
            raise ValueError("验收短剧需要两个真实镜头")
        check(
            "Codex App Server 工具执行",
            {"project_id": drama["id"], "scenes": len(drama["scenes"])},
        )
        for index, scene in enumerate(drama["scenes"]):
            if (
                not scene.get("first_frame_id")
                or not scene.get("video_id")
                or not scene.get("audio_id")
            ):
                raise ValueError("验收镜头缺少首帧、视频或旁白")
            check(
                f"镜头 {index + 1} 模型图片与视频",
                {
                    "frame": scene["first_frame_id"],
                    "video": scene["video_id"],
                    "provider_video_id": asset(scene["video_id"]).get(
                        "provider_video_id"
                    ),
                },
            )
        video = asset(drama["export_id"])
        info = await validate_video(media_path(video["path"]), True)
        check(
            "短剧剪辑成片与解码",
            {
                "asset_id": video["id"],
                "info": info,
                "sha256": hashlib.sha256(
                    media_path(video["path"]).read_bytes()
                ).hexdigest(),
            },
        )
        narration = projects.create(
            CreateProject(
                kind="narration",
                title="验收 · 给生活一点留白",
                scene_count=2,
                target_duration=12,
                aspect="9:16",
                prompt="两镜头中文口播：工作间隙，给自己一个短暂的停顿。看一眼窗外，喝一口水，再从容开始。画面为窗边绿植与玻璃水杯，每镜一句简短旁白，全部字数不超过30字。",
            )
        )
        report["project_ids"].append(narration["id"])
        jobs.update(job_id, acceptance_phase="narration")
        jobs.event(job_id, "acceptance", "验收口播：一段话自动制作真实旁白与视频", 65)
        await agent_run(narration["id"], job_id, "", "auto")
        narration = projects.get(narration["id"])
        video = asset(narration["export_id"])
        info = await validate_video(media_path(video["path"]), True)
        check(
            "口播一键成片",
            {
                "project_id": narration["id"],
                "asset_id": video["id"],
                "info": info,
                "sha256": hashlib.sha256(
                    media_path(video["path"]).read_bytes()
                ).hexdigest(),
            },
        )
        check(
            "SQLite 持久化",
            {
                "project_revision": projects.get(narration["id"])["revision"],
                "db": "studio.sqlite3",
            },
        )
        report.update(
            status="passed",
            finished_at=time.time(),
            duration_seconds=round(time.time() - report["started_at"], 2),
        )
        return report
    except BaseException as error:
        report.update(status="failed", finished_at=time.time(), error=str(error)[:2000])
        raise
    finally:
        (DATA / "reports" / f"{job_id}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        store.save("report", report)
