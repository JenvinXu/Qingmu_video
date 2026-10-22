from __future__ import annotations
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DATA = Path(os.environ.get("LIME_DATA_DIR", ROOT / "data")).resolve()
MEDIA = DATA / "media"
for directory in (DATA, MEDIA, DATA / "reports", DATA / "agent-workspace"):
    directory.mkdir(parents=True, exist_ok=True)
token_file = DATA / "session-token"
if not token_file.exists():
    token_file.write_text(secrets.token_urlsafe(36), encoding="utf-8")
TOKEN = token_file.read_text(encoding="utf-8").strip()
internal_file = DATA / "internal-token"
if not internal_file.exists():
    internal_file.write_text(secrets.token_urlsafe(36), encoding="utf-8")
INTERNAL_TOKEN = internal_file.read_text(encoding="utf-8").strip()


def media_path(relative: str) -> Path:
    path = (MEDIA / relative).resolve()
    if not path.is_relative_to(MEDIA) or path == MEDIA:
        raise ValueError("素材路径超出工作区")
    return path


def new_media_path(suffix: str) -> tuple[str, Path]:
    relative = secrets.token_hex(16) + suffix
    return relative, media_path(relative)
