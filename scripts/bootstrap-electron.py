"""Fetch official Electron through the Windows proxy and verify npm release SHA-256."""

import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.request import getproxies
import zipfile
import httpx

sys.stdout.reconfigure(encoding="utf-8")
root = Path(__file__).resolve().parents[1]
module = root / "node_modules/electron"
version = json.loads((module / "package.json").read_text())["version"]
dist = module / "dist"
if (dist / "electron.exe").exists() and (dist / "version").read_text().strip().lstrip(
    "v"
) == version:
    print("Official Electron already installed:", version)
    raise SystemExit(0)
name = f"electron-v{version}-win32-x64.zip"
origin = f"https://github.com/electron/electron/releases/download/v{version}"
checksum = json.loads((module / "checksums.json").read_text())[name]
cache = (
    Path(os.environ["LOCALAPPDATA"])
    / "electron/Cache"
    / hashlib.sha256(origin.encode()).hexdigest()
    / name
)
cache.parent.mkdir(parents=True, exist_ok=True)
valid = cache.exists() and hashlib.sha256(cache.read_bytes()).hexdigest() == checksum
if not valid:
    partial = cache.with_suffix(".part")
    proxy = getproxies().get("https") or getproxies().get("http")
    with (
        httpx.Client(proxy=proxy, follow_redirects=True, timeout=90) as client,
        client.stream("GET", origin + "/" + name) as response,
    ):
        response.raise_for_status()
        total = int(response.headers.get("content-length", "0"))
        size = 0
        checkpoint = 0
        digest = hashlib.sha256()
        with partial.open("wb") as output:
            for chunk in response.iter_bytes(512 * 1024):
                output.write(chunk)
                digest.update(chunk)
                size += len(chunk)
                if size - checkpoint > 20 * 1024 * 1024:
                    print("Official Electron downloaded:", size, "/", total, flush=True)
                    checkpoint = size
        if digest.hexdigest() != checksum:
            partial.unlink(missing_ok=True)
            raise RuntimeError(
                "Official Electron archive SHA-256 did not match the release checksum"
            )
        partial.replace(cache)
dist.mkdir(exist_ok=True)
with zipfile.ZipFile(cache) as archive:
    if any(
        not (dist / name).resolve().is_relative_to(dist.resolve())
        for name in archive.namelist()
    ):
        raise RuntimeError("Invalid archive paths")
    archive.extractall(dist)
(module / "path.txt").write_text("electron.exe", encoding="utf-8")
print("Official Electron verified and installed:", version, checksum, flush=True)
