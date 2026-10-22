"""Canonical short-drama script markers shared by planning and storyboard validation."""

from __future__ import annotations

import re
from .timing import MAX_DRAMA_SCENE_SECONDS


MARKER = re.compile(
    r"(?m)^[ \t]*[（(][ \t]*(\d+)[ \t]*[-–—~至][ \t]*(\d+)[ \t]*秒?[ \t]*[）)]"
    r"[ \t]*分镜[ \t]*0*(\d+)[ \t]*[：:][ \t]*"
)


def drama_segments(script: str, *, required: bool = False) -> list[dict]:
    """Parse ``（0-5秒）分镜1：...`` blocks and reject ambiguous timelines."""

    matches = list(MARKER.finditer(script))
    if not matches:
        if required:
            raise ValueError("视频文案需要使用“（0-5秒）分镜1：内容”的连续分镜格式")
        return []
    if script[: matches[0].start()].strip():
        raise ValueError("第一个分镜标记前不能有未归属的文案")
    if len(matches) > 40:
        raise ValueError("视频文案最多包含 40 个分镜")

    segments = []
    previous_end = 0
    for index, match in enumerate(matches, start=1):
        start, end, number = (int(value) for value in match.groups())
        text_end = matches[index].start() if index < len(matches) else len(script)
        text = script[match.end() : text_end].strip()
        if number != index:
            raise ValueError(f"分镜编号需要从 1 连续排列，当前应为分镜 {index}")
        if start != previous_end:
            raise ValueError(
                f"分镜 {index} 应从 {previous_end} 秒开始，时间段不能重叠或留空"
            )
        if end <= start or end - start > MAX_DRAMA_SCENE_SECONDS:
            raise ValueError(
                f"分镜 {index} 的结束时间需要大于开始时间，单镜最长 {MAX_DRAMA_SCENE_SECONDS} 秒"
            )
        if not text:
            raise ValueError(f"分镜 {index} 缺少文案内容")
        segments.append(
            {
                "number": number,
                "start": start,
                "end": end,
                "duration": end - start,
                "text": text,
            }
        )
        previous_end = end
    return segments
