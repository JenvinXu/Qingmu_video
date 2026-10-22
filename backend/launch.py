from __future__ import annotations
import argparse
import multiprocessing
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main():
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=4318)
    args = parser.parse_args()
    import uvicorn
    from studio.api.app import app

    uvicorn.run(
        app, host="127.0.0.1", port=args.port, access_log=False, log_level="warning"
    )


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
