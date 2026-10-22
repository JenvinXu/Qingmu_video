"""Search licensed media providers and normalize their results."""

from __future__ import annotations

import asyncio
import html
import os
import re
from pathlib import PurePosixPath
from urllib.parse import quote

from ..core.network import async_client

MAX_BYTES = 256 * 1024 * 1024
USER_AGENT = (
    "LimeStudio/1.1 (https://github.com/openai/codex; "
    "local desktop media research; contact: local-user)"
)
VIDEO_SUFFIXES = {".mp4", ".webm", ".ogv", ".mov"}


def _text(value) -> str:
    if isinstance(value, list):
        value = " ".join(str(item) for item in value)
    value = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    return re.sub(r"\s+", " ", value).strip()


def _number(value, default=0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _terms(value: str) -> set[str]:
    lowered = value.casefold()
    terms = set(re.findall(r"[a-z0-9][a-z0-9+.-]*", lowered))
    for group in re.findall(r"[\u3400-\u9fff]+", lowered):
        terms.add(group)
        if len(group) > 1:
            terms.update(group[index : index + 2] for index in range(len(group) - 1))
    return {term for term in terms if len(term) > 1 or term.isdigit()}


def rank_candidate(query: str, candidate: dict) -> dict:
    """Metadata relevance score used before downloading a large media file."""
    name = str(candidate.get("name") or "").casefold()
    haystack = " ".join(
        str(candidate.get(key) or "")
        for key in ("name", "description", "artist", "provider")
    ).casefold()
    wanted = _terms(query)
    found = {term for term in wanted if term in haystack}
    title_found = {term for term in wanted if term in name}
    coverage = len(found) / max(1, len(wanted))
    title_coverage = len(title_found) / max(1, len(wanted))
    exact = query.casefold().strip() in name
    score = round(
        10
        + coverage * 36
        + title_coverage * 34
        + (10 if exact else 0)
        + (5 if coverage == 1 and title_coverage > 0 else 0)
    )
    if candidate.get("kind") == "video":
        score += 5
    if candidate.get("duration") and candidate["duration"] >= 4:
        score += 3
    score = max(0, min(100, score))
    candidate["score"] = score
    candidate["matched_terms"] = sorted(found)
    candidate["title_matched_terms"] = sorted(title_found)
    candidate["match_reason"] = (
        f"标题命中 {len(title_found)}/{len(wanted)}、元数据命中 {len(found)}/{len(wanted)} 个检索要点"
        + (
            f"：{'、'.join(sorted(title_found)[:6])}"
            if title_found
            else "；标题未命中，禁止自动采用"
        )
    )
    return candidate


def _candidate(provider: str, **value):
    return {
        "provider": provider,
        "kind": value.pop("kind", "video"),
        "name": _text(value.pop("name", "网络视频"))[:240],
        "description": _text(value.pop("description", ""))[:4000],
        "artist": _text(value.pop("artist", ""))[:500],
        **value,
    }


async def search_commons(query: str, limit=12):
    async with async_client(
        timeout=40, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    ) as client:
        result = await client.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": f"{query} filetype:video",
                "gsrnamespace": 6,
                "gsrlimit": min(30, limit * 2),
                "prop": "imageinfo",
                "iiprop": "url|mime|size|extmetadata",
                "iiurlwidth": 480,
            },
        )
        result.raise_for_status()
    values = []
    for page in result.json().get("query", {}).get("pages", {}).values():
        info = page.get("imageinfo", [{}])[0]
        mime = str(info.get("mime", ""))
        size = int(info.get("size") or 0)
        if not mime.startswith("video/") or not 0 < size <= MAX_BYTES:
            continue
        ext = info.get("extmetadata", {})
        values.append(
            _candidate(
                "wikimedia",
                name=page.get("title", "").removeprefix("File:"),
                url=info.get("url"),
                thumbnail=info.get("thumburl") or info.get("url"),
                page_url=info.get("descriptionurl"),
                license=ext.get("LicenseShortName", {}).get(
                    "value", "请查看 Wikimedia Commons 来源页"
                ),
                license_url=ext.get("LicenseUrl", {}).get("value"),
                artist=ext.get("Artist", {}).get("value", ""),
                description=ext.get("ImageDescription", {}).get("value", ""),
                size=size,
                width=info.get("width"),
                height=info.get("height"),
            )
        )
    return values[:limit]


