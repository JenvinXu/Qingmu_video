"""Shared timing rules for natural in-video dialogue and its subtitles."""

from __future__ import annotations

import re


_NON_SPOKEN = re.compile(r"[\s，。！？、；：,.!?;:'\"“”‘’（）()《》〈〉—…-]+")


def dialogue_window(scene: dict, duration: float | None = None) -> tuple[float, float] | None:
    """Return a bounded dialogue interval, inferring a natural default when absent."""
    text = scene.get("dialogue", "").strip()
    if not text:
        return None
    length = max(0.1, float(duration if duration is not None else scene.get("duration", 0)))
    spoken_units = max(1, len(_NON_SPOKEN.sub("", text)))
    spoken_seconds = min(max(0.8, spoken_units / 4.2 + 0.35), max(0.1, length - 0.25))
    raw_start = scene.get("dialogue_start")
    raw_end = scene.get("dialogue_end")

    if raw_start is None and raw_end is None:
        start = min(max(0.6, length * 0.15), max(0, length - spoken_seconds - 0.25))
        end = min(length, start + spoken_seconds)
    elif raw_start is None:
        end = min(length, max(0.1, float(raw_end)))
        start = max(0, end - spoken_seconds)
    elif raw_end is None:
        start = min(max(0, float(raw_start)), max(0, length - 0.1))
        end = min(length, start + spoken_seconds)
    else:
        start = min(max(0, float(raw_start)), max(0, length - 0.1))
        end = min(length, max(start + 0.1, float(raw_end)))
    if end <= start:
        start, end = max(0, length - 0.1), length
    return round(start, 2), round(end, 2)


def normalize_dialogue_timing(scene: dict) -> tuple[dict, bool]:
    """Materialize timing so preview, export and regeneration use one source of truth."""
    updated = dict(scene)
    window = dialogue_window(updated)
    start, end = window if window is not None else (None, None)
    changed = (
        updated.get("dialogue_start") != start
        or updated.get("dialogue_end") != end
    )
    updated["dialogue_start"] = start
    updated["dialogue_end"] = end
    return updated, changed
