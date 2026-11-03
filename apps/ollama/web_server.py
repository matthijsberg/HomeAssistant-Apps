import http.server
import json
import os
import socket
import socketserver
import sys
import threading
import time
import urllib.parse
from collections import OrderedDict

import requests

PORT = 8099
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")


class SessionManager:
    """Thread-safe manager for active and historical chat generation sessions."""

    def __init__(self, max_sessions: int = 100, ttl: float = 3600.0):
        self._lock = threading.Lock()
        self.sessions: OrderedDict[str, dict] = OrderedDict()
        self.max_sessions = max_sessions
        self.ttl = ttl

    def get_or_create(self, message_id: str, model: str = "") -> dict:
        with self._lock:
            if message_id in self.sessions:
                return self.sessions[message_id]

            session = {
                "id": message_id,
                "model": model,
                "created_at": time.time(),
                "status": "pending",  # 'running', 'done', 'error'
                "chunks": [],  # list of bytes
                "done": False,
                "error": None,
                "condition": threading.Condition(self._lock),
            }
            self.sessions[message_id] = session
            self._cleanup()
            return session

    def get(self, message_id: str) -> dict | None:
        with self._lock:
            return self.sessions.get(message_id)

    def _cleanup(self):
        now = time.time()
        expired = [k for k, v in self.sessions.items() if now - v["created_at"] > self.ttl]
        for k in expired:
            del self.sessions[k]

        while len(self.sessions) > self.max_sessions:
            self.sessions.popitem(last=False)


session_manager = SessionManager(max_sessions=100, ttl=3600.0)


def start_chat_worker(session: dict, body_bytes: bytes, headers: dict, ollama_url: str = OLLAMA_URL):
    """Background worker that calls Ollama streaming endpoint and buffers all chunks.

    Resilient to client disconnections: even if the browser drops connection mid-stream,
    this worker continues buffering until the model finishes generating.
    """
    try:
        session["status"] = "running"
        url = f"{ollama_url}/api/chat"

        try:
            payload = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except Exception:
            payload = {}

        # Force streaming from Ollama backend
        payload["stream"] = True
        payload.pop("message_id", None)  # internal tracking only
        req_body = json.dumps(payload).encode("utf-8")

        req_headers = {
            k: v
            for k, v in headers.items()
            if k.lower() not in ["host", "content-length", "transfer-encoding"]
        }
        req_headers["Content-Type"] = "application/json"

        with requests.post(url, data=req_body, headers=req_headers, stream=True, timeout=600) as resp:
            if resp.status_code != 200:
                err_text = resp.text
                with session["condition"]:
                    session["status"] = "error"
                    session["error"] = f"Ollama HTTP {resp.status_code}: {err_text}"
                    session["done"] = True
                    err_chunk = (
                        json.dumps({
                            "error": f"HTTP {resp.status_code}: {err_text}",
                            "done": True,
                        })
                        + "\n"
                    ).encode("utf-8")
                    session["chunks"].append(err_chunk)
                    session["condition"].notify_all()
                return

            for line in resp.iter_lines(delimiter=b"\n"):
                if not line:
                    continue
                with session["condition"]:
                    session["chunks"].append(line + b"\n")
                    session["condition"].notify_all()

            with session["condition"]:
                session["status"] = "done"
                session["done"] = True
                session["condition"].notify_all()

    except Exception as e:
        with session["condition"]:
            session["status"] = "error"
            session["error"] = str(e)
            session["done"] = True
            err_chunk = (
                json.dumps({
                    "error": str(e),
                    "done": True,
                })
                + "\n"
            ).encode("utf-8")
            session["chunks"].append(err_chunk)
            session["condition"].notify_all()


