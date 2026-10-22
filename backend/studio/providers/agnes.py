from __future__ import annotations
import asyncio
import base64
import json
import hashlib
import time
from urllib.parse import urlsplit
import httpx
from PIL import Image
from .settings import read_settings, safe_error
from ..core.store import store
from ..core.paths import new_media_path
from ..library.service import download, register, data_uri
from ..core.network import async_client
from .capabilities import video_capabilities
from ..domain.timing import MIN_DRAMA_SCENE_SECONDS, MAX_DRAMA_SCENE_SECONDS


class Agnes:
    def __init__(self, *, image_model=None, video_model=None, video_size=None):
        self.settings = read_settings(True)
        for key, value in (
            ("image_model", image_model),
            ("video_model", video_model),
            ("video_size", video_size),
        ):
            if value:
                self.settings[key] = value
        self.base = self.settings["base_url"].rstrip("/")

    def headers(self, credential="media"):
        field = "video_api_key" if credential == "video" else "api_key"
        key = self.settings.get(field)
        if not key:
            label = "视频模型" if credential == "video" else "媒体模型"
            raise ValueError(f"请先在设置中保存{label} API Key")
        return {"Authorization": "Bearer " + key}

    async def request(
        self,
        method,
        endpoint,
        payload=None,
        *,
        params=None,
        trace=True,
        credential="media",
    ):
        started = time.time()
        url = endpoint if endpoint.startswith("https://") else self.base + endpoint
        record = {
            "kind": "model",
            "endpoint": url.split("?")[0],
            "method": method,
            "model": (payload or {}).get("model", (params or {}).get("model_name")),
            "started_at": started,
        }
        try:
            async with async_client(
                target_url=self.base, timeout=httpx.Timeout(180, connect=20)
            ) as client:
                response = await client.request(
                    method,
                    url,
                    json=payload,
                    params=params,
                    headers=self.headers(credential),
                )
                if response.is_error:
                    raise RuntimeError(
                        f"模型接口 HTTP {response.status_code}: {response.text[:1600]}"
                    )
                result = response.json()
                record.update(
                    status="completed",
                    http_status=response.status_code,
                    request_id=response.headers.get("x-request-id") or result.get("id"),
                    usage=result.get("usage"),
                    provider_video_id=result.get("video_id"),
                )
                return result
        except Exception as error:
            record.update(status="failed", error=safe_error(error))
            raise
        finally:
            record["duration_ms"] = round((time.time() - started) * 1000)
            if trace:
                store.save("trace", record)

    async def test(self):
        result = await self.request(
            "POST",
            "/responses",
            {
                "model": self.settings["text_model"],
                "input": "只回复：连接成功",
                "max_output_tokens": 1024,
            },
        )
        if result.get("status") not in {"completed", None} or result.get("error"):
            raise ValueError(
                "文本模型返回未完成状态："
                + str(result.get("error") or result.get("incomplete_details"))
            )
        text = "".join(
            c.get("text", "")
            for i in result.get("output", [])
            for c in i.get("content", [])
            if c.get("type") == "output_text"
        )
        if not text:
            raise ValueError("模型未返回有效文本")
        return {
            "message": text,
            "usage": result.get("usage"),
            "model": self.settings["text_model"],
        }

    async def test_video(self):
        result = await self.request("GET", "/models", credential="video")
        models = [item.get("id") for item in result.get("data", [])]
        model = self.settings["video_model"]
        if models and model not in models:
            raise ValueError(f"视频连接成功，但模型列表中未找到 {model}")
        return {"message": "视频连接成功", "model": model}

    async def image(self, prompt: str, aspect: str, references: list[dict], name: str):
        body = {
            "model": self.settings["image_model"],
            "prompt": prompt,
            "size": "1K",
            "ratio": aspect,
            "extra_body": {"response_format": "url"},
        }
        if references:
            if len(references) > 30:
                raise ValueError("首帧图片最多接受 30 张参考图片")
            body["extra_body"]["image"] = [data_uri(a) for a in references]
        signature = hashlib.sha256(
            json.dumps({"base": self.base, "body": body}, sort_keys=True).encode()
        ).hexdigest()
        try:
            cached = store.get("image_result", signature)
            result = cached["result"]
        except KeyError:
            result = None
            for attempt, delay in enumerate((10, 20, 35, 0), 1):
                try:
                    result = await self.request("POST", "/images/generations", body)
                    break
                except RuntimeError as error:
                    message = str(error)
                    retryable = "HTTP 503" in message and any(
                        marker in message
                        for marker in ("队列已满", "queue_unavailable", "queue is full")
                    )
                    if not retryable or attempt == 4:
                        raise
                    await asyncio.sleep(delay)
            # Persist the provider result before downloading so a network retry
            # reuses the generated image rather than making another paid request.
            store.save("image_result", {"id": signature, "result": result})
        items = result.get("data", [])
        if not items:
            raise RuntimeError(
                "图像模型未返回图片：" + json.dumps(result, ensure_ascii=False)[:800]
            )
        item = items[0]
        relative, target = new_media_path(".png")
        url = item.get("url")
        if url:
            await download(url, target)
        elif item.get("b64_json"):
            target.write_bytes(base64.b64decode(item["b64_json"]))
        else:
            raise RuntimeError("图像模型结果缺少 URL 或 Base64")
        # Convert to a known image format, independent of provider file extensions.
        with Image.open(target) as image:
            image.convert("RGB").save(target, "PNG")
        value = await register(
            relative,
            name,
            "image",
            source="generated",
            source_url=url,
            license="AI 生成",
            model=self.settings["image_model"],
            prompt=prompt,
            request_id=result.get("id"),
            reference_ids=[a["id"] for a in references],
        )
        store.delete("image_result", signature)
        return value

    async def video(
        self,
        prompt: str,
        aspect: str,
        seconds: int,
        first_frame: dict | None,
        references: list[dict],
        name: str,
        on_progress,
        existing=None,
        on_created=None,
    ):
        model = self.settings["video_model"]
        if (
            not isinstance(seconds, int)
            or not MIN_DRAMA_SCENE_SECONDS <= seconds <= MAX_DRAMA_SCENE_SECONDS
        ):
            raise ValueError(
                f"视频时长需要是 {MIN_DRAMA_SCENE_SECONDS}–{MAX_DRAMA_SCENE_SECONDS} 秒整数"
            )
        if model.endswith("flash") and self.settings["video_size"] != "720P":
            raise ValueError("Flash 视频模型仅支持 720P，请调整该分镜画质")
        body = {
            "model": model,
            "prompt": prompt,
            "seconds": str(seconds),
            "mode": "ti2vid" if model == "agnes-video-v2.0" else "text",
            "size": self.settings["video_size"],
            "aspect_ratio": aspect,
        }
        images = [a for a in references if a.get("mime", "").startswith("image/")]
        audios = [a for a in references if a["kind"] in {"voice", "music"}]
        videos = [a for a in references if a["kind"] == "video"]
        caps = video_capabilities(model)
        all_images = ([first_frame] if first_frame else []) + [
            a for a in images if not first_frame or a["id"] != first_frame["id"]
        ]
        for group, key, label in (
            (all_images, "images", "图片"),
            (audios, "audios", "音色"),
            (videos, "videos", "视频"),
        ):
            if len(group) > caps[key]:
                raise ValueError(
                    f"{model} 最多支持 {caps[key]} 个{label}参考，当前选择 {len(group)} 个；请减少参考或切换支持的模型，软件不会丢弃素材"
                )
        if self.settings["video_size"] not in caps["sizes"]:
            raise ValueError(
                f"{model} 不支持 {self.settings['video_size']}，请调整画质"
            )
        if images or audios or videos or (first_frame and not first_frame.get("source_url") and not caps["public_urls"]):
            body["mode"] = (
                "multi_reference" if model == "agnes-video-v2.0" else "reference"
            )
            reference_labels = []
            for group, key in (
                (all_images, "images"),
                (audios, "audios"),
                (videos, "videos"),
            ):
                urls = []
                for index, value in enumerate(group, 1):
                    source = value.get("source_url")
                    if not source and not caps["public_urls"] and key in {"images", "audios"}:
                        source = data_uri(value)
                    if not source:
                        raise ValueError(
                            f"参考素材「{value['name']}」需要公开链接；当前服务无法直接读取本地上传文件，请使用可访问的素材链接或配置支持本地参考的服务"
                        )
                    urls.append(
                        source
                        if key != "videos"
                        else {"url": source}
                    )
                    marker = {
                        "images": "Picture",
                        "audios": "Audio",
                        "videos": "Video",
                    }[key]
                    label = (
                        "首帧构图"
                        if first_frame and value["id"] == first_frame["id"]
                        else value["name"]
                    )
                    reference_labels.append(f"<{marker} {index}>：{label}")
                if urls:
                    body[key] = urls
            body["prompt"] = prompt + "\n参考素材对应：\n" + "\n".join(reference_labels)
        elif first_frame:
            if not first_frame.get("source_url"):
                raise ValueError("首帧需要可公开访问的图片链接；请生成首帧或从链接导入")
            if model == "agnes-video-v2.0":
                body.update(
                    mode="keyframes",
                    image=[first_frame["source_url"], first_frame["source_url"]],
                )
            else:
                body.update(mode="keyframe", first_frame=first_frame["source_url"])
        if existing:
            video_id = existing["video_id"]
            model = existing["model"]
        else:
            result = None
            for attempt, delay in enumerate((10, 20, 35, 0), 1):
                try:
                    result = await self.request(
                        "POST", "/videos", body, credential="video"
                    )
                    break
                except RuntimeError as error:
                    message = str(error)
                    retryable = (
                        "HTTP 503" in message
                        and "video_queue_unavailable" in message
                    )
                    if not retryable or attempt == 4:
                        raise
                    on_progress(
                        f"视频队列暂满，{delay} 秒后重试提交（{attempt}/3）；首帧与已完成素材保留"
                    )
                    await asyncio.sleep(delay)
            video_id = result.get("video_id")
            if not video_id:
                raise RuntimeError("视频模型未返回 video_id：" + str(result)[:1200])
            if on_created:
                on_created(
                    {"video_id": video_id, "model": model, "created_at": time.time()}
                )
        host = urlsplit(self.base)
        query_url = f"{host.scheme}://{host.netloc}/agnesapi"
        deadline = time.monotonic() + 1500
        network_failures = 0
        while time.monotonic() < deadline:
            try:
                status = await self.request(
                    "GET",
                    query_url,
                    params={"video_id": video_id, "model_name": model},
                    trace=False,
                    credential="video",
                )
                network_failures = 0
            except (httpx.TransportError, RuntimeError):
                network_failures += 1
                if network_failures > 6:
                    raise
                on_progress(
                    f"网络暂时不可用，继续查询原视频任务（{network_failures}/6）"
                )
                await asyncio.sleep(min(30, 2**network_failures))
                continue
            on_progress(
                f"视频模型 {status.get('status', '处理中')} · {status.get('progress', 0)}%"
            )
            if status.get("status") == "failed":
                raise RuntimeError("视频生成失败：" + str(status.get("error")))
            if status.get("status") == "completed":
                url = status.get("url") or (status.get("metadata") or {}).get("url")
                if not url:
                    raise RuntimeError(
                        "已完成的视频任务缺少 URL："
                        + json.dumps(status, ensure_ascii=False)[:1200]
                    )
                relative, target = new_media_path(".mp4")
                await download(url, target)
                value = await register(
                    relative,
                    name,
                    "video",
                    source="generated",
                    source_url=url,
                    license="AI 生成",
                    model=model,
                    prompt=prompt,
                    provider_video_id=video_id,
                    reference_ids=[a["id"] for a in references],
                )
                store.save(
                    "trace",
                    {
                        "kind": "video_result",
                        "model": model,
                        "status": "completed",
                        "provider_video_id": video_id,
                        "asset_id": value["id"],
                        "info": value["info"],
                    },
                )
                return value
            await asyncio.sleep(8)
        raise TimeoutError("视频任务查询超过 25 分钟。重新制作会继续查询同一个任务。")
