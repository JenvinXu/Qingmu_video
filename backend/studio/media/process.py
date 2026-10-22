from __future__ import annotations
import asyncio
import json
import os
import shutil
from pathlib import Path


def executable(name: str) -> str:
    if location := os.environ.get("LIME_" + name.upper()):
        if Path(location).is_file():
            return location
    if location := shutil.which(name):
        return location
    winget = (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    )
    for location in winget.glob(f"Gyan.FFmpeg.Shared*/**/bin/{name}.exe"):
        return str(location)
    raise RuntimeError(f"{name} 未就绪，请重新安装完整发行版")


async def run_process(argv: list[str], timeout=300):
    kwargs = {"creationflags": 0x08000000} if os.name == "nt" else {}
    process = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, **kwargs
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    if process.returncode:
        raise RuntimeError(stderr.decode("utf-8", errors="replace")[-2400:])
    return stdout


async def probe(path: Path):
    output = await run_process(
        [
            executable("ffprobe"),
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ],
        30,
    )
    info = json.loads(output)
    streams = info.get("streams", [])
    duration = float(info.get("format", {}).get("duration", 0))
    return {
        "duration": duration,
        "streams": [
            {
                k: s.get(k)
                for k in (
                    "codec_type",
                    "codec_name",
                    "width",
                    "height",
                    "sample_rate",
                    "channels",
                )
            }
            for s in streams
        ],
        "size": path.stat().st_size,
    }


async def validate_video(path: Path, require_audio=False):
    info = await probe(path)
    types = {s["codec_type"] for s in info["streams"]}
    if (
        "video" not in types
        or info["duration"] <= 0
        or (require_audio and "audio" not in types)
    ):
        raise RuntimeError("输出媒体缺少有效视频或音轨")
    await run_process(
        [
            executable("ffmpeg"),
            "-v",
            "error",
            "-xerror",
            "-i",
            str(path),
            "-t",
            "2",
            "-f",
            "null",
            "-",
        ],
        60,
    )
    return info
