"""Deterministic local HTTPS pages for opt-in Android extension scenarios.

Supply an ephemeral certificate/key; trust that certificate explicitly in the
test app's HTTPX SSLContext. Production networking defaults are not changed.
"""

from __future__ import annotations

import argparse
import json
import ssl
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cert", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--control", type=Path)
    args = parser.parse_args()

    class Pages(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 -- BaseHTTPRequestHandler interface
            target = urlsplit(self.path)
            query = parse_qs(target.query)
            start = int(query.get("_start", ["0"])[0])
            limit = min(int(query.get("_limit", ["3"])[0]), 20)
            control = (
                json.loads(args.control.read_text())
                if args.control and args.control.exists()
                else {}
            )
            time.sleep(min(float(control.get("delay", 0)), 10))
            status = int(control.get("status", 200))
            label = "name" if target.path in {"/comments", "/users"} else "title"
            rows = [
                {"id": index + 1, label: f"Fixture café {index + 1}"}
                for index in range(start, min(start + limit, 12))
            ]
            body = json.dumps(rows, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Pages)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(args.cert, args.key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    print(f"Fixture HTTPS listening on 127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
