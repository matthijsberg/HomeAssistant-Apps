"""Unit tests for Ollama Web UI proxy server (web_server.py).

Tests streaming proxying, background session tracking, reconnection resilience,
and chunked transfer encoding.
"""

import json
import socketserver
import threading
import time

import requests

from web_server import ProxyHandler, SessionManager, start_chat_worker


class MockStreamingResponse:
    """Mock requests streaming response simulating Ollama /api/chat stream."""

    def __init__(self, chunks, status_code=200):
        self.chunks = chunks
        self.status_code = status_code
        self.text = "Error" if status_code != 200 else ""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def iter_lines(self, delimiter=b"\n"):
        for chunk in self.chunks:
            time.sleep(0.01)
            yield chunk


def test_session_manager_lifecycle():
    mgr = SessionManager(max_sessions=3, ttl=1.0)
    s1 = mgr.get_or_create("msg_1", model="qwen2.5:7b")
    assert s1["id"] == "msg_1"
    assert s1["model"] == "qwen2.5:7b"
    assert s1["status"] == "pending"
    assert s1["chunks"] == []

    # Retrieving existing session returns same object
    assert mgr.get("msg_1") is s1

    # Add more to trigger max_sessions
    mgr.get_or_create("msg_2")
    mgr.get_or_create("msg_3")
    mgr.get_or_create("msg_4")
    # msg_1 should be evicted due to max_sessions=3
    assert mgr.get("msg_1") is None
    assert mgr.get("msg_4") is not None


def test_session_manager_ttl():
    mgr = SessionManager(max_sessions=10, ttl=0.05)
    mgr.get_or_create("msg_temp")
    assert mgr.get("msg_temp") is not None
    time.sleep(0.07)
    mgr._cleanup()
    assert mgr.get("msg_temp") is None


def test_start_chat_worker_success(monkeypatch):
    mgr = SessionManager()
    session = mgr.get_or_create("msg_test", model="qwen2.5:7b")

    mock_lines = [
        json.dumps({"message": {"role": "assistant", "content": "Hallo"}, "done": False}).encode("utf-8"),
        json.dumps({"message": {"role": "assistant", "content": " wereld!"}, "done": False}).encode("utf-8"),
        json.dumps({"message": {"role": "assistant", "content": ""}, "done": True, "eval_count": 2}).encode("utf-8"),
    ]

    def mock_post(url, data=None, headers=None, stream=False, timeout=600):
        return MockStreamingResponse(mock_lines)

    monkeypatch.setattr(requests, "post", mock_post)

    body = json.dumps({"model": "qwen2.5:7b", "messages": [{"role": "user", "content": "Hi"}]}).encode("utf-8")
    headers = {"Content-Type": "application/json"}

    # Run worker synchronously for test
    start_chat_worker(session, body, headers, ollama_url="http://mock:11434")

    assert session["status"] == "done"
    assert session["done"] is True
    assert len(session["chunks"]) == 3
    assert b"Hallo" in session["chunks"][0]
    assert b"wereld!" in session["chunks"][1]
    assert b'"done": true' in session["chunks"][2].lower()


def test_start_chat_worker_error(monkeypatch):
    mgr = SessionManager()
    session = mgr.get_or_create("msg_fail")

    def mock_post(url, data=None, headers=None, stream=False, timeout=600):
        return MockStreamingResponse([], status_code=500)

    monkeypatch.setattr(requests, "post", mock_post)

    start_chat_worker(session, b"{}", {}, ollama_url="http://mock:11434")

    assert session["status"] == "error"
    assert session["done"] is True
    assert "HTTP 500" in session["error"]


def test_http_proxy_chat_stream_and_resume(monkeypatch):
    """End-to-end integration test: start local test server, verify streaming and resume endpoints."""
    mock_lines = [
        json.dumps({"message": {"role": "assistant", "thinking": "Ik denk na..."}, "done": False}).encode("utf-8"),
        json.dumps({"message": {"role": "assistant", "content": "Hier is je script"}, "done": False}).encode("utf-8"),
        json.dumps({"message": {"role": "assistant", "content": ""}, "done": True, "eval_count": 10}).encode("utf-8"),
    ]

    orig_post = requests.post

    def mock_post(url, data=None, headers=None, stream=False, timeout=600, **kwargs):
        if "127.0.0.1" in url or "localhost" in url and "11434" not in url:
            return orig_post(url, data=data, headers=headers, stream=stream, timeout=timeout, **kwargs)
        return MockStreamingResponse(mock_lines)

    monkeypatch.setattr(requests, "post", mock_post)

    # Start a test HTTP server on an ephemeral port
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), ProxyHandler)
    port = server.server_address[1]
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    try:
        # 1. Test POST /api/chat with streaming and message_id
        msg_id = "msg_stream_e2e"
        payload = {
            "model": "ornith-1.5:35b",
            "messages": [{"role": "user", "content": "Demo"}],
            "stream": True,
            "message_id": msg_id,
        }
        res = requests.post(f"http://127.0.0.1:{port}/api/chat", json=payload, stream=True, timeout=10)
        assert res.status_code == 200
        assert res.headers.get("Transfer-Encoding") == "chunked"
        assert res.headers.get("X-Message-ID") == msg_id

        received_chunks = []
        for line in res.iter_lines():
            if line:
                received_chunks.append(json.loads(line.decode("utf-8")))

        assert len(received_chunks) == 3
        assert received_chunks[0]["message"]["thinking"] == "Ik denk na..."
        assert received_chunks[1]["message"]["content"] == "Hier is je script"
        assert received_chunks[2]["done"] is True
        res.close()

        # 2. Test GET /api/chat_resume with offset
        resume_res = requests.get(f"http://127.0.0.1:{port}/api/chat_resume?id={msg_id}&offset=1", timeout=10)
        assert resume_res.status_code == 200
        resume_chunks = [json.loads(line_item) for line_item in resume_res.iter_lines() if line_item]
        assert len(resume_chunks) == 2  # skipped chunk 0
        assert resume_chunks[0]["message"]["content"] == "Hier is je script"
        resume_res.close()

        # 3. Test GET /api/chat_resume for nonexistent session
        bad_res = requests.get(f"http://127.0.0.1:{port}/api/chat_resume?id=nonexistent", timeout=10)
        assert bad_res.status_code == 404

    finally:
        server.shutdown()
        server.server_close()
