from __future__ import annotations
import asyncio
import ipaddress
import mimetypes
import socket
import time
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from PIL import Image
from ..core.paths import media_path, new_media_path
from ..core.store import store
from ..media.process import probe
from ..core.network import https_proxy, async_client

MAX_BYTES = 256 * 1024 * 1024
DOWNLOAD_USER_AGENT = (
    "LimeStudio/1.1 (https://github.com/openai/codex; "
    "local desktop media research; contact: local-user)"
)
_dns_cache = {}


async def public_url(url: str):
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("素材链接需要是公开 HTTPS 地址")
    host = parsed.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("素材链接不能指向本机或内部网络")
    addresses = await asyncio.to_thread(
        socket.getaddrinfo, parsed.hostname, parsed.port or 443
    )
    ips = [ipaddress.ip_address(a[4][0]) for a in addresses]
    # Clash-style DNS maps public names to 198.18/15. Verify the real public DNS
    # records through the user's configured proxy instead of allowing that subnet.
    synthetic = ipaddress.ip_network("198.18.0.0/15")
    if ips and all(ip.version == 4 and ip in synthetic for ip in ips) and https_proxy():
        try:
            ipaddress.ip_address(host)
        except ValueError:
            cached = _dns_cache.get(host)
            if cached and cached[0] > time.monotonic():
                ips = cached[1]
            else:
                replies = None
                for resolver in (
                    "https://dns.google/resolve",
                    "https://cloudflare-dns.com/dns-query",
                ):
                    try:
                        async with async_client(
                            timeout=20, headers={"Accept": "application/dns-json"}
                        ) as client:
                            replies = await asyncio.gather(
                                *[
                                    client.get(
                                        resolver, params={"name": host, "type": kind}
                                    )
                                    for kind in ("A", "AAAA")
                                ]
                            )
                        for reply in replies:
                            reply.raise_for_status()
                        break
                    except (httpx.TransportError, httpx.HTTPStatusError):
                        if resolver.endswith("dns-query"):
                            raise
                ips = []
                for reply in replies:
                    reply.raise_for_status()
                    data = reply.json()
                    if data.get("Status") != 0:
                        raise ValueError("素材域名未通过公开 DNS 核验")
                    ips.extend(
                        ipaddress.ip_address(a["data"])
                        for a in data.get("Answer", [])
                        if a.get("type") in {1, 28}
                    )
                _dns_cache[host] = (time.monotonic() + 60, ips)
    if not ips or any(not ip.is_global for ip in ips):
        raise ValueError("素材链接不能指向本机或内部网络")
    return url


async def download(url: str, target: Path):
    for attempt in range(3):
        try:
            return await _download_once(url, target)
        except httpx.TransportError:
            if attempt == 2:
                raise
            await asyncio.sleep(0.75 * (attempt + 1))


async def _download_once(url: str, target: Path):
    partial = target.with_suffix(target.suffix + ".part")
    try:
        async with async_client(
            timeout=120,
            follow_redirects=False,
            headers={"User-Agent": DOWNLOAD_USER_AGENT},
        ) as client:
            for _ in range(6):
                await public_url(url)
                async with client.stream("GET", url) as response:
                    if response.is_redirect:
                        url = str(response.url.join(response.headers["location"]))
                        continue
                    response.raise_for_status()
                    if int(response.headers.get("content-length", "0")) > MAX_BYTES:
                        raise ValueError("素材超过 256 MB")
                    size = 0
                    with partial.open("wb") as file:
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > MAX_BYTES:
                                raise ValueError("素材超过 256 MB")
                            file.write(chunk)
                    if not size:
                        raise ValueError("素材下载为空")
                    partial.replace(target)
                    return response.headers.get("content-type", "").split(";")[0]
        raise ValueError("素材链接重定向过多")
    finally:
        partial.unlink(missing_ok=True)


async def register(relative: str, name: str, kind: str, **metadata):
    path = media_path(relative)
    mime = (
        mimetypes.guess_type(name)[0]
        or mimetypes.guess_type(relative)[0]
        or "application/octet-stream"
    )
    info = {}
    if kind in {"character", "prop", "image"}:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            info = {"width": image.width, "height": image.height}
            mime = Image.MIME.get(image.format, mime)
    elif kind in {"video", "voice", "music"}:
        info = await probe(path)
        required = "video" if kind == "video" else "audio"
        if not any(s["codec_type"] == required for s in info["streams"]):
            raise ValueError("素材的媒体类型不匹配")
    elif kind == "document":
        if path.suffix.lower() not in {".txt", ".md"}:
            raise ValueError("文稿支持 TXT、Markdown")
        metadata["text"] = path.read_text(encoding="utf-8-sig")[:100000]
    thumbnail = None
    if kind in {"image", "character", "prop"}:
        thumb_relative, thumb_path = new_media_path(".jpg")
        with Image.open(path) as image:
            image = image.convert("RGB")
            image.thumbnail((560, 560))
            image.save(thumb_path, quality=82)
        thumbnail = thumb_relative
    if kind == "video":
        from ..media.process import run_process, executable

        thumb_relative, thumb_path = new_media_path(".jpg")
        await run_process(
            [
                executable("ffmpeg"),
                "-v",
                "error",
                "-y",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-vf",
                "scale=480:-2",
                str(thumb_path),
            ],
            60,
        )
        thumbnail = thumb_relative
    return store.save(
        "asset",
        {
            "name": name,
            "kind": kind,
            "path": relative,
            "mime": mime,
            "size": path.stat().st_size,
            "info": info,
            "thumbnail": thumbnail,
            **metadata,
        },
    )


