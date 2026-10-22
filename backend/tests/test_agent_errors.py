from studio.agent.client import _provider_error_detail, _unfinished_export_error
from studio.core.store import store


def test_queue_full_error_keeps_provider_code_and_request_id():
    message = _provider_error_detail(
        '模型接口 HTTP 503: {"code":"video_queue_full","message":"视频队列已满，请稍后重试 (request id: req-123)"}'
    )
    assert "视频模型队列已满" in message
    assert "HTTP 503 / video_queue_full" in message
    assert "req-123" in message


def test_auto_failure_prefers_real_tool_error_and_scene_stage():
    job = store.save(
        "job",
        {
            "action": "auto",
            "project_id": "project-error-test",
            "status": "running",
            "progress": 30,
            "stage": "video",
            "message": "制作中",
            "events": [
                {
                    "time": 1,
                    "stage": "video",
                    "message": "分镜 02 · 生成视频",
                },
                {
                    "time": 2,
                    "stage": "video",
                    "message": "视频模型 in_progress · 10%",
                },
            ],
        },
    )
    message = _unfinished_export_error(
        {
            "message": "我未能完成制作",
            "last_tool_failure": {
                "tool": "studio_produce",
                "error": "fetch failed",
            },
        },
        job["id"],
    )
    assert message.startswith("分镜 02 · 生成视频失败：")
    assert "与模型服务的连接中断" in message
    assert "fetch failed" in message
    assert "已完成的分镜和素材已保留" in message
    assert "我未能完成制作" not in message
