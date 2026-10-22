"""Verify timed story scripts, automatic shot count, model menus, and the production panel."""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
parser = argparse.ArgumentParser()
parser.add_argument("--native", action="store_true")
parser.add_argument("--live", action="store_true")
parser.add_argument("--url", default="http://127.0.0.1:4428")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
data = (
    Path(os.environ["APPDATA"]) / "LimeStudio/workspace"
    if args.native
    else root / "data"
)
base = (
    json.loads((data / "runtime.json").read_text(encoding="utf-8"))["backendUrl"]
    if args.native
    else args.url
)
client = httpx.Client(
    base_url=base,
    headers={"Authorization": "Bearer " + (data / "session-token").read_text().strip()},
    timeout=40,
)
report = {
    "status": "running",
    "native": args.native,
    "live": args.live,
    "checks": [],
    "page_errors": [],
}
created = []
marker = re.compile(
    r"(?m)^[ \t]*[（(]\s*(\d+)\s*[-–—~至]\s*(\d+)\s*秒?\s*[）)]\s*分镜\s*0*(\d+)\s*[：:]\s*"
)


def call(method, path, body=None):
    response = client.request(method, path, json=body)
    response.raise_for_status()
    return response.json()


def read(ident):
    return call("GET", "/api/projects/" + ident)


def segments(script):
    matches = list(marker.finditer(script))
    return [
        {
            "number": int(match.group(3)),
            "start": int(match.group(1)),
            "end": int(match.group(2)),
            "text": script[
                match.end() : matches[index + 1].start()
                if index + 1 < len(matches)
                else len(script)
            ].strip(),
        }
        for index, match in enumerate(matches)
    ]


def wait(page, predicate, timeout=30):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "Timed out waiting for saved state"
        page.wait_for_timeout(120)


def wait_job(page, ident):
    wait(
        page,
        lambda: call("GET", "/api/jobs/" + ident)["status"]
        not in {"queued", "running"},
        240,
    )
    job = call("GET", "/api/jobs/" + ident)
    assert job["status"] == "completed", job.get("error")
    return job