def asset(ident):
    value = store.get("asset", ident)
    # Old workspaces predate stored MIME types; derive them from the actual path.
    if not value.get("mime"):
        value["mime"] = (
            mimetypes.guess_type(value.get("path", ""))[0] or "application/octet-stream"
        )
    if value["kind"] == "character" and not value.get("path"):
        return value
    if not media_path(value["path"]).is_file():
        raise ValueError("素材文件已移动或不存在，请重新导入")
    return value


def data_uri(value):
    import base64

    path = media_path(value["path"])
    if path.stat().st_size > 24 * 1024 * 1024:
        raise ValueError("模型参考素材不能超过 24 MB")
    return f"data:{value['mime']};base64," + base64.b64encode(path.read_bytes()).decode(
        "ascii"
    )


async def collect(url: str, name: str, license: str, **metadata):
    suffix = Path(urlsplit(url).path).suffix.lower()
    if suffix not in {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".mp4",
        ".webm",
        ".mov",
        ".mp3",
        ".wav",
        ".ogg",
    }:
        suffix = ".bin"
    relative, target = new_media_path(suffix)
    mime = await download(url, target)
    kind = (
        "image"
        if mime.startswith("image/")
        else (
            "video"
            if mime.startswith("video/")
            else "voice" if mime.startswith("audio/") else ""
        )
    )
    if not kind:
        target.unlink(missing_ok=True)
        raise ValueError("链接未返回可识别的图片、视频或音频")
    if suffix == ".bin":
        suffix = mimetypes.guess_extension(mime) or ".bin"
        actual = target.with_suffix(suffix)
        target.replace(actual)
        relative = actual.name
    allowed = {
        key: value
        for key, value in metadata.items()
        if key
        in {
            "provider",
            "page_url",
            "license_url",
            "description",
            "search_query",
            "match_score",
            "match_reason",
            "artist",
        }
        and value not in {None, ""}
    }
    # Signed provider download URLs can contain credentials. Save the public
    # landing page as provenance when available, never the signed URL.
    source_url = allowed.get("page_url") or url
    return await register(
        relative,
        name,
        kind,
        source="url",
        source_url=source_url,
        license=license,
        **allowed,
    )


async def search_commons(query: str):
    async with httpx.AsyncClient(timeout=35) as client:
        result = await client.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": query,
                "gsrnamespace": 6,
                "gsrlimit": 10,
                "prop": "imageinfo",
                "iiprop": "url|extmetadata",
                "iiurlwidth": 360,
            },
            headers={
                "User-Agent": DOWNLOAD_USER_AGENT
            },
        )
        result.raise_for_status()
    values = []
    for page in result.json().get("query", {}).get("pages", {}).values():
        info = page.get("imageinfo", [{}])[0]
        ext = info.get("extmetadata", {})
        if info.get("url"):
            values.append(
                {
                    "provider": "wikimedia",
                    "kind": "image",
                    "name": page["title"].removeprefix("File:"),
                    "url": info["url"],
                    "thumbnail": info.get("thumburl", info["url"]),
                    "page_url": info.get("descriptionurl"),
                    "license": ext.get("LicenseShortName", {}).get(
                        "value", "请查看来源页面"
                    ),
                    "license_url": ext.get("LicenseUrl", {}).get("value"),
                    "artist": ext.get("Artist", {}).get("value", ""),
                    "description": ext.get("ImageDescription", {}).get("value", ""),
                }
            )
    return values


async def search_openverse(query: str):
    async with async_client(timeout=35) as client:
        response = await client.get(
            "https://api.openverse.org/v1/images/",
            params={"q": query, "page_size": 10, "mature": "false"},
        )
        response.raise_for_status()
    return [
        {
            "provider": "openverse",
            "kind": "image",
            "name": item["title"],
            "url": item["url"],
            "thumbnail": item["thumbnail"],
            "page_url": item["foreign_landing_url"],
            "license": item.get("attribution")
            or f"CC {item['license'].upper()} {item.get('license_version', '')}",
            "artist": item.get("creator", ""),
            "license_url": item.get("license_url"),
        }
        for item in response.json().get("results", [])
        if item.get("url", "").startswith("https://")
    ]


async def search_openverse_audio(query: str):
    async with async_client(timeout=35) as client:
        response = await client.get(
            "https://api.openverse.org/v1/audio/",
            params={"q": query, "page_size": 12, "mature": "false"},
        )
        response.raise_for_status()
    return [
        {
            "provider": "openverse",
            "kind": "audio",
            "name": item["title"],
            "url": item["url"],
            "thumbnail": item.get("thumbnail"),
            "page_url": item["foreign_landing_url"],
            "license": item.get("attribution")
            or f"CC {item['license'].upper()} {item.get('license_version', '')}",
            "artist": item.get("creator", ""),
            "license_url": item.get("license_url"),
            "duration": item.get("duration"),
            "score": 80,
            "match_reason": "Openverse 音频标题和标签与检索词对应",
        }
        for item in response.json().get("results", [])
        if item.get("url", "").startswith("https://")
    ]
