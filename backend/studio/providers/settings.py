from __future__ import annotations
from urllib.parse import urlsplit
from ..core.store import store
from ..core.secrets import encrypt, decrypt
from ..domain.models import Settings
from ..domain.timing import MIN_DRAMA_SCENE_SECONDS, MAX_DRAMA_SCENE_SECONDS


def read_settings(private=False):
    try:
        saved = store.get("settings", "models")
    except KeyError:
        saved = {}
    key = decrypt(saved.get("encrypted_key", ""))
    llm_key = decrypt(saved.get("encrypted_llm_key", ""))
    video_key = decrypt(saved.get("encrypted_video_key", ""))
    result = Settings().model_dump(
        exclude={"api_key", "llm_api_key", "video_api_key"}
    )
    result.update(
        {
            k: v
            for k, v in saved.items()
            if k
            not in {
                "encrypted_key",
                "encrypted_llm_key",
                "encrypted_video_key",
                "api_key",
                "llm_api_key",
                "video_api_key",
            }
        }
    )
    result["video_seconds"] = min(
        MAX_DRAMA_SCENE_SECONDS,
        max(MIN_DRAMA_SCENE_SECONDS, int(result.get("video_seconds") or 5)),
    )
    result.update(
        key_configured=bool(key),
        video_key_configured=bool(video_key or key),
        llm_key_configured=bool(key if result["llm_provider"] == "media" else llm_key),
    )
    if private:
        result["api_key"] = key
        result["llm_api_key"] = llm_key
        # Existing installations keep working until a dedicated video key is saved.
        result["video_api_key"] = video_key or key
    return result


def save_settings(value: Settings):
    validate_url(value.base_url)
    validate_url(value.llm_base_url)
    try:
        previous = store.get("settings", "models")
    except KeyError:
        previous = {}
    data = value.model_dump(exclude={"api_key", "llm_api_key", "video_api_key"})
    data["base_url"] = data["base_url"].rstrip("/")
    data["llm_base_url"] = data["llm_base_url"].rstrip("/")
    data.update(
        id="models",
        encrypted_key=(
            encrypt(value.api_key)
            if value.api_key
            else previous.get("encrypted_key", "")
        ),
        encrypted_llm_key=(
            encrypt(value.llm_api_key)
            if value.llm_api_key
            else previous.get("encrypted_llm_key", "")
        ),
        encrypted_video_key=(
            encrypt(value.video_api_key)
            if value.video_api_key
            else previous.get("encrypted_video_key", "")
        ),
    )
    store.save("settings", data)
    return read_settings()


def validate_url(address):
    url = urlsplit(address)
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username
        or url.password
    ):
        raise ValueError("请输入有效的模型 API 地址")
    if url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1"}:
        raise ValueError("外部模型接口需要 HTTPS")


def llm_connection():
    settings = read_settings(True)
    separate = settings["llm_provider"] != "media"
    return {
        "provider": settings["llm_provider"],
        "base_url": settings["llm_base_url"] if separate else settings["base_url"],
        "api_key": settings["llm_api_key"] if separate else settings["api_key"],
        "text_model": settings["text_model"],
        "vision_model": settings["vision_model"],
    }


def safe_error(error: Exception) -> str:
    text = str(error) or type(error).__name__
    cause = error.__cause__
    for _ in range(3):
        if not cause:
            break
        detail = str(cause)
        if detail and detail not in text:
            text += ": " + detail
        cause = cause.__cause__
    try:
        settings = read_settings(True)
        for field in ("api_key", "llm_api_key", "video_api_key"):
            if settings.get(field):
                text = text.replace(settings[field], "[已隐藏]")
    except Exception:
        pass
    return text[:2000]
