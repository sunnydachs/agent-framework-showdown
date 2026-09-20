"""Reassembles recorded SSE streams in llm_calls_<framework>.jsonl into full JSON.

Each trace record has response either as a dict (non-stream) or
{"_raw": "<SSE text>"} when the client requested streaming. This script parses
the SSE chunks and reconstructs a single consolidated message per call:
content, reasoning, tool_calls, finish_reason, and usage (from the final chunk
with usage, or OpenRouter's :free caveat).
"""
import json
import sys
from pathlib import Path

TRACE_DIR = Path(__file__).resolve().parent.parent / "traces"


def parse_sse(raw: str):
    content_parts = []
    reasoning_parts = []
    tool_calls = {}
    finish_reason = None
    usage = None
    model = None
    provider = None
    for line in raw.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[len("data: "):].strip()
        if payload == "[DONE]":
            break
        try:
            chunk = json.loads(payload)
        except json.JSONDecodeError:
            continue
        model = model or chunk.get("model")
        provider = provider or chunk.get("provider")
        if chunk.get("usage"):
            usage = chunk["usage"]
        for choice in chunk.get("choices", []):
            delta = choice.get("delta") or {}
            if delta.get("content"):
                content_parts.append(delta["content"])
            if delta.get("reasoning"):
                reasoning_parts.append(delta["reasoning"])
            for tc in delta.get("tool_calls") or []:
                idx = tc.get("index", 0)
                slot = tool_calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["name"] = fn["name"]
                if fn.get("arguments"):
                    slot["arguments"] += fn["arguments"]
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]
    return {
        "model": model,
        "provider": provider,
        "content": "".join(content_parts),
        "reasoning": "".join(reasoning_parts),
        "tool_calls": [tool_calls[i] for i in sorted(tool_calls)],
        "finish_reason": finish_reason,
        "usage": usage,
    }


def main():
    framework = sys.argv[1] if len(sys.argv) > 1 else None
    files = sorted(TRACE_DIR.glob("llm_calls_*.jsonl"))
    for f in files:
        fw = f.stem.replace("llm_calls_", "")
        if framework and fw != framework:
            continue
        out_path = TRACE_DIR / f"parsed_{fw}.jsonl"
        n_parsed = 0
        with open(f) as fin, open(out_path, "w") as fout:
            for line in fin:
                rec = json.loads(line)
                resp = rec.get("response", {})
                if "_raw" in resp:
                    parsed = parse_sse(resp["_raw"])
                elif "choices" in resp:
                    msg = resp["choices"][0].get("message", {})
                    parsed = {
                        "model": resp.get("model"),
                        "provider": resp.get("provider"),
                        "content": msg.get("content"),
                        "reasoning": msg.get("reasoning"),
                        "tool_calls": [
                            {"id": t["id"], "name": t["function"]["name"], "arguments": t["function"]["arguments"]}
                            for t in (msg.get("tool_calls") or [])
                        ],
                        "finish_reason": resp["choices"][0].get("finish_reason"),
                        "usage": resp.get("usage"),
                    }
                else:
                    parsed = {"error": "unparseable", "raw_keys": list(resp.keys())}
                fout.write(json.dumps({
                    "id": rec["id"],
                    "ts": rec["ts"],
                    "framework": rec["framework"],
                    "elapsed_s": rec["elapsed_s"],
                    "status": rec["status"],
                    "request": rec["request"],
                    "parsed_response": parsed,
                }, ensure_ascii=False) + "\n")
                n_parsed += 1
        print(f"{fw}: {n_parsed} calls -> {out_path.name}")


if __name__ == "__main__":
    main()