def _archive_file(files: list[dict]):
    choices = []
    for item in files:
        name = str(item.get("name", ""))
        suffix = PurePosixPath(name).suffix.lower()
        if suffix not in VIDEO_SUFFIXES or any(
            word in name.casefold() for word in ("thumb", "sample", "trailer")
        ):
            continue
        size = int(_number(item.get("size")))
        if not 0 < size <= MAX_BYTES:
            continue
        width, height = int(_number(item.get("width"))), int(
            _number(item.get("height"))
        )
        fmt = str(item.get("format", "")).casefold()
        priority = (
            0 if "512kb" in fmt else 1 if "mpeg4" in fmt or suffix == ".mp4" else 2
        )
        choices.append((priority, -max(width, height), size, item))
    return min(choices, default=(None, None, None, None))[3]


async def search_archive(query: str, limit=8):
    search = (
        f"({query}) AND mediatype:movies AND "
        "(licenseurl:*creativecommons* OR licenseurl:*publicdomain*)"
    )
    async with async_client(
        timeout=45, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    ) as client:
        response = await client.get(
            "https://archive.org/advancedsearch.php",
            params={
                "q": search,
                "fl[]": [
                    "identifier",
                    "title",
                    "description",
                    "licenseurl",
                    "creator",
                ],
                "rows": limit,
                "page": 1,
                "output": "json",
            },
        )
        response.raise_for_status()
        docs = response.json().get("response", {}).get("docs", [])

        async def resolve(doc):
            ident = doc.get("identifier")
            if not ident:
                return None
            meta = await client.get(f"https://archive.org/metadata/{quote(str(ident))}")
            meta.raise_for_status()
            payload = meta.json()
            selected = _archive_file(payload.get("files", []))
            if not selected:
                return None
            filename = selected["name"]
            metadata = payload.get("metadata", {})
            license_url = metadata.get("licenseurl") or doc.get("licenseurl") or ""
            if isinstance(license_url, list):
                license_url = license_url[0] if license_url else ""
            restricted = str(license_url).casefold()
            if any(value in restricted for value in ("by-nc", "by-nd")):
                return None
            return _candidate(
                "internet_archive",
                name=metadata.get("title") or doc.get("title") or filename,
                url=f"https://archive.org/download/{quote(str(ident))}/{quote(filename)}",
                thumbnail=f"https://archive.org/services/img/{quote(str(ident))}",
                page_url=f"https://archive.org/details/{quote(str(ident))}",
                license=license_url or "请查看 Internet Archive 来源页",
                license_url=license_url or None,
                artist=metadata.get("creator") or doc.get("creator") or "",
                description=metadata.get("description")
                or doc.get("description")
                or "",
                size=int(_number(selected.get("size"))),
                width=int(_number(selected.get("width"))) or None,
                height=int(_number(selected.get("height"))) or None,
                duration=_number(selected.get("length")) or None,
            )

        resolved = await asyncio.gather(
            *(resolve(doc) for doc in docs), return_exceptions=True
        )
    return [item for item in resolved if isinstance(item, dict)]


