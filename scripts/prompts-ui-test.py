"""Verify prompt editing/persistence and shared drama timing; optional real Agent turn."""
import argparse
import json
import os
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
parser.add_argument("--url", default="http://127.0.0.1:4418")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
data = Path(os.environ["APPDATA"]) / "LimeStudio/workspace" if args.native else root / "data"
base = json.loads((data / "runtime.json").read_text(encoding="utf-8"))["backendUrl"] if args.native else args.url
client = httpx.Client(base_url=base, headers={"Authorization": "Bearer " + (data / "session-token").read_text().strip()}, timeout=30)
out = root / "data/reports"
report = {"status": "running", "native": args.native, "live": args.live, "checks": [], "page_errors": []}
originals, edited = {}, {}
pid = None

def call(method, path, body=None):
    r = client.request(method, path, json=body)
    r.raise_for_status()
    return r.json()

def entries():
    return {p["id"]: p for p in call("GET", "/api/prompts")}

def read():
    return call("GET", "/api/projects/" + pid)

def wait(predicate, page, timeout=30):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "Timed out waiting for actual saved state"
        page.wait_for_timeout(100)

def wait_job(ident, page):
    wait(lambda: call("GET", "/api/jobs/" + ident)["status"] not in ["queued", "running"], page, 180)
    job = call("GET", "/api/jobs/" + ident)
    assert job["status"] == "completed", job.get("error")
    return job

try:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9225") if args.native else p.chromium.launch(channel="msedge", headless=True)
        page = browser.contexts[0].pages[0] if args.native else browser.new_page(viewport={"width": 1280, "height": 820})
        page.on("pageerror", lambda e: report["page_errors"].append(str(e)))
        if not args.native:
            page.goto("http://127.0.0.1:5178/#" + urlencode({"api": base, "token": (data / "session-token").read_text().strip()}))
        page.get_by_role("button", name="提示词库", exact=True).wait_for(timeout=60000)
        page.get_by_role("button", name="提示词库", exact=True).click()
        field = page.get_by_role("textbox", name="步骤提示词", exact=True)
        field.wait_for()
        if args.native:
            connection = page.evaluate("window.studioDesktop.connection()")
            client.close()
            client = httpx.Client(base_url=connection["baseUrl"], headers={"Authorization": "Bearer " + connection["token"]}, timeout=30)
        nav = page.locator(".sidebar nav button").all_text_contents()
        assert nav[nav.index("物品库") + 1] == "提示词库"
        current = entries()
        assert len(current) == 11
        for ident in ["drama_idea", "drama_storyboard", "drama_assets"]:
            originals[ident] = current[ident]
        edited["drama_idea"] = originals["drama_idea"]["text"] + '\n本次验收要求：在文案末尾原样增加一句“落日仍在球场等我”。'
        field.fill(edited["drama_idea"])
        page.get_by_role("button", name="视频文案 → 分镜", exact=True).click()
        assert entries()["drama_idea"]["text"] == edited["drama_idea"]
        edited["drama_storyboard"] = originals["drama_storyboard"]["text"] + "\n本次验收要求：每个镜头 duration 为 7 秒，video_seconds 为 7。"
        field.fill(edited["drama_storyboard"])
        page.get_by_role("button", name="分镜 → 资产匹配", exact=True).click()
        assert entries()["drama_storyboard"]["text"] == edited["drama_storyboard"]
        edited["drama_assets"] = originals["drama_assets"]["text"] + "\n本次验收要求：每个镜头都选择已配置的篮球运动员角色；没有物品时不选择物品。"
        field.fill(edited["drama_assets"])
        page.get_by_role("button", name="我的作品", exact=True).click()
        wait(lambda: entries()["drama_assets"]["text"] == edited["drama_assets"], page)
        report["checks"].append("入口紧随物品库；11 个步骤提示词可编辑；切换步骤和页面立即同步后端")
        page.get_by_role("button", name="提示词库", exact=True).click()
        for group in ["口播", "通用", "短剧"]:
            page.locator(".prompt-groups").get_by_role("button", name=group, exact=True).click()
            assert field.input_value()
        page.screenshot(path=str(out / ("prompt-library-native.png" if args.native else "prompt-library.png")))
        assert field.input_value() == edited["drama_idea"]
        assets = call("GET", "/api/assets")
        role = next((a for a in assets if a["kind"] == "character" and a.get("mime", "").startswith("image/")), None)
        project = call("POST", "/api/projects", {"kind": "drama", "title": "QA提示词与镜头时长验证", "prompt": "篮球运动员在落日球场投进最后一球，与朋友相视一笑。", "scene_count": 2, "target_duration": 14, "asset_ids": [role["id"]] if role else []})
        pid = project["id"]
        if args.live:
            started = time.monotonic()
            idea = call("POST", f"/api/projects/{pid}/run", {"action": "idea"})
            wait_job(idea["id"], page)
            assert "落日仍在球场等我" in read()["script"]
            board = call("POST", f"/api/projects/{pid}/run", {"action": "storyboard"})
            wait_job(board["id"], page)
            scenes = read()["scenes"]
            assert len(scenes) == 2 and all(s["duration"] == s["video_seconds"] == 7 for s in scenes)
            if role:
                assert all(role["id"] in s["asset_ids"] for s in scenes)
            traces = call("GET", "/api/traces")
            snapshots = [t for t in traces if t.get("event") == "prompt_applied" and t.get("job_id") in [idea["id"], board["id"]]]
            assert len(snapshots) == 2
            assert any("落日仍在球场等我" in t["message"] for t in snapshots)
            assert any("每个镜头都选择" in t["message"] for t in snapshots)
            report["real_agent"] = {"job_ids": [idea["id"], board["id"]], "duration_seconds": round(time.monotonic() - started, 2), "script_marker_present": True, "scene_durations": [s["duration"] for s in scenes], "asset_matching_applied": bool(role), "prompt_versions_recorded": True}
            report["checks"].append("实际 Codex 文案、分镜及资产匹配使用编辑后的提示词；每镜整数时长一致；任务记录提示词版本")
        else:
            project = call("PATCH", f"/api/projects/{pid}", {"revision": project["revision"], "script": "球场投篮。朋友微笑。", "scenes": [{"id": "a", "title": "投篮", "description": "球场投篮", "duration": 5}, {"id": "b", "title": "微笑", "description": "朋友微笑", "duration": 6}]})
        page.get_by_role("button", name="我的作品", exact=True).click()
        page.get_by_role("button", name="打开作品" + project["title"], exact=True).click()
        page.get_by_role("button", name="分镜设置", exact=True).click()
        card = page.locator(".storyboard-card").first
        heading = card.locator(".storyboard-card-heading > span").first.bounding_box()
        title = card.get_by_label("分镜 1 标题", exact=True).bounding_box()
        assert abs((heading["y"] + heading["height"] / 2) - (title["y"] + title["height"] / 2)) < 8
        assert card.bounding_box()["height"] < 370, card.bounding_box()
        card.get_by_label("时长", exact=True).fill("7.3")
        wait(lambda: read()["scenes"][0]["duration"] == read()["scenes"][0]["video_seconds"] == 8, page)
        page.screenshot(path=str(out / ("compact-storyboard-native.png" if args.native else "compact-storyboard.png")))
        page.get_by_role("button", name="开始创作", exact=True).click()
        page.get_by_label("视频时长", exact=True).wait_for()
        assert page.get_by_label("视频时长", exact=True).input_value() == "8"
        page.locator(".scene-advanced summary").click()
        assert page.get_by_label("剪辑时长", exact=True).input_value() == "8"
        page.get_by_label("视频时长", exact=True).fill("9")
        assert page.get_by_label("剪辑时长", exact=True).input_value() == "9"
        assert "00:09" in page.locator(".timeline-clip").first.inner_text()
        wait(lambda: read()["scenes"][0]["duration"] == read()["scenes"][0]["video_seconds"] == 9, page)
        page.get_by_role("button", name="分镜设置", exact=True).click()
        wait(lambda: read()["scenes"][0]["duration"] == read()["scenes"][0]["video_seconds"] == 9, page)
        assert page.locator(".storyboard-card").first.get_by_label("时长", exact=True).input_value() == "9"
        report["checks"].append("分镜编号标题同行、卡片紧凑；小数归整；分镜/生成/剪辑与后台时长双向一致")
        assert not report["page_errors"]
        report["status"] = "passed"
        if not args.native:
            browser.close()
except Exception as e:
    report["status"] = "failed"
    report["error"] = str(e)
    raise
finally:
    for ident, original in originals.items():
        current = entries()[ident]
        if current["text"] == edited.get(ident):
            call("PUT", "/api/prompts/" + ident, {"revision": current["revision"], "text": original["text"]})
    if pid:
        client.delete("/api/projects/" + pid)
    (out / ("prompts-native-test.json" if args.native else "prompts-ui-test.json")).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    client.close()
print("PROMPTS_TIMING_TEST_PASSED")
