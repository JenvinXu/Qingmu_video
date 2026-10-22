from __future__ import annotations
import asyncio
import time
from collections.abc import Awaitable, Callable
from ..core.store import store
from ..providers.settings import safe_error

TRANSITIONS = {
    "queued": {"running", "cancelled"},
    "running": {"completed", "failed", "cancelled"},
}


class Jobs:
    def __init__(self):
        self.tasks: dict[str, asyncio.Task] = {}
        self.project_locks: dict[str, asyncio.Lock] = {}

    def recover(self):
        for job in store.list("job", 1000):
            if job["status"] in {"queued", "running"}:
                self.update(
                    job["id"],
                    status="failed",
                    error="应用上次退出时任务被中断。已生成的素材保留，可重新制作。",
                )

    def update(self, ident, **changes):
        job = store.get("job", ident)
        if "status" in changes and changes["status"] != job["status"]:
            allowed = TRANSITIONS.get(job["status"], set())
            if changes["status"] not in allowed and not (
                job["status"] == "queued" and changes["status"] == "failed"
            ):
                raise ValueError("无效任务状态转换")
        job.update(changes)
        if job["status"] in {"completed", "failed", "cancelled"}:
            job["finished_at"] = time.time()
        return store.save("job", job)

    def event(self, ident, stage: str, message: str, progress: int):
        job = store.get("job", ident)
        if job["status"] != "running":
            raise asyncio.CancelledError("任务已经结束")
        if job["action"] == "acceptance":
            progress = (
                round(progress * 0.55)
                if job.get("acceptance_phase") != "narration"
                else 55 + round(progress * 0.44)
            )
        events = job.get("events", [])[-199:]
        events.append({"time": time.time(), "stage": stage, "message": message})
        return self.update(
            ident, stage=stage, message=message, progress=progress, events=events
        )

    def busy(self, project_id):
        return any(
            (j.get("project_id") == project_id or j["action"] == "acceptance")
            and j["status"] in {"queued", "running"}
            for j in store.list("job")
        )

    def start(
        self,
        action: str,
        project_id: str | None,
        operation: Callable[[str], Awaitable],
        *,
        allow_busy: bool = False,
    ):
        if project_id and not allow_busy and self.busy(project_id):
            raise ValueError("当前作品正在制作，请等待完成或取消任务")
        job = store.save(
            "job",
            {
                "action": action,
                "project_id": project_id,
                "status": "queued",
                "progress": 0,
                "stage": "queued",
                "message": "等待制作",
                "events": [],
                "created_at": time.time(),
            },
        )

        async def work():
            try:
                self.update(job["id"], status="running")
                result = await operation(job["id"])
                self.update(
                    job["id"],
                    status="completed",
                    progress=100,
                    result=result,
                    message="制作完成",
                )
            except asyncio.CancelledError:
                self.update(
                    job["id"],
                    status="cancelled",
                    message="任务已取消，完成的素材已保留",
                )
            except Exception as exc:
                self.update(
                    job["id"],
                    status="failed",
                    error=safe_error(exc),
                    message="制作失败",
                )
            finally:
                self.tasks.pop(job["id"], None)

        self.tasks[job["id"]] = asyncio.create_task(work())
        return job

    def start_production(self, project_id: str, operation: Callable[[str], Awaitable]):
        """Schedule long media work outside the five-minute App Server tool call."""
        existing = next(
            (
                job
                for job in store.list("job")
                if job.get("project_id") == project_id
                and job.get("action") == "produce"
                and job.get("status") in {"queued", "running"}
            ),
            None,
        )
        return existing or self.start(
            "produce", project_id, operation, allow_busy=True
        )

    async def cancel(self, ident):
        store.get("job", ident)
        if task := self.tasks.get(ident):
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return store.get("job", ident)


jobs = Jobs()
