"""Temporary loopback server exposing only the two generated waveform pages."""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = {"/repeater-waveforms.html": ROOT / "docs/repeater-waveforms.html",
         "/repeater-waveforms-preview.html": ROOT / "docs/repeater-waveforms-preview.html"}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            path = "/repeater-waveforms.html" if PAGES["/repeater-waveforms.html"].exists() else "/repeater-waveforms-preview.html"
        target = PAGES.get(path)
        if target is None or not target.is_file():
            self.send_error(404)
            return
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    status = {"pid": os.getpid(), "port": server.server_port, "url": f"http://127.0.0.1:{server.server_port}/"}
    (ROOT / ".local/viewer-server.json").write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    print(status["url"], flush=True)
    server.serve_forever()
