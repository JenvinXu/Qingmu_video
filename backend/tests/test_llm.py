import base64
import io
import json
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from studio.api.app import app
from studio.core.paths import TOKEN, INTERNAL_TOKEN, new_media_path
from studio.core.store import store
from studio.domain.models import Settings, CreateProject
from studio.domain import projects
from studio.library.service import register
from studio.providers.settings import (
    save_settings,
    read_settings,
    llm_connection,
    safe_error,
)
from studio.providers.llm import LLM
from studio.agent.tools import execute
from studio.providers.responses import normalize_input, ResponseObserver


def test_split_terminal_sse_preserves_usage_without_retaining_content():
    observer = ResponseObserver()
    event = (
        "event: response.completed\r\ndata: "
        + json.dumps(
            {
                "type": "response.completed",
                "response": {
                    "id": "resp-real",
                    "usage": {"input_tokens": 12, "output_tokens": 8},
                    "output": [{"text": "图片中的人物"}],
                },
            },
            ensure_ascii=False,
        )
        + "\r\n\r\n"
    ).encode("utf-8")
    for index in range(0, len(event), 7):
        observer.feed(event[index : index + 7])
    assert observer.status == "completed" and observer.usage == {
        "input_tokens": 12,
        "output_tokens": 8,
    }
    assert observer.request_id == "resp-real" and observer.buffer == ""
    assert "人物" not in str(vars(observer))


def test_qianfan_assistant_history_uses_output_text():
    history = [
        {"role": "user", "content": [{"type": "input_text", "text": "idea"}]},
        {"role": "assistant", "content": [{"type": "output_text", "text": "checking"}]},
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "studio_context",
            "arguments": "{}",
        },
        {"type": "function_call_output", "call_id": "call_1", "output": "context"},
    ]
    native = normalize_input(history, assistant_output=True)
    assert native[0]["content"][0]["type"] == "input_text"
    assert native[1]["content"][0]["type"] == "output_text"
    assert native[2]["call_id"] == native[3]["call_id"] == "call_1"
    assert normalize_input(history)[1]["content"][0]["type"] == "input_text"


def test_independent_connections_encrypted_and_legacy_migration():
    # Legacy records gain new defaults without changing their previous media key.
    from studio.core.secrets import encrypt

    store.save(
        "settings",
        {
            "id": "models",
            "base_url": "https://media.example/v1",
            "text_model": "old-text",
            "encrypted_key": encrypt("old-media-key"),
        },
    )
    assert llm_connection()["api_key"] == "old-media-key"
    assert read_settings()["llm_provider"] == "media"
    assert read_settings()["video_key_configured"]
    assert read_settings(True)["video_api_key"] == "old-media-key"
    public = save_settings(
        Settings(
            base_url="https://media.example/v1",
            api_key="media-private",
            video_api_key="video-private",
            llm_provider="qianfan",
            llm_api_key="llm-private",
            text_model="deepseek-v4-flash",
        )
    )
    saved = store.get("settings", "models")
    stored = json.dumps(saved)
    assert all(
        secret not in stored
        for secret in ("media-private", "video-private", "llm-private")
    )
    assert (
        not {
            "api_key",
            "video_api_key",
            "llm_api_key",
            "encrypted_key",
            "encrypted_video_key",
            "encrypted_llm_key",
        }
        & public.keys()
    )
    assert (
        public["key_configured"]
        and public["video_key_configured"]
        and public["llm_key_configured"]
    )
    save_settings(Settings.model_validate(public))
    assert read_settings(True)["api_key"] == "media-private"
    assert read_settings(True)["video_api_key"] == "video-private"
    assert llm_connection()["api_key"] == "llm-private"
    assert llm_connection()["base_url"] == "https://qianfan.baidubce.com/v2"
    assert read_settings()["base_url"] == "https://media.example/v1"
    assert (
        safe_error(RuntimeError("media-private, video-private and llm-private"))
        == "[已隐藏], [已隐藏] and [已隐藏]"
    )
    with TestClient(app) as client:
        response = client.get(
            "/api/settings", headers={"Authorization": "Bearer " + TOKEN}
        )
        assert (
            "llm-private" not in response.text
            and "media-private" not in response.text
            and "video-private" not in response.text
        )
        internal = client.get(
            "/api/internal/agent-config",
            headers={"Authorization": "Bearer " + INTERNAL_TOKEN},
        ).json()
        assert (
            internal["api_key"] == "llm-private"
            and internal["text_model"] == "deepseek-v4-flash"
        )
    with pytest.raises(ValueError):
        save_settings(Settings(llm_base_url="http://outside.example/v2"))


@pytest.mark.asyncio
async def test_visual_tool_uses_pixels_without_changing_agent_model(monkeypatch):
    save_settings(
        Settings(
            api_key="media-private",
            llm_api_key="llm-private",
            llm_provider="qianfan",
            text_model="deepseek-v4-flash",
            vision_model="kimi-k2.6",
        )
    )
    relative, path = new_media_path(".png")
    Image.new("RGB", (2200, 1100), (42, 170, 90)).save(path)
    value = await register(relative, name="picture", kind="image")
    project = projects.create(CreateProject(kind="drama"))
    calls = []

    async def request(self, method, endpoint, payload=None):
        calls.append((self.config, endpoint, payload))
        return {
            "choices": [{"message": {"content": "绿色画面"}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 10},
        }

    monkeypatch.setattr(LLM, "request", request)
    result = await execute(
        project["id"],
        "",
        "studio_inspect_asset",
        {"asset_id": value["id"], "question": "什么颜色？"},
    )
    assert result["model"] == "kimi-k2.6" and result["description"] == "绿色画面"
    config, endpoint, payload = calls[0]
    assert config["api_key"] == "llm-private" and endpoint == "/chat/completions"
    assert payload["model"] == "kimi-k2.6" and "temperature" not in payload
    uri = payload["messages"][-1]["content"][-1]["image_url"]["url"]
    with Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1]))) as image:
        assert image.size == (1536, 768)
        assert image.getpixel((10, 10))[1] > 150
    assert llm_connection()["text_model"] == "deepseek-v4-flash"
    assert projects.get(project["id"])["revision"] == project["revision"]
    with pytest.raises(KeyError):
        await execute(
            project["id"], "", "studio_inspect_asset", {"asset_id": "../../private-key"}
        )
    document_relative, document_path = new_media_path(".txt")
    document_path.write_text("visual tool must reject text", encoding="utf-8")
    not_image = await register(document_relative, name="document.txt", kind="document")
    with pytest.raises(ValueError, match="读图仅支持"):
        await LLM().inspect_asset(not_image["id"])
    assert len(calls) == 1
