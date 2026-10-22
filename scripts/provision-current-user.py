"""Initialize this Windows user's desktop data separately from distributable binaries.

Uses a consistent SQLite backup. Never overwrites an existing user's database.
DPAPI-encrypted settings remain bound to the current Windows account.
"""

import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")

root = Path(__file__).resolve().parents[1]
source = root / "data"
target = Path(os.environ["APPDATA"]) / "LimeStudio/workspace"
target.mkdir(parents=True, exist_ok=True)
database = target / "studio.sqlite3"
if database.exists():
    if "--merge-samples" in sys.argv:
        with (
            sqlite3.connect(source / "studio.sqlite3") as src,
            sqlite3.connect(database) as dst,
        ):
            for kind, ident, raw, updated in src.execute(
                "SELECT kind,id,data,updated FROM records"
            ).fetchall():
                value = json.loads(raw)
                if kind == "settings":
                    continue
                if kind == "project" and not (
                    value.get("export_id")
                    or value.get("title", "").startswith("参考示例")
                ):
                    continue
                if kind in {"job", "report"} and value.get("status") not in {
                    "completed",
                    "passed",
                }:
                    continue
                if kind == "trace" and value.get("status") == "failed":
                    continue
                dst.execute(
                    "INSERT OR IGNORE INTO records VALUES (?,?,?,?)",
                    (kind, ident, raw, updated),
                )
            dst.commit()
        shutil.copytree(source / "media", target / "media", dirs_exist_ok=True)
        for report in (source / "reports").glob("*.json"):
            if json.loads(report.read_text(encoding="utf-8")).get("status") == "passed":
                shutil.copy2(report, target / "reports" / report.name)
        print(
            "Additional samples added; existing settings and projects preserved:",
            target,
        )
        raise SystemExit(0)
    print("Existing desktop workspace preserved:", target)
    raise SystemExit(0)
with (
    sqlite3.connect(source / "studio.sqlite3") as src,
    sqlite3.connect(database) as dst,
):
    active = [
        json.loads(row[0])
        for row in src.execute("SELECT data FROM records WHERE kind='job'")
    ]
    if any(j["status"] in {"running", "queued"} for j in active):
        raise RuntimeError(
            "Wait until current production finishes before initializing desktop data"
        )
    src.backup(dst)
    failed_projects = set()
    for ident, raw in dst.execute(
        "SELECT id,data FROM records WHERE kind='report'"
    ).fetchall():
        report = json.loads(raw)
        if report.get("status") != "passed":
            failed_projects.update(report.get("project_ids", []))
            dst.execute("DELETE FROM records WHERE kind='report' AND id=?", (ident,))
    for ident in failed_projects:
        row = dst.execute(
            "SELECT data FROM records WHERE kind='project' AND id=?", (ident,)
        ).fetchone()
        if row and not json.loads(row[0]).get("export_id"):
            dst.execute("DELETE FROM records WHERE kind='project' AND id=?", (ident,))
    failed_jobs = {j["id"] for j in active if j["status"] in {"failed", "cancelled"}}
    for ident in failed_jobs:
        dst.execute("DELETE FROM records WHERE kind='job' AND id=?", (ident,))
    for ident, raw in dst.execute(
        "SELECT id,data FROM records WHERE kind='trace'"
    ).fetchall():
        if json.loads(raw).get("job_id") in failed_jobs:
            dst.execute("DELETE FROM records WHERE kind='trace' AND id=?", (ident,))
    dst.commit()
shutil.copytree(source / "media", target / "media", dirs_exist_ok=True)
(target / "reports").mkdir(exist_ok=True)
for report in (source / "reports").glob("*.json"):
    value = json.loads(report.read_text(encoding="utf-8"))
    if value.get("status") == "passed":
        shutil.copy2(report, target / "reports" / report.name)
print("Desktop workspace initialized without embedding credentials:", target)
