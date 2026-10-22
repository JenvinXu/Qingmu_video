"""Collect passed desktop evidence and local samples without exporting credentials."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--job", required=True)
args = parser.parse_args()
data = Path(os.environ["APPDATA"]) / "LimeStudio/workspace"
out = root / "data/reports"
report_path = data / "reports" / (args.job + ".json")
report = json.loads(report_path.read_text(encoding="utf-8"))
assert report["status"] == "passed", "Desktop acceptance has not passed"
desktop = json.loads((out / "desktop-test.json").read_text(encoding="utf-8"))
assert desktop["status"] == "passed" and not desktop["page_errors"]
ui = json.loads((out / "ui-test.json").read_text(encoding="utf-8"))
assert ui["status"] == "passed"
refined = json.loads((out / "refined-acceptance.json").read_text(encoding="utf-8"))
assert refined["status"] in {"passed", "failed"}, "Live refinement check is unfinished"
narration_ui = json.loads((out / "narration-ui-test.json").read_text(encoding="utf-8"))
narration_live = json.loads(
    (out / "narration-step-acceptance.json").read_text(encoding="utf-8")
)
assert narration_ui["status"] == "passed" and narration_live["status"] == "passed"
cold = json.loads((out / "cold-start.json").read_text(encoding="utf-8-sig"))
assert cold["status"] == "passed" and cold["window_visible"]
qianfan = json.loads(
    (out / "qianfan-native-acceptance.json").read_text(encoding="utf-8")
)
qianfan_ui = json.loads((out / "qianfan-ui-test.json").read_text(encoding="utf-8"))
qianfan_mcp = json.loads((out / "qianfan-mcp-test.json").read_text(encoding="utf-8"))
assert qianfan["status"] == qianfan_ui["status"] == qianfan_mcp["status"] == "passed"
drama_input = json.loads(
    (out / "drama-input-native-acceptance.json").read_text(encoding="utf-8")
)
drama_input_ui = json.loads(
    (out / "drama-input-native-ui-test.json").read_text(encoding="utf-8")
)
assert drama_input["status"] == drama_input_ui["status"] == "passed"
assert not drama_input_ui["page_errors"]
drama_capacity = json.loads(
    (out / "drama-capacity-test.json").read_text(encoding="utf-8")
)
package_check = json.loads((out / "package-check.json").read_text(encoding="utf-8"))
assert drama_capacity["status"] == package_check["status"] == "passed"
skills_ui = json.loads(
    (out / "skills-ui-acceptance.json").read_text(encoding="utf-8")
)
skills_live = json.loads(
    (out / "drama-skills-acceptance.json").read_text(encoding="utf-8")
)
skills_launch = json.loads(
    (out / "skills-final-launch.json").read_text(encoding="utf-8-sig")
)
assert skills_ui["status"] == skills_live["status"] == skills_launch["status"] == "passed"
assert skills_launch["window_visible"] and not skills_launch["debugging_port_enabled"]
dialogue_agent = json.loads(
    (out / "drama-natural-dialogue-agent.json").read_text(encoding="utf-8")
)
dialogue_ui = json.loads(
    (out / "drama-natural-dialogue-ui.json").read_text(encoding="utf-8")
)
dialogue_export = json.loads(
    (out / "drama-natural-dialogue-export.json").read_text(encoding="utf-8")
)
dialogue_launch = json.loads(
    (out / "drama-natural-dialogue-final-launch.json").read_text(encoding="utf-8")
)
subtitle_ui = json.loads(
    (out / "subtitle-timing-ui.json").read_text(encoding="utf-8")
)
subtitle_plan = json.loads(
    (out / "drama-subtitle-timing-plan.json").read_text(encoding="utf-8")
)
subtitle_visual = json.loads(
    (out / "subtitle-export-visual-check.json").read_text(encoding="utf-8-sig")
)
assert (
    dialogue_agent["status"]
    == dialogue_ui["status"]
    == dialogue_export["status"]
    == dialogue_launch["status"]
    == "passed"
)
assert dialogue_agent["narration_scene_count"] == 0
assert dialogue_ui["external_tts_tracks"] == 0
assert dialogue_export["dialogue_scenes"] == 4
assert dialogue_launch["window_visible"] and not dialogue_launch["debugging_port_enabled"]
assert subtitle_ui["status"] == subtitle_plan["status"] == subtitle_visual["status"] == "passed"
assert not subtitle_ui["page_errors"]
assert all(
    0 < item["start"] < item["end"]
    for item in subtitle_plan["timings"]
)
drama_local = json.loads(
    (out / "drama-local-reference-test.json").read_text(encoding="utf-8")
)
local_probe = json.loads(
    (out / "local-reference-probe.json").read_text(encoding="utf-8")
)
assert drama_local["status"] == local_probe["status"] == "passed"
local_preview = json.loads(
    (out / "drama-local-native-preview.json").read_text(encoding="utf-8")
)
drama_restart = json.loads(
    (out / "drama-final-restart.json").read_text(encoding="utf-8-sig")
)
assert local_preview["status"] == drama_restart["status"] == "passed"
assert drama_restart["codex_connected"] and drama_restart["no_active_jobs"]
assert cold["qianfan_configuration_persisted"]
prompt_ui = json.loads((out / "prompts-ui-test.json").read_text(encoding="utf-8"))
prompt_native = json.loads(
    (out / "prompts-native-test.json").read_text(encoding="utf-8")
)
assert prompt_ui["status"] == prompt_native["status"] == "passed"
assert prompt_native["live"] and prompt_native["real_agent"]["prompt_versions_recorded"]
story_prompt_ui = json.loads(
    (out / "story-prompt-ui-test.json").read_text(encoding="utf-8")
)
story_prompt_native = json.loads(
    (out / "story-prompt-native-test.json").read_text(encoding="utf-8")
)
assert story_prompt_ui["status"] == story_prompt_native["status"] == "passed"
assert story_prompt_native["live"]
assert story_prompt_native["real_agent"]["descriptions_copied_verbatim"]
assert story_prompt_native["real_agent"]["script_end_seconds"] == 15
assert cold["prompt_library_persisted"] and cold["checked_prompt_count"] == 11
launcher = json.loads((out / "launcher-test.json").read_text(encoding="utf-8"))
assert launcher["status"] == "passed" and launcher["acceptance_job"] == args.job
shutil.copy2(report_path, out / "packaged-acceptance.json")
samples = out / "samples"
samples.mkdir(exist_ok=True)
with sqlite3.connect((data / "studio.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
    copied = []
    for name, identifier in zip(
        ("drama", "narration"), report["project_ids"], strict=True
    ):
        project = json.loads(
            db.execute(
                "SELECT data FROM records WHERE kind='project' AND id=?", (identifier,)
            ).fetchone()[0]
        )
        asset = json.loads(
            db.execute(
                "SELECT data FROM records WHERE kind='asset' AND id=?",
                (project["export_id"],),
            ).fetchone()[0]
        )
        source = (data / "media" / asset["path"]).resolve()
        assert source.is_relative_to((data / "media").resolve()) and source.is_file()
        target = samples / (name + ".mp4")
        shutil.copy2(source, target)
        with target.open("rb") as file:
            sample_hash = hashlib.file_digest(file, "sha256").hexdigest()
        copied.append(
            {
                "kind": name,
                "project_id": identifier,
                "path": str(target),
                "sha256": sample_hash,
            }
        )
    for sample_name, sample_report in (
        ("drama-refined", refined),
        ("narration-steps", narration_live),
        ("drama-input-references", drama_input),
        ("drama-local-references", drama_local),
    ):
        if sample_report["status"] != "passed":
            continue
        asset = json.loads(
            db.execute(
                "SELECT data FROM records WHERE kind='asset' AND id=?",
                (sample_report["export"]["asset_id"],),
            ).fetchone()[0]
        )
        source = (data / "media" / asset["path"]).resolve()
        assert source.is_relative_to((data / "media").resolve()) and source.is_file()
        target = samples / (sample_name + ".mp4")
        shutil.copy2(source, target)
        subprocess.run(
            [
                str(root / "release/win-unpacked/resources/media/ffmpeg.exe"),
                "-v",
                "error",
                "-i",
                str(target),
                "-f",
                "null",
                "-",
            ],
            check=True,
            capture_output=True,
        )
        with target.open("rb") as file:
            sample_hash = hashlib.file_digest(file, "sha256").hexdigest()
        copied.append(
            {
                "kind": sample_name,
                "project_id": sample_report["project_id"],
                "path": str(target),
                "sha256": sample_hash,
                "decode_passed": True,
            }
        )
    skills_sample = root / "data/samples/last-light-skills.mp4"
    subprocess.run(
        [
            str(root / "release/win-unpacked/resources/media/ffmpeg.exe"),
            "-v",
            "error",
            "-i",
            str(skills_sample),
            "-f",
            "null",
            "-",
        ],
        check=True,
        capture_output=True,
    )
    with skills_sample.open("rb") as file:
        skills_hash = hashlib.file_digest(file, "sha256").hexdigest()
    copied.append(
        {
            "kind": "drama-screenwriting-visual-skills",
            "project_id": skills_live["project_id"],
            "path": str(skills_sample),
            "sha256": skills_hash,
            "duration": skills_live["duration"],
            "decode_passed": True,
        }
    )
    dialogue_sample = root / "data/samples/last-light-natural-dialogue.mp4"
    subprocess.run(
        [
            str(root / "release/win-unpacked/resources/media/ffmpeg.exe"),
            "-v",
            "error",
            "-i",
            str(dialogue_sample),
            "-f",
            "null",
            "-",
        ],
        check=True,
        capture_output=True,
    )
    with dialogue_sample.open("rb") as file:
        dialogue_hash = hashlib.file_digest(file, "sha256").hexdigest()
    copied.append(
        {
            "kind": "drama-natural-dialogue",
            "project_id": dialogue_export["project_id"],
            "path": str(dialogue_sample),
            "sha256": dialogue_hash,
            "duration": dialogue_export["info"]["duration"],
            "decode_passed": True,
        }
    )
installer = root / "release/青幕 Lime Studio Setup 1.0.0.exe"
with installer.open("rb") as file:
    checksum = hashlib.file_digest(file, "sha256").hexdigest()
manifest = {
    "status": "passed",
    "version": "1.0.0",
    "installer": {
        "path": str(installer),
        "bytes": installer.stat().st_size,
        "sha256": checksum,
    },
    "codex": json.loads((root / "docs/upstream.json").read_text(encoding="utf-8")),
    "electron": (root / "release/win-unpacked/version").read_text().strip(),
    "desktop_acceptance_job": args.job,
    "desktop_acceptance_seconds": report["duration_seconds"],
    "desktop_checks": desktop["checks"],
    "desktop_ui_checks": desktop["ui_checks"],
    "ui_refinement": ui,
    "refined_live_acceptance": refined,
    "narration_step_ui": narration_ui,
    "narration_step_live_acceptance": narration_live,
    "qianfan_llm_acceptance": qianfan,
    "qianfan_ui_checks": qianfan_ui,
    "qianfan_mcp_checks": qianfan_mcp,
    "drama_input_acceptance": drama_input,
    "drama_input_ui_checks": drama_input_ui,
    "drama_capacity_guard": drama_capacity,
    "drama_local_reference_acceptance": drama_local,
    "local_reference_probe": local_probe,
    "drama_local_reference_preview": local_preview,
    "drama_final_restart": drama_restart,
    "package_check": package_check,
    "screenwriting_visual_skills_ui": skills_ui,
    "screenwriting_visual_skills_acceptance": skills_live,
    "screenwriting_visual_skills_final_launch": skills_launch,
    "natural_dialogue_agent": dialogue_agent,
    "natural_dialogue_ui": dialogue_ui,
    "natural_dialogue_export": dialogue_export,
    "natural_dialogue_final_launch": dialogue_launch,
    "subtitle_timing_ui": subtitle_ui,
    "subtitle_timing_plan": subtitle_plan,
    "subtitle_export_visual_check": subtitle_visual,
    "prompt_library_ui": prompt_ui,
    "prompt_library_native": prompt_native,
    "story_prompt_ui": story_prompt_ui,
    "story_prompt_native": story_prompt_native,
    "prompt_library_persisted": cold["prompt_library_persisted"],
    "normal_launch_window_visible": cold["window_visible"],
    "normal_launch_debugging_port_enabled": cold["debugging_port_enabled"],
    "launcher_test": launcher,
    "samples": copied,
    "credentials_included": False,
}
(out / "delivery-manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
)
print("DELIVERY_MANIFEST_PASSED", flush=True)
