"""Text uses native Responses; visual inspection is a bounded Chat Completions tool.

Codex keeps its inexpensive text model while the visual model receives actual pixels.
The media-generation connection is independent of both.
"""

from __future__ import annotations
from ..agent.prompts import read, render
import base64
import io
import time
import httpx
from PIL import Image, ImageOps
from .settings import llm_connection, safe_error
from ..core.network import async_client
from ..core.paths import media_path
from ..core.store import store
from ..library.service import asset


class LLM:
    def __init__(self):
        self.config = llm_connection()
        if not self.config["api_key"]:
            raise ValueError("请先在模型设置中保存 LLM API Key")

    async def request(self, method, endpoint, payload=None):
        config = self.config
        started = time.time()
        trace = {
            "kind": "llm_model",
            "provider": config["provider"],
            "model": (payload or {}).get("model"),
            "endpoint": config["base_url"] + endpoint,
        }
        try:
            async with async_client(
                target_url=config["base_url"], timeout=httpx.Timeout(180, connect=20)
            ) as client:
                response = await client.request(
                    method,
                    config["base_url"] + endpoint,
                    headers={"Authorization": "Bearer " + config["api_key"]},
                    json=payload,
                )
                if response.is_error:
                    raise RuntimeError(
                        f"LLM 接口 HTTP {response.status_code}: {response.text[:1600]}"
                    )
                result = response.json()
                trace.update(
                    status="completed",
                    usage=result.get("usage"),
                    request_id=result.get("id"),
                )
                return result
        except Exception as error:
            trace.update(status="failed", error=safe_error(error))
            raise
        finally:
            trace["duration_ms"] = round((time.time() - started) * 1000)
            store.save("trace", trace)

    async def test(self):
        model = self.config["text_model"]
        result = await self.request(
            "POST",
            "/responses",
            {
                "model": model,
                "input": "只回复：连接成功",
                "max_output_tokens": 1024,
                "store": False,
            },
        )
        text = "".join(
            c.get("text", "")
            for item in result.get("output", [])
            for c in item.get("content", [])
            if c.get("type") == "output_text"
        )
        if (
            result.get("status") not in {"completed", None}
            or result.get("error")
            or not text
        ):
            raise ValueError(
                "文本模型未返回完整文本："
                + str(
                    result.get("error") or result.get("incomplete_details") or "空响应"
                )
            )
        return {
            "message": text,
            "model": model,
            "usage": result.get("usage"),
            "provider": self.config["provider"],
        }

    async def inspect_asset(
        self,
        asset_id: str,
        question: str = "描述图片中的人物、物品、环境、构图和颜色，供视频创作参考。",
    ):
        value = asset(asset_id)
        if not value.get("mime", "").startswith("image/"):
            raise ValueError("读图仅支持图片、角色和物品的图片素材")
        if len(question) > 2000 or not question.strip():
            raise ValueError("请填写不超过 2000 字的读图问题")
        # Resolve only registered media paths, never user/agent supplied filesystem paths.
        with Image.open(media_path(value["path"])) as original:
            image = ImageOps.exif_transpose(original).convert("RGB")
            image.thumbnail((1536, 1536))
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=85)
        uri = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode(
            "ascii"
        )
        model = self.config["vision_model"]
        template = read("vision")
        instruction = render(template, {"question": question})
        result = await self.request(
            "POST",
            "/chat/completions",
            {
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": instruction,
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": question},
                            {"type": "image_url", "image_url": {"url": uri}},
                        ],
                    },
                ],
                "max_tokens": 2048,
                "stream": False,
            },
        )
        choices = result.get("choices", [])
        text = choices[0].get("message", {}).get("content", "") if choices else ""
        if not text or choices[0].get("finish_reason") not in {"stop", None}:
            raise ValueError("视觉模型未返回完整分析结果")
        return {
            "asset_id": asset_id,
            "model": model,
            "description": text,
            "usage": result.get("usage"),
        }
