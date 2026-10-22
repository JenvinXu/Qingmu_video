"""Inspect and save the real packaged model configuration without exposing keys."""

import json
import sys
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
root = Path(__file__).resolve().parents[1]
out = root / "data/reports"
with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9225")
    page = browser.contexts[0].pages[0]
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.get_by_role("button", name="模型设置", exact=True).click()
    page.get_by_label("文本模型", exact=True).wait_for()
    assert page.get_by_label("模型服务").input_value() == "qianfan"
    assert (
        page.get_by_label("文本模型", exact=True).input_value() == "deepseek-v4-flash"
    )
    assert page.get_by_label("视觉模型", exact=True).input_value() == "kimi-k2.6"
    assert (
        page.get_by_label("LLM API 地址", exact=True).input_value()
        == "https://qianfan.baidubce.com/v2"
    )
    llm_key = page.get_by_label("LLM API Key", exact=True)
    assert llm_key.input_value() == "" and "已加密保存" in llm_key.get_attribute(
        "placeholder"
    )
    assert page.get_by_role("tab").count() == 3
    assert page.locator(".settings-model-card[aria-pressed=true]").count() == 1
    page.get_by_label("模型服务").select_option("media")
    assert page.get_by_label("文本模型", exact=True).input_value() == "agnes-2.5-flash"
    page.get_by_label("模型服务").select_option("qianfan")
    assert (
        page.get_by_label("文本模型", exact=True).input_value() == "deepseek-v4-flash"
    )
    assert page.get_by_label("视觉模型", exact=True).input_value() == "kimi-k2.6"
    page.get_by_role("tab", name="图片模型", exact=False).click()
    assert (
        page.get_by_label("媒体 API 地址", exact=True).input_value()
        == "https://api.agnes-ai.cn/v1"
    )
    media_key = page.get_by_label("媒体 API Key", exact=True)
    assert media_key.input_value() == "" and "已加密保存" in media_key.get_attribute(
        "placeholder"
    )
    page.get_by_role("tab", name="文本模型", exact=False).click()
    page.get_by_role("button", name="保存配置", exact=True).click()
    page.get_by_text("配置已保存", exact=True).wait_for(timeout=30000)
    connection = page.evaluate("window.studioDesktop.connection()")
    with httpx.Client(
        base_url=connection["baseUrl"],
        headers={"Authorization": "Bearer " + connection["token"]},
        timeout=30,
    ) as client:
        settings = client.get("/api/settings").json()
        assert settings["llm_key_configured"] and settings["key_configured"]
        assert (
            settings["text_model"] == "deepseek-v4-flash"
            and settings["video_model"] == "agnes-video-2.5-flash"
        )
        assert (
            not {"api_key", "llm_api_key", "encrypted_key", "encrypted_llm_key"}
            & settings.keys()
        )
        picture = next(
            a
            for a in client.get("/api/assets").json()
            if a["mime"].startswith("image/") and a["source"] == "generated"
        )
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert "bce-v3/ALTAK-" not in page.content() and "cpk-" not in page.content()
    page.screenshot(path=str(out / "desktop-qianfan-settings.png"), full_page=True)
    page.get_by_role("button", name="素材库", exact=True).click()
    page.locator(".asset-card").filter(has_text=picture["name"]).first.click()
    page.get_by_role("button", name="识别图片", exact=True).wait_for()
    page.screenshot(path=str(out / "desktop-qianfan-vision.png"), full_page=True)
    assert not errors, errors
    report = {
        "status": "passed",
        "checks": [
            "real packaged Qianfan text/vision configuration",
            "independent media configuration",
            "provider presets select inexpensive text model",
            "blank-key save retains encrypted credentials",
            "keys excluded from renderer and public API",
            "visual action available on real image asset",
            "no page errors or horizontal overflow",
        ],
        "page_errors": errors,
    }
    (out / "qianfan-ui-test.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))