async def search_nasa(query: str, limit=8):
    async with async_client(
        timeout=45, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    ) as client:
        response = await client.get(
            "https://images-api.nasa.gov/search",
            params={"q": query, "media_type": "video", "page_size": limit},
        )
        response.raise_for_status()
        items = response.json().get("collection", {}).get("items", [])

        async def resolve(item):
            data = (item.get("data") or [{}])[0]
            manifest_url = item.get("href")
            if not manifest_url:
                return None
            manifest = await client.get(manifest_url)
            manifest.raise_for_status()
            urls = manifest.json()
            videos = [
                url
                for url in urls
                if isinstance(url, str)
                and PurePosixPath(url.split("?", 1)[0]).suffix.lower() in VIDEO_SUFFIXES
            ]
            if not videos:
                return None
            videos.sort(
                key=lambda url: (
                    0 if "~small" in url else 1 if "~medium" in url else 2,
                    len(url),
                )
            )
            video_url = videos[0].replace(
                "http://images-assets.nasa.gov/", "https://images-assets.nasa.gov/"
            )
            nasa_id = data.get("nasa_id", "")
            preview = next(
                (
                    link.get("href")
                    for link in item.get("links", [])
                    if link.get("render") == "image"
                ),
                "",
            )
            return _candidate(
                "nasa",
                name=data.get("title") or nasa_id,
                url=video_url,
                thumbnail=preview,
                page_url=f"https://images.nasa.gov/details/{quote(str(nasa_id))}",
                license="NASA media usage guidelines; verify listed credits and third-party rights",
                license_url="https://www.nasa.gov/nasa-brand-center/images-and-media/",
                artist=data.get("photographer") or data.get("center") or "NASA",
                description=data.get("description") or data.get("description_508") or "",
            )

        resolved = await asyncio.gather(
            *(resolve(item) for item in items), return_exceptions=True
        )
    return [item for item in resolved if isinstance(item, dict)]


async def search_pexels(query: str, limit=12):
    key = os.getenv("PEXELS_API_KEY", "").strip()
    if not key:
        return []
    async with async_client(
        timeout=40,
        headers={"Authorization": key, "User-Agent": USER_AGENT},
    ) as client:
        response = await client.get(
            "https://api.pexels.com/v1/videos/search",
            params={"query": query, "per_page": limit, "orientation": "portrait"},
        )
        response.raise_for_status()
    values = []
    for item in response.json().get("videos", []):
        renditions = [
            video
            for video in item.get("video_files", [])
            if video.get("link") and int(video.get("width") or 0) <= 1920
        ]
        if not renditions:
            continue
        rendition = max(renditions, key=lambda value: int(value.get("height") or 0))
        values.append(
            _candidate(
                "pexels",
                name=f"Pexels video {item.get('id')}",
                url=rendition["link"],
                thumbnail=item.get("image"),
                page_url=item.get("url"),
                license="Pexels License",
                license_url="https://www.pexels.com/license/",
                artist=(item.get("user") or {}).get("name", ""),
                description=query,
                duration=item.get("duration"),
                width=rendition.get("width"),
                height=rendition.get("height"),
            )
        )
    return values


async def search_pixabay(query: str, limit=20):
    key = os.getenv("PIXABAY_API_KEY", "").strip()
    if not key:
        return []
    async with async_client(timeout=40, headers={"User-Agent": USER_AGENT}) as client:
        response = await client.get(
            "https://pixabay.com/api/videos/",
            params={
                "key": key,
                "q": query,
                "per_page": max(3, limit),
                "safesearch": "true",
            },
        )
        response.raise_for_status()
    values = []
    for item in response.json().get("hits", []):
        renditions = [
            value
            for value in (item.get("videos") or {}).values()
            if value.get("url") and int(value.get("size") or 0) <= MAX_BYTES
        ]
        if not renditions:
            continue
        rendition = max(renditions, key=lambda value: int(value.get("height") or 0))
        values.append(
            _candidate(
                "pixabay",
                name=f"Pixabay video {item.get('id')}",
                url=rendition["url"],
                thumbnail=rendition.get("thumbnail"),
                page_url=item.get("pageURL"),
                license="Pixabay Content License",
                license_url="https://pixabay.com/service/license-summary/",
                artist=item.get("user", ""),
                description=query,
                duration=item.get("duration"),
                width=rendition.get("width"),
                height=rendition.get("height"),
                size=rendition.get("size"),
            )
        )
    return values