class ProxyHandler(http.server.SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _split_path(self):
        split = urllib.parse.urlsplit(self.path)
        norm_path = "/" + split.path.lstrip("/")
        query = urllib.parse.parse_qs(split.query)
        return norm_path, query

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, PUT, PATCH, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With, X-Message-ID")
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, PUT, PATCH, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With, X-Message-ID")
        super().end_headers()

    def write_chunk(self, data: bytes):
        if not data:
            return
        header = f"{len(data):X}\r\n".encode("latin1")
        self.wfile.write(header + data + b"\r\n")
        self.wfile.flush()

    def finish_chunked(self):
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()

    def stream_session(self, session: dict, start_offset: int = 0):
        """Stream chunks from session to connected HTTP client using chunked transfer encoding."""
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("X-Message-ID", session["id"])
        self.end_headers()

        cursor = start_offset
        try:
            while True:
                chunks_to_send = []
                is_done = False

                with session["condition"]:
                    if cursor < len(session["chunks"]):
                        chunks_to_send = session["chunks"][cursor:]
                        cursor += len(chunks_to_send)
                    elif session["done"]:
                        is_done = True
                    else:
                        session["condition"].wait(timeout=1.0)
                        if cursor < len(session["chunks"]):
                            chunks_to_send = session["chunks"][cursor:]
                            cursor += len(chunks_to_send)
                        if session["done"] and cursor >= len(session["chunks"]):
                            is_done = True

                for chunk in chunks_to_send:
                    self.write_chunk(chunk)

                if is_done:
                    self.finish_chunked()
                    self.close_connection = True
                    break

        except (BrokenPipeError, ConnectionResetError, socket.error):
            # Client disconnected mid-stream (mobile 5G drop / page reload);
            # background worker keeps running to completion.
            self.close_connection = True

    def _read_request_body(self) -> bytes:
        transfer_encoding = self.headers.get("Transfer-Encoding", "").lower()
        if "chunked" in transfer_encoding:
            chunks = []
            while True:
                line = self.rfile.readline().strip()
                if not line:
                    break
                try:
                    chunk_len = int(line, 16)
                except ValueError:
                    break
                if chunk_len == 0:
                    self.rfile.readline()
                    break
                chunks.append(self.rfile.read(chunk_len))
                self.rfile.readline()
            return b"".join(chunks)
        else:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 0:
                return self.rfile.read(content_length)
            return b""

    def do_GET(self):
        norm_path, query = self._split_path()

        if norm_path == "/api/chat_resume":
            message_ids = query.get("id", [])
            offsets = query.get("offset", ["0"])
            if not message_ids:
                self.send_error(400, "Missing 'id' parameter")
                return

            message_id = message_ids[0]
            try:
                start_offset = int(offsets[0])
            except ValueError:
                start_offset = 0

            session = session_manager.get(message_id)
            if not session:
                self.send_error(404, "Session not found or expired")
                return

            self.stream_session(session, start_offset=start_offset)
            return

        elif norm_path.startswith("/api/") or norm_path.startswith("/v1/"):
            self.proxy_request("GET", norm_path)
        elif norm_path in ["/", ""]:
            self.path = "/index.html"
            return http.server.SimpleHTTPRequestHandler.do_GET(self)
        else:
            return http.server.SimpleHTTPRequestHandler.do_GET(self)

    def do_POST(self):
        norm_path, _ = self._split_path()

        if norm_path == "/api/chat":
            body = self._read_request_body()
            try:
                payload = json.loads(body.decode("utf-8")) if body else {}
            except Exception:
                payload = {}

            message_id = payload.get("message_id")
            # If client requests streaming or provides message_id, use background worker
            if payload.get("stream", True) or message_id:
                if not message_id:
                    message_id = f"msg_{int(time.time()*1000)}"

                model_name = payload.get("model", "")
                session = session_manager.get_or_create(message_id, model=model_name)

                # Spawn Ollama generation worker thread
                worker = threading.Thread(
                    target=start_chat_worker,
                    args=(session, body, dict(self.headers), OLLAMA_URL),
                    daemon=True,
                )
                worker.start()

                # Stream response back to client immediately
                self.stream_session(session, start_offset=0)
                return

            # Fallback non-streaming proxy
            self.proxy_request("POST", norm_path, body=body)

        elif norm_path.startswith("/api/") or norm_path.startswith("/v1/"):
            body = self._read_request_body()
            self.proxy_request("POST", norm_path, body=body)
        else:
            self.send_error(404)

    def do_DELETE(self):
        norm_path, _ = self._split_path()
        if norm_path.startswith("/api/") or norm_path.startswith("/v1/"):
            body = self._read_request_body()
            self.proxy_request("DELETE", norm_path, body=body)
        else:
            self.send_error(404)

    def proxy_request(self, method: str, norm_path: str, body: bytes | None = None):
        url = f"{OLLAMA_URL}{norm_path}"
        try:
            headers = {
                k: v
                for k, v in self.headers.items()
                if k.lower() not in ["host", "content-length", "transfer-encoding"]
            }

            resp = requests.request(method, url, data=body, headers=headers, stream=False, timeout=300)

            self.send_response(resp.status_code)
            content = resp.content
            for key, value in resp.headers.items():
                if key.lower() not in [
                    "content-encoding",
                    "transfer-encoding",
                    "content-length",
                    "connection",
                    "access-control-allow-origin",
                ]:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        except Exception as e:
            print(f"Proxy error: {e}", file=sys.stderr)
            self.send_error(500, str(e))


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("", PORT), ProxyHandler) as httpd:
        print(f"Serving UI on port {PORT}")
        httpd.serve_forever()
