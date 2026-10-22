"""Run one real end-to-end acceptance and write server evidence; exit nonzero on failure."""

from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path
import httpx

sys.stdout.reconfigure(encoding="utf-8")
parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:4318")
parser.add_argument("--data", default=str(Path(__file__).resolve().parents[1] / "data"))
parser.add_argument("--job", default="")
parser.add_argument(
    "--resume",
    action="store_true",
    help="Reuse the last failed acceptance project and its provider tasks",
)
args = parser.parse_args()
token = (Path(args.data) / "session-token").read_text(encoding="utf-8").strip()
with httpx.Client(
    base_url=args.url, headers={"Authorization": "Bearer " + token}, timeout=35
) as client:
    if args.job:
        ident = args.job
    else:
        response = client.post("/api/acceptance", params={"resume": args.resume})
        response.raise_for_status()
        ident = response.json()["id"]
    print("Acceptance job:", ident, flush=True)
    previous = None
    while True:
        response = client.get("/api/jobs/" + ident)
        response.raise_for_status()
        job = response.json()
        current = (job["status"], job.get("message"))
        if current != previous:
            print(job["status"], job.get("progress", 0), job.get("message"), flush=True)
            previous = current
        if job["status"] in {"completed", "failed", "cancelled"}:
            print(
                json.dumps(
                    job.get("result") or {"error": job.get("error")},
                    ensure_ascii=False,
                    indent=2,
                ),
                flush=True,
            )
            sys.exit(
                0
                if job["status"] == "completed"
                and job.get("result", {}).get("status") == "passed"
                else 1
            )
        time.sleep(5)
