"""Real stdio MCP discovery and authenticated diagnostics, without provider calls."""

import json
import os
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
data = Path(os.environ["APPDATA"]) / "LimeStudio/workspace"
runtime = json.loads((data / "runtime.json").read_text(encoding="utf-8"))
env = {
    **os.environ,
    "LIME_DATA_DIR": str(data),
    "LIME_BACKEND_URL": runtime["backendUrl"],
    "PYTHONUTF8": "1",
}
messages = [
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-06-18"},
    },
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "studio_diagnostics", "arguments": {}},
    },
]
result = subprocess.run(
    [sys.executable, str(root / "scripts/mcp_server.py")],
    input="".join(json.dumps(m) + "\n" for m in messages),
    capture_output=True,
    encoding="utf-8",
    env=env,
    timeout=30,
    check=True,
)
responses = [json.loads(line) for line in result.stdout.splitlines()]
assert len(responses) == 3 and not any(r.get("error") for r in responses)
assert responses[0]["result"]["protocolVersion"] == "2025-06-18"
names = [t["name"] for t in responses[1]["result"]["tools"]]
assert len(names) == 9 and {
    "studio_inspect_asset",
    "studio_create_character",
    "studio_previous_tail",
} <= set(names)
diagnostics = json.loads(responses[2]["result"]["content"][0]["text"])
assert (
    diagnostics["llm_key_configured"]
    and diagnostics["key_configured"]
    and diagnostics["agent"]["ready"]
)
report = {
    "status": "passed",
    "protocol": "2025-06-18",
    "tools": names,
    "diagnostics_passed": True,
}
(root / "data/reports/qianfan-mcp-test.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
)
print("QIANFAN_MCP_TEST_PASSED")
