from __future__ import annotations
import asyncio
import time
import httpx
from ..core.paths import new_media_path
from ..core.store import store
from ..library.service import register
from ..media.process import executable, probe, run_process
from .settings import read_settings

VOICES = [
    {"id": "zh-CN-XiaoxiaoNeural", "name": "晓晓 · 温柔自然"},
    {"id": "zh-CN-YunxiNeural", "name": "云希 · 青年男声"},
    {"id": "zh-CN-XiaoyiNeural", "name": "晓伊 · 清晰活泼"},
    {"id": "zh-CN-YunjianNeural", "name": "云健 · 稳重叙事"},
    {"id": "en-US-JennyNeural", "name": "Jenny · English"},
]


async def clean_voice_audio(source, target):
    raw = await probe(source)
    # TTS providers often leave a long pause between complete sentences.
    # Keep a short natural breath (140 ms) while removing only silences that
    # last at least 380 ms. Word-internal and normal comma pauses remain.
    await run_process(
        [
            executable("ffmpeg"),
            "-v",
            "error",
            "-y",
            "-i",
            str(source),
            "-af",
            (
                "silenceremove="
                "start_periods=1:start_duration=0.05:start_threshold=-50dB:"
                "start_silence=0.02:stop_periods=-1:stop_duration=0.38:"
                "stop_threshold=-50dB:stop_silence=0.14:detection=rms,"
                "alimiter=limit=0.95"
            ),
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "160k",
            str(target),
        ],
        120,
    )
    cleaned = await probe(target)
    raw_duration = float(raw.get("duration") or 0)
    cleaned_duration = float(cleaned.get("duration") or 0)
    return {
        "original_duration": raw_duration,
        "cleaned_duration": cleaned_duration,
        "silence_reduced_seconds": max(0, round(raw_duration - cleaned_duration, 3)),
    }


async def synthesize(text: str, voice: str, name: str):
    settings = read_settings(True)
    relative, path = new_media_path(".mp3")
    partial = path.with_suffix(".part.mp3")
    started = time.time()
    boundaries = []
    try:
        if settings["voice_provider"] == "edge":
            import edge_tts
            from urllib.request import getproxies

            proxies = getproxies()
            proxy = proxies.get("https") or proxies.get("http")
            if proxy and not proxy.startswith(("http://", "https://")):
                proxy = None
            communication = edge_tts.Communicate(
                text, voice, boundary="WordBoundary", proxy=proxy
            )
            async with asyncio.timeout(120):
                with partial.open("wb") as file:
                    async for chunk in communication.stream():
                        if chunk["type"] == "audio":
                            file.write(chunk["data"])
                        elif chunk["type"] in {"WordBoundary", "SentenceBoundary"}:
                            boundaries.append(
                                {
                                    "start": chunk["offset"] / 10_000_000,
                                    "end": (chunk["offset"] + chunk["duration"])
                                    / 10_000_000,
                                    "text": chunk["text"],
                                }
                            )
        else:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    settings["base_url"] + "/audio/speech",
                    headers={"Authorization": "Bearer " + settings["api_key"]},
                    json={
                        "model": settings["voice_model"],
                        "input": text,
                        "voice": voice,
                        "response_format": "mp3",
                    },
                )
                response.raise_for_status()
                partial.write_bytes(response.content)
        if not partial.exists() or partial.stat().st_size < 100:
            raise RuntimeError("配音服务没有返回有效音频")
        timing = await clean_voice_audio(partial, path)
        value = await register(
            relative,
            name,
            "voice",
            source="tts",
            license="合成旁白",
            voice=voice,
            text=text,
            # The silence filter changes offsets. Segment subtitles use the
            # cleaned audio duration instead of stale provider word timings.
            boundaries=[],
            provider_boundaries=boundaries,
            provider=settings["voice_provider"],
            original_duration=timing["original_duration"],
            silence_reduced_seconds=timing["silence_reduced_seconds"],
            silence_policy="remove pauses >=380ms; retain 140ms",
        )
        store.save(
            "trace",
            {
                "kind": "voice",
                "provider": settings["voice_provider"],
                "status": "completed",
                "duration_ms": round((time.time() - started) * 1000),
                "asset_id": value["id"],
            },
        )
        return value
    finally:
        partial.unlink(missing_ok=True)
