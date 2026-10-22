"""Exercise the final native first-frame quota guard with real imported images."""

import json
import os
import sys
import time
from pathlib import Path
import httpx

sys.stdout.reconfigure(encoding="utf-8")
root = Path(__file__).resolve().parents[1]
data = Path(os.environ["APPDATA"]) / "LimeStudio/workspace"
runtime = json.loads((data / "runtime.json").read_text(encoding="utf-8"))
client = httpx.Client(
    base_url=runtime["backendUrl"],
    headers={
        "Authorization": "Bearer "
        + (data / "session-token").read_text(encoding="utf-8").strip()
    },
    timeout=60,
)


def call(method, path, body=None):
    r = client.request(method, path, json=body)
    r.raise_for_status()
    return r.json()


assets = call("GET", "/api/assets")
photo = next(a for a in assets if a["kind"] == "image" and a.get("thumbnail"))
project = call("POST", "/api/projects", {"kind": "drama", "title": "首帧容量保护测试"})
ids = []
try:
    for index in range(30):
        with (data / "media" / photo["thumbnail"]).open("rb") as file:
            r = client.post(
                "/api/assets/import",
                data={"kind": "image"},
                files={"file": (f"capacity-{index}.jpg", file, "image/jpeg")},
            )
            r.raise_for_status()
            ids.append(r.json()["id"])
    project = call(
        "PATCH",
        "/api/projects/" + project["id"],
        {
            "revision": project["revision"],
            "scenes": [
                {
                    "id": "capacity",
                    "title": "容量",
                    "description": "检查首帧预留位置",
                    "reference_ids": ids,
                }
            ],
        },
    )
    job = call(
        "POST",
        "/api/projects/" + project["id"] + "/run",
        {"action": "image", "scene_id": "capacity"},
    )
    deadline = time.monotonic() + 20
    while job["status"] not in {"completed", "failed", "cancelled"}:
        assert time.monotonic() < deadline
        time.sleep(0.1)
        job = call("GET", "/api/jobs/" + job["id"])
    assert job["status"] == "failed" and "预留" in job["error"]
    saved = call("GET", "/api/projects/" + project["id"])
    assert (
        saved["scenes"][0]["reference_ids"] == ids
        and saved["scenes"][0]["first_frame_id"] is None
    )
    report = {
        "status": "passed",
        "native": True,
        "imported_images": 30,
        "first_frame_quota_rejected_before_generation": True,
        "reference_ids_preserved": True,
        "job": job,
    }
    (root / "data/reports/drama-capacity-test.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("DRAMA_CAPACITY_TEST_PASSED")
finally:
    call("DELETE", "/api/projects/" + project["id"])
    for ident in ids:
        client.delete("/api/assets/" + ident)
    client.close()
