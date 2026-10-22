"""Keep the official Responses wire contract while removing Codex-only metadata."""

from __future__ import annotations
import json
import codecs


class ResponseObserver:
    """Observe terminal SSE events before Codex closes a completed HTTP stream.

    Store accounting only; never retain text, image data or model reasoning in traces.
    """

    def __init__(self):
        self.decoder = codecs.getincrementaldecoder("utf-8")()
        self.buffer = ""
        self.status = None
        self.usage = None
        self.request_id = None
        self.error = None

    def feed(self, chunk):
        self.buffer += self.decoder.decode(chunk)
        self.buffer = self.buffer.replace("\r\n", "\n")
        while "\n\n" in self.buffer:
            event, self.buffer = self.buffer.split("\n\n", 1)
            data = "\n".join(
                line[5:].strip()
                for line in event.splitlines()
                if line.startswith("data:")
            )
            try:
                value = json.loads(data)
            except (ValueError, TypeError):
                continue
            kind = value.get("type")
            if kind in {"response.completed", "response.failed", "response.incomplete"}:
                response = value.get("response") or {}
                self.status = "completed" if kind == "response.completed" else "failed"
                self.usage = response.get("usage")
                self.request_id = response.get("id")
                self.error = response.get("error") or response.get("incomplete_details")
            elif kind == "error":
                self.status = "failed"
                self.error = value.get("message") or value.get("error")
        if len(self.buffer) > 2_000_000:
            self.buffer = ""  # bounded observation; byte forwarding remains unchanged


def normalize_input(value, *, assistant_output=False):
    if isinstance(value, str):
        return value
    items = []
    for item in value or []:
        kind = item.get("type", "message")
        if kind == "message":
            role = item.get("role", "user")
            content = item.get("content", [])
            if isinstance(content, str):
                content = [{"type": "input_text", "text": content}]
            parts = []
            for part in content:
                if part.get("type") in {"input_text", "output_text", "text"}:
                    parts.append(
                        {
                            "type": (
                                "output_text"
                                if assistant_output and role == "assistant"
                                else "input_text"
                            ),
                            "text": part.get("text", ""),
                        }
                    )
                elif part.get("type") in {"input_image", "image_url"}:
                    url = part.get("image_url")
                    if isinstance(url, dict):
                        url = url.get("url")
                    parts.append({"type": "input_image", "image_url": url})
            if parts:
                # Some compatible providers only accept input_text even on assistant history.
                items.append({"role": role, "content": parts})
        elif kind == "function_call":
            call = {
                k: item[k]
                for k in ("type", "call_id", "name", "arguments")
                if k in item
            }
            call["id"] = item.get("id") or "fc_" + item["call_id"]
            call["status"] = item.get("status") or "completed"
            items.append(call)
        elif kind == "function_call_output":
            output = item.get("output", "")
            if not isinstance(output, str):
                output = json.dumps(output, ensure_ascii=False)
            items.append(
                {
                    "type": kind,
                    "id": item.get("id") or "fco_" + item["call_id"],
                    "call_id": item["call_id"],
                    "output": output,
                }
            )
    return items
