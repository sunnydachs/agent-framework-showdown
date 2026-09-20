"""LLM traffic recorder proxy for the agent framework showdown.

All three frameworks are pointed at http://127.0.0.1:8118/v1 (an OpenAI-compatible
endpoint). The proxy forwards to OpenRouter and records every request/response
pair as JSONL: raw messages sent by the framework, raw model output, tool calls,
token usage, latency, and the framework label (via X-Framework header).

Run:  python proxy/rec_proxy.py --port 8118
"""
import argparse
import json
import os
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parent.parent
TRACE_DIR = ROOT / "traces"
TRACE_DIR.mkdir(exist_ok=True)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
UPSTREAM = os.environ.get("PROXY_UPSTREAM", OPENROUTER_URL)


def _load_key():
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.strip().startswith("OPENROUTER_API_KEY="):
                return line.strip().split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("OPENROUTER_API_KEY", "")


API_KEY = _load_key()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):  # silence default stderr noise
        pass

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _record(self, framework, run_label, request_body, response_body, elapsed, status):
        rec = {
            "id": uuid.uuid4().hex[:12],
            "ts": time.time(),
            "framework": framework,
            "run_label": run_label,
            "status": status,
            "elapsed_s": round(elapsed, 3),
            "request": request_body,
            "response": response_body,
        }
        out = TRACE_DIR / f"llm_calls_{framework}.jsonl"
        if run_label:
            out = TRACE_DIR / f"llm_calls_{framework}__{run_label}.jsonl"
        with open(out, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def do_POST(self):
        body = self._read_body()
        framework = self.headers.get("X-Framework", "unknown")
        t0 = time.time()
        try:
            req = Request(
                UPSTREAM,
                data=body,
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/arari/agent-framework-showdown",
                    "X-Title": "agent-framework-showdown",
                },
            )
            with urlopen(req, timeout=300) as resp:
                resp_body = resp.read()
                status = resp.status
        except HTTPError as e:
            resp_body = e.read()
            status = e.code
        except Exception as e:  # network error, etc.
            self._record(framework, "", None, {"proxy_error": str(e)}, time.time() - t0, 0)
            self.send_error(502, str(e))
            return

        elapsed = time.time() - t0
        # label can also arrive via request body (some clients strip custom
        # headers); read it before parsing below
        try:
            req_json = json.loads(body)
        except Exception:
            req_json = {"_raw": body.decode("utf-8", "replace")}
        label = self.headers.get("X-Run-Label", "") or req_json.pop("run_label", "")
        # run labels carry the framework name as prefix: "<fw>__<scenario>_run<N>"
        if framework == "unknown" and "__" in label:
            framework = label.split("__", 1)[0]
            req_json["inferred_framework"] = framework
        try:
            resp_json = json.loads(resp_body)
        except Exception:
            resp_json = {"_raw": resp_body.decode("utf-8", "replace")}

        # never leak the API key into traces
        req_json.pop("api_key", None)

        self._record(framework, label, req_json, resp_json, elapsed, status)

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp_body)))
        self.end_headers()
        self.wfile.write(resp_body)

    def do_GET(self):
        # health check
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        payload = b'{"status":"ok"}'
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8118)
    args = ap.parse_args()
    if not API_KEY:
        print("ERROR: OPENROUTER_API_KEY not found in .env or env", file=sys.stderr)
        sys.exit(1)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"[rec-proxy] listening on http://127.0.0.1:{args.port}/v1 -> {UPSTREAM}")
    print(f"[rec-proxy] traces -> {TRACE_DIR}/llm_calls_<framework>.jsonl")
    srv.serve_forever()


if __name__ == "__main__":
    main()
