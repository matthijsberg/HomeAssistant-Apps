import http.server
import os
import socketserver
import sys
import requests

PORT = 8099
OLLAMA_URL = "http://localhost:11434"


class ProxyHandler(http.server.SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _normalize_path(self):
        # Handle duplicate slashes from Home Assistant Ingress routing
        return "/" + self.path.lstrip("/")

    def do_OPTIONS(self):
        # CORS preflight handler for browser fetch requests
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, PUT, PATCH, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        norm_path = self._normalize_path()
        if norm_path.startswith("/api/") or norm_path.startswith("/v1/"):
            self.proxy_request("GET", norm_path)
        elif norm_path == "/" or norm_path == "":
            self.path = "/index.html"
            return http.server.SimpleHTTPRequestHandler.do_GET(self)
        else:
            return http.server.SimpleHTTPRequestHandler.do_GET(self)

    def do_POST(self):
        norm_path = self._normalize_path()
        if norm_path.startswith("/api/") or norm_path.startswith("/v1/"):
            self.proxy_request("POST", norm_path)
        else:
            self.send_error(404)

    def do_DELETE(self):
        norm_path = self._normalize_path()
        if norm_path.startswith("/api/") or norm_path.startswith("/v1/"):
            self.proxy_request("DELETE", norm_path)
        else:
            self.send_error(404)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, PUT, PATCH, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
        super().end_headers()

    def proxy_request(self, method, norm_path):
        url = f"{OLLAMA_URL}{norm_path}"
        try:
            headers = {k: v for k, v in self.headers.items() if k.lower() not in ["host", "content-length"]}

            body = None
            if method in ["POST", "DELETE", "PUT", "PATCH"]:
                content_length = int(self.headers.get("Content-Length", 0))
                if content_length > 0:
                    body = self.rfile.read(content_length)

            resp = requests.request(method, url, data=body, headers=headers, stream=True)

            self.send_response(resp.status_code)
            for key, value in resp.headers.items():
                if key.lower() not in [
                    "content-encoding",
                    "transfer-encoding",
                    "content-length",
                    "connection",
                    "access-control-allow-origin",
                ]:
                    self.send_header(key, value)
            self.end_headers()

            for chunk in resp.iter_content(chunk_size=1024):
                if chunk:
                    self.wfile.write(chunk)
                    self.wfile.flush()

        except Exception as e:
            print(f"Proxy error: {e}", file=sys.stderr)
            self.send_error(500, str(e))


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("", PORT), ProxyHandler) as httpd:
        print(f"Serving UI on port {PORT}")
        httpd.serve_forever()
