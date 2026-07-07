"""Local HTTP save helper for the cut-review HTML page.

The review page is often opened as file://, where browsers cannot silently
write JSON back to the project folder. This helper exposes one localhost POST
endpoint and writes only the paths configured at startup.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as tmp:
            tmp.write(text)
            tmp.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def make_handler(paths: list[Path]):
    class Handler(BaseHTTPRequestHandler):
        server_version = "CutReviewSaveServer/1.0"

        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "content-type")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Cache-Control", "no-store")

        def _json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(status)
            self._cors()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self) -> None:
            if urlparse(self.path).path != "/health":
                self._json(404, {"ok": False, "error": "unknown endpoint"})
                return
            self._json(200, {"ok": True, "paths": [str(path) for path in paths]})

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/save-cut-decisions":
                self._json(404, {"ok": False, "error": "unknown endpoint"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._json(400, {"ok": False, "error": "invalid content length"})
                return
            if length <= 0 or length > 10_000_000:
                self._json(400, {"ok": False, "error": "invalid decision payload size"})
                return
            text = self.rfile.read(length).decode("utf-8")
            try:
                json.loads(text)
            except json.JSONDecodeError as exc:
                self._json(400, {"ok": False, "error": f"invalid JSON: {exc.msg}"})
                return
            try:
                for path in paths:
                    atomic_write_text(path, text)
            except Exception as exc:
                self._json(500, {"ok": False, "error": str(exc)})
                return
            self._json(200, {"ok": True, "path": str(paths[0]), "paths": [str(path) for path in paths]})

        def log_message(self, fmt: str, *args) -> None:
            print("%s - %s" % (self.address_string(), fmt % args), flush=True)

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description="Save cut-review decisions from localhost HTML.")
    parser.add_argument("--path", required=True, help="Primary decision JSON path to write.")
    parser.add_argument("--copy-to", action="append", default=[], help="Additional decision JSON path to update.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=17654)
    args = parser.parse_args()

    paths = [Path(args.path), *[Path(path) for path in args.copy_to]]
    server = ThreadingHTTPServer((args.host, args.port), make_handler(paths))
    print(f"Cut-review save server on http://{args.host}:{args.port}/save-cut-decisions", flush=True)
    for path in paths:
        print(f"writing {path}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