try:
    with sync_playwright() as playwright:
        if args.native:
            browser = playwright.chromium.connect_over_cdp("http://127.0.0.1:9225")
            context = browser.contexts[0]
            page = (
                context.pages[0]
                if context.pages
                else context.wait_for_event("page", timeout=60000)
            )
        else:
            browser = playwright.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(
                "http://127.0.0.1:5178/#"
                + urlencode(
                    {"api": base, "token": (data / "session-token").read_text().strip()}
                )
            )
        page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
        page.get_by_role("button", name="我的作品", exact=True).wait_for(timeout=60000)
        if args.native:
            connection = page.evaluate("window.studioDesktop.connection()")
            client.close()
            client = httpx.Client(
                base_url=connection["baseUrl"],
                headers={"Authorization": "Bearer " + connection["token"]},
                timeout=40,
            )

        prompts = call("GET", "/api/prompts")
        assert len(prompts) == 11 and all(
            value.get("template_version") == 2 for value in prompts
        )
        assert all(len(value["text"]) > 120 for value in prompts)
        drama_idea = next(value for value in prompts if value["id"] == "drama_idea")[
            "text"
        ]
        drama_board = next(
            value for value in prompts if value["id"] == "drama_storyboard"
        )["text"]
        assert (
            "（0-5秒）分镜1" in drama_idea and "description 必须逐字复制" in drama_board
        )
        report["checks"].append(
            "11 项精细提示词升级并保留版本；短剧时间轴格式和逐字映射规则已进入后端"
        )

        if args.live:
            project = call(
                "POST",
                "/api/projects",
                {
                    "kind": "drama",
                    "title": "QA精细分镜提示词",
                    "prompt": "雨夜末班车站，一位女孩把珍藏多年的旧车票还给久别重逢的朋友，两人终于和解。",
                    "target_duration": 15,
                },
            )
            created.append(project["id"])
            started = time.monotonic()
            idea = call(
                "POST", f"/api/projects/{project['id']}/run", {"action": "idea"}
            )
            wait_job(page, idea["id"])
            written = read(project["id"])
            marked = segments(written["script"])
            assert marked and written["scene_count"] == len(marked)
            assert marked[0]["start"] == 0 and marked[-1]["end"] == 15
            assert [value["number"] for value in marked] == list(
                range(1, len(marked) + 1)
            )
            board = call(
                "POST", f"/api/projects/{project['id']}/run", {"action": "storyboard"}
            )
            wait_job(page, board["id"])
            finished = read(project["id"])
            assert len(finished["scenes"]) == len(marked)
            assert [scene["description"] for scene in finished["scenes"]] == [
                value["text"] for value in marked
            ]
            assert [scene["duration"] for scene in finished["scenes"]] == [
                value["end"] - value["start"] for value in marked
            ]
            report["real_agent"] = {
                "job_ids": [idea["id"], board["id"]],
                "duration_seconds": round(time.monotonic() - started, 2),
                "scene_count": len(marked),
                "script_end_seconds": marked[-1]["end"],
                "descriptions_copied_verbatim": True,
            }
            report["checks"].append(
                "真实 Codex 生成连续时间轴文案，并按分镜号、时间差和原文一一建立分镜"
            )
            ui_project = finished
        else:
            script = (
                "（0-5秒）分镜1：中景，女孩推开雨夜车站的大门。\n"
                "（5-11秒）分镜2：特写，她把旧车票放进朋友掌心。"
            )
            ui_project = call(
                "POST", "/api/projects", {"kind": "drama", "title": "QA分镜制作布局"}
            )
            created.append(ui_project["id"])
            ui_project = call(
                "PATCH",
                f"/api/projects/{ui_project['id']}",
                {"revision": ui_project["revision"], "script": script},
            )
            ui_project = call(
                "PATCH",
                f"/api/projects/{ui_project['id']}",
                {
                    "revision": ui_project["revision"],
                    "scenes": [
                        {
                            "id": "one",
                            "title": "推门",
                            "description": "中景，女孩推开雨夜车站的大门。",
                            "duration": 5,
                        },
                        {
                            "id": "two",
                            "title": "归还",
                            "description": "特写，她把旧车票放进朋友掌心。",
                            "duration": 6,
                        },
                    ],
                },
            )

        page.get_by_role("button", name="我的作品", exact=True).click()
        page.get_by_role(
            "button", name="打开作品" + ui_project["title"], exact=True
        ).click()
        page.get_by_role("button", name="视频文案", exact=True).click()
        assert page.get_by_text(
            f"已识别 {ui_project['scene_count']} 个分镜", exact=True
        ).is_visible()
        assert page.get_by_text("分镜数量", exact=True).count() == 0
        page.get_by_role("button", name="视频制作", exact=True).click()
        panel = page.locator(".reference-maker")
        assert panel.get_by_role("button", name="全部参考", exact=True).is_visible()
        assert panel.get_by_role("button", name="视频制作", exact=True).is_visible()
        for label in ["角色参考", "物品参考", "音色参考", "视频参考", "图片参考"]:
            assert panel.get_by_role("button", name=label, exact=True).is_visible()
        assert page.get_by_label("视频比例", exact=True).count() == 0
        panel.get_by_role("button", name="图片参考", exact=True).click()
        panel.get_by_role("button", name="选择生成首帧模型", exact=True).click()
        assert panel.get_by_role("menu").is_visible()
        panel.get_by_role("button", name="默认 ·", exact=False).click()
        panel.get_by_role("button", name="视频制作", exact=True).click()
        assert page.get_by_label("视频比例", exact=True).is_visible()
        panel.get_by_role("button", name="选择生成视频模型", exact=True).click()
        panel.get_by_role("button", name="自定义模型…", exact=True).click()
        panel.get_by_label("自定义生成视频模型", exact=True).fill("qa-video-model")
        panel.get_by_label("自定义生成视频模型", exact=True).press("Enter")
        wait(
            page,
            lambda: read(ui_project["id"])["scenes"][0]["video_model"]
            == "qa-video-model",
        )
        actions = page.locator(".production-actions-card")
        assert actions.get_by_role("button", name="智能优化", exact=True).is_visible()
        assert actions.get_by_role("button", name="制作全部", exact=True).is_visible()
        assert "primary" in actions.get_by_role(
            "button", name="制作全部", exact=True
        ).get_attribute("class")
        page.screenshot(
            path=str(
                root
                / "data/reports"
                / ("story-prompt-native.png" if args.native else "story-prompt-ui.png")
            ),
            full_page=True,
        )
        report["checks"].append(
            "移除手填镜数；参考子栏、视频制作页、图片/视频模型下拉及醒目制作操作卡片通过"
        )
        assert not report["page_errors"]
        report["status"] = "passed"
        if not args.native:
            browser.close()
finally:
    for ident in created:
        try:
            client.delete("/api/projects/" + ident)
        except Exception:
            pass
    report_path = (
        root
        / "data/reports"
        / (
            "story-prompt-native-test.json"
            if args.native
            else "story-prompt-ui-test.json"
        )
    )
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    client.close()

print("STORY_PROMPT_UI_PASSED")