async def search_coverr(query: str, limit=12):
    key = os.getenv("COVERR_API_KEY", "").strip()
    if not key:
        return []
    async with async_client(
        timeout=40,
        headers={"Authorization": f"Bearer {key}", "User-Agent": USER_AGENT},
    ) as client:
        response = await client.get(
            "https://api.coverr.co/videos",
            params={
                "query": query,
                "page_size": limit,
                "urls": "true",
                "sort": "popular",
                "filter": "is_vertical:true",
            },
        )
        response.raise_for_status()
    values = []
    for item in response.json().get("hits", []):
        url = (item.get("urls") or {}).get("mp4_download")
        if not url:
            continue
        creator = item.get("creator") or item.get("author") or {}
        if isinstance(creator, dict):
            creator = creator.get("name") or creator.get("username") or ""
        values.append(
            _candidate(
                "coverr",
                name=item.get("title") or f"Coverr video {item.get('id')}",
                url=url,
                thumbnail=item.get("poster") or item.get("thumbnail"),
                page_url=item.get("canonical_url") or item.get("url"),
                license="Coverr License; attribution required for API videos",
                license_url="https://coverr.co/license",
                artist=creator,
                description=" ".join(item.get("tags") or []),
                duration=_number(item.get("duration")) or None,
                width=item.get("max_width"),
                height=item.get("max_height"),
            )
        )
    return values


VIDEO_PROVIDERS = {
    "wikimedia": search_commons,
    "internet_archive": search_archive,
    "nasa": search_nasa,
    "pexels": search_pexels,
    "pixabay": search_pixabay,
    "coverr": search_coverr,
}


async def search_videos(query: str, providers: set[str] | None = None, limit=30):
    selected = [
        (name, function)
        for name, function in VIDEO_PROVIDERS.items()
        if providers is None or name in providers
    ]
    results = await asyncio.gather(
        *(function(query) for _, function in selected), return_exceptions=True
    )
    candidates = []
    for (provider, _), result in zip(selected, results, strict=True):
        if isinstance(result, Exception):
            continue
        for item in result:
            item.setdefault("provider", provider)
            candidates.append(rank_candidate(query, item))
    unique = {}
    for item in candidates:
        key = item.get("page_url") or item.get("url")
        previous = unique.get(key)
        if not previous or item["score"] > previous["score"]:
            unique[key] = item
    return sorted(
        unique.values(), key=lambda item: (-item["score"], item["provider"], item["name"])
    )[:limit]


def source_status():
    return [
        {
            "id": "wikimedia",
            "name": "Wikimedia Commons",
            "description": "开放许可视频与图片，无需密钥",
            "ready": True,
            "url": "https://commons.wikimedia.org",
        },
        {
            "id": "internet_archive",
            "name": "Internet Archive",
            "description": "Creative Commons 与公版影片，无需密钥",
            "ready": True,
            "url": "https://archive.org",
        },
        {
            "id": "nasa",
            "name": "NASA Image and Video Library",
            "description": "科技与航天视频，无需密钥；使用前核对署名",
            "ready": True,
            "url": "https://images.nasa.gov",
        },
        {
            "id": "pexels",
            "name": "Pexels Videos",
            "description": "高质量库存视频，需要免费 API Key",
            "ready": bool(os.getenv("PEXELS_API_KEY")),
            "url": "https://www.pexels.com/api/",
        },
        {
            "id": "pixabay",
            "name": "Pixabay Videos",
            "description": "库存视频，需要免费 API Key",
            "ready": bool(os.getenv("PIXABAY_API_KEY")),
            "url": "https://pixabay.com/api/docs/",
        },
        {
            "id": "coverr",
            "name": "Coverr",
            "description": "库存视频和向量检索，需要 API Key",
            "ready": bool(os.getenv("COVERR_API_KEY")),
            "url": "https://coverr.co/api/docs/videos",
        },
    ]
