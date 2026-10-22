from __future__ import annotations
import re
import tempfile
from pathlib import Path
from ..core.paths import MEDIA, media_path, new_media_path
from ..domain.dialogue import dialogue_window
from ..library.service import asset, register
from .process import run_process, executable, validate_video

CANVAS = {"9:16": (720, 1280), "16:9": (1280, 720), "1:1": (720, 720)}


def ass_time(seconds: float):
    cs = round(max(0, seconds) * 100)
    hours, remainder = divmod(cs, 360000)
    minutes, remainder = divmod(remainder, 6000)
    secs, centis = divmod(remainder, 100)
    return f"{hours}:{minutes:02}:{secs:02}.{centis:02}"


def ass_escape(text: str):
    # Prevent imported text becoming ASS drawing tags or overriding styles.
    return (
        text.replace("\\", "＼")
        .replace("{", "｛")
        .replace("}", "｝")
        .replace("\n", "\\N")
    )


def subtitles(
    scene: dict, audio: dict | None, duration: float, width: int, height: int
):
    narration = scene.get("narration", "").strip()
    spoken = scene.get("dialogue", "").strip() or narration
    if not spoken:
        return ""
    font_size = 34 if width <= 720 else 32
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Default,Microsoft YaHei,{font_size},&H00FFFFFF,&H00FFFFFF,&H0020392C,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,44,44,{round(height * 0.09)},1
[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    events = []
    boundaries = (audio or {}).get("boundaries", []) if narration else []
    if boundaries:
        phrase, start, end = "", None, 0
        for boundary in boundaries:
            if start is None:
                start = boundary["start"]
            phrase += boundary["text"]
            end = min(duration, boundary["end"])
            if len(phrase) >= 16 or phrase.endswith(("。", "！", "？", ".", "!", "?")):
                events.append((start, end, phrase))
                phrase, start = "", None
        if phrase and start is not None:
            events.append((start, end, phrase))
    else:
        phrases = [n for n in re.split(r"(?<=[。！？.!?，,])", spoken) if n.strip()]
        phrases = [p[i : i + 18] for p in phrases for i in range(0, len(p), 18)]
        length = sum(map(len, phrases)) or 1
        window = (
            dialogue_window(scene, duration)
            if scene.get("dialogue", "").strip()
            else None
        )
        window_start, window_end = window or (0, duration)
        available = max(0.1, window_end - window_start)
        cursor = window_start
        for phrase in phrases:
            end = min(window_end, cursor + available * len(phrase) / length)
            events.append((cursor, end, phrase))
            cursor = end
    return header + "".join(
        f"Dialogue: 0,{ass_time(start)},{ass_time(max(start + 0.1, end))},Default,,0,0,0,,{ass_escape(text)}\n"
        for start, end, text in events
        if start < duration
    )


async def export_project(project: dict, on_progress):
    scenes = project.get("scenes", [])
    if not scenes:
        raise ValueError("请先生成分镜")
    width, height = CANVAS[project["aspect"]]
    relative, target = new_media_path(".mp4")
    with tempfile.TemporaryDirectory(prefix="lime-edit-", dir=MEDIA) as temporary:
        work = Path(temporary)
        clips, total = [], 0.0
        for index, scene in enumerate(scenes):
            on_progress(
                f"剪辑镜头 {index + 1}/{len(scenes)} · {scene['title']}",
                index / len(scenes),
            )
            audio = asset(scene["audio_id"]) if scene.get("audio_id") else None
            if project["kind"] == "narration" and scene.get("narration") and not audio:
                raise ValueError(f"镜头「{scene['title']}」还没有旁白，请先制作配音")
            if project["kind"] == "narration" and not scene.get("match_reason", "").strip():
                raise ValueError(f"片段「{scene['title']}」还没有确认文案与素材的匹配依据")
            duration = float(scene["duration"])
            if audio and duration + 0.15 < audio["info"]["duration"]:
                raise ValueError(
                    f"镜头「{scene['title']}」时长小于真实旁白时长，请加长镜头"
                )
            clip = work / f"clip-{index}.mp4"
            video = asset(scene["video_id"]) if scene.get("video_id") else None
            image = (
                asset(scene["first_frame_id"]) if scene.get("first_frame_id") else None
            )
            sound_effect = asset(scene["sfx_id"]) if scene.get("sfx_id") else None
            args = [executable("ffmpeg"), "-v", "error", "-y"]
            loop_visual = False
            if video:
                if scene.get("trim_in", 0) >= video["info"]["duration"]:
                    raise ValueError("剪辑入点超出源视频时长")
                available = video["info"]["duration"] - scene.get("trim_in", 0)
                loop_visual = available + 0.05 < duration
                if loop_visual:
                    # AI providers can return a shorter clip than the narration.
                    # Keyframe videos start and end on the same visual anchor, so
                    # looping preserves motion and avoids a long frozen tail.
                    args += ["-stream_loop", "-1"]
                args += [
                    "-ss",
                    str(scene.get("trim_in", 0)),
                    "-i",
                    str(media_path(video["path"])),
                ]
            elif image and project["kind"] == "narration":
                args += [
                    "-loop",
                    "1",
                    "-framerate",
                    "30",
                    "-i",
                    str(media_path(image["path"])),
                ]
            else:
                raise ValueError(
                    f"镜头「{scene['title']}」缺少{'视频' if project['kind'] == 'drama' else '画面'}"
                )
            has_video_audio = bool(
                video
                and any(s["codec_type"] == "audio" for s in video["info"]["streams"])
            )
            next_input = 1
            audio_filters = []
            if audio:
                args += ["-i", str(media_path(audio["path"]))]
                narration_input = next_input
                next_input += 1
                if project["kind"] == "drama" and has_video_audio:
                    audio_filters.extend(
                        [
                            "[0:a:0]volume=0.55,apad,aresample=48000[videoamb]",
                            f"[{narration_input}:a:0]apad,aresample=48000[voiceover]",
                            "[videoamb][voiceover]amix=inputs=2:duration=longest:normalize=0,"
                            "alimiter=limit=0.95[base]",
                        ]
                    )
                    base_audio = "base"
                else:
                    base_audio = f"{narration_input}:a:0"
            elif has_video_audio:
                base_audio = "0:a:0"
            else:
                args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
                base_audio = f"{next_input}:a:0"
                next_input += 1
            if sound_effect:
                args += ["-i", str(media_path(sound_effect["path"]))]
                sound_effect_input = next_input
            visual = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1,fps=30"
            if video:
                # Extend only by holding the final frame; never cut the narration.
                if not loop_visual:
                    visual += f",tpad=stop_mode=clone:stop_duration={duration}"
            elif image and project["kind"] == "narration":
                # Give still B-roll a restrained continuous camera move. pzoom keeps
                # the value across looped input frames, avoiding per-frame resets.
                visual += (
                    ",zoompan="
                    "z='min(max(zoom,pzoom)+0.00018,1.035)':"
                    "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                    f"d=1:s={width}x{height}:fps=30"
                )
            if project.get("subtitles") and (
                scene.get("dialogue") or scene.get("narration")
            ):
                ass = work / f"caption-{index}.ass"
                ass.write_text(
                    subtitles(scene, audio, duration, width, height),
                    encoding="utf-8-sig",
                )
                escaped = (
                    str(ass).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
                )
                visual += f",subtitles=filename='{escaped}'"
            if sound_effect:
                if base_audio != "base":
                    audio_filters.append(
                        f"[{base_audio}]apad,aresample=48000[base]"
                    )
                offset = min(duration, float(scene.get("sfx_offset", 0)))
                remaining = max(0.1, duration - offset)
                delay = round(offset * 1000)
                volume = float(scene.get("sfx_volume", 0.35))
                audio_filters.append(
                    f"[{sound_effect_input}:a:0]atrim=0:{remaining},"
                    f"adelay={delay}|{delay},volume={volume},apad[sfx]"
                )
                audio_filters.append(
                    "[base][sfx]amix=inputs=2:duration=first:normalize=0,"
                    "alimiter=limit=0.95[a]"
                )
                audio_output = "a"
            elif audio_filters:
                audio_output = "base"
            else:
                audio_output = ""
            if audio_filters:
                audio_args = [
                    "-filter_complex",
                    ";".join(audio_filters),
                    "-map",
                    f"[{audio_output}]",
                ]
            else:
                audio_args = [
                    "-map",
                    base_audio,
                    "-af",
                    "apad,aresample=48000,alimiter=limit=0.95",
                ]
            args += [
                "-map",
                "0:v:0",
                "-vf",
                visual,
                *audio_args,
                "-t",
                str(duration),
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "21",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                "-ar",
                "48000",
                "-ac",
                "2",
                str(clip),
            ]
            await run_process(args, 600)
            clips.append(clip)
            total += duration
        concat = work / "clips.txt"
        concat.write_text(
            "\n".join(
                "file '" + str(c).replace("\\", "/").replace("'", "'\\''") + "'"
                for c in clips
            ),
            encoding="utf-8",
        )
        merged = work / "merged.mp4" if project.get("bgm_id") else target
        await run_process(
            [
                executable("ffmpeg"),
                "-v",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(merged),
            ],
            300,
        )
        if project.get("bgm_id"):
            music = asset(project["bgm_id"])
            volume = float(project.get("bgm_volume", 0.12))
            fade_out = max(0, total - 2)
            background = (
                f"[1:a]atrim=0:{total},volume={volume},"
                f"afade=t=in:st=0:d=1,afade=t=out:st={fade_out}:d=2[bg]"
            )
            if project.get("bgm_ducking", True):
                mixing = (
                    background
                    + ";[bg][0:a]sidechaincompress="
                    "threshold=0.025:ratio=8:attack=20:release=300[ducked];"
                    "[0:a][ducked]amix=inputs=2:duration=first:normalize=0,"
                    "alimiter=limit=0.95[a]"
                )
            else:
                mixing = (
                    background
                    + ";[0:a][bg]amix=inputs=2:duration=first:normalize=0,"
                    "alimiter=limit=0.95[a]"
                )
            await run_process(
                [
                    executable("ffmpeg"),
                    "-v",
                    "error",
                    "-y",
                    "-i",
                    str(merged),
                    "-stream_loop",
                    "-1",
                    "-i",
                    str(media_path(music["path"])),
                    "-filter_complex",
                    mixing,
                    "-map",
                    "0:v",
                    "-map",
                    "[a]",
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-t",
                    str(total),
                    "-movflags",
                    "+faststart",
                    str(target),
                ],
                300,
            )
    info = await validate_video(target, require_audio=True)
    if abs(info["duration"] - total) > 0.6:
        raise RuntimeError("导出时长与时间线不一致")
    result = await register(
        relative,
        project["title"] + ".mp4",
        "video",
        source="export",
        license="项目成片",
        project_id=project["id"],
        project_revision=project["revision"],
        scene_ids=[s["id"] for s in scenes],
    )
    on_progress("成片已通过解码和时长检查", 1)
    return result
