---
type: "architecture"
id: "streaming-and-reconnection"
title: "Live Streaming and Mobile Reconnection Resilience"
status: "active"
trust: "high"
generated: false
sources:
  - "Home Assistant Ingress streaming specifications"
  - "Ollama API streaming protocol (/api/chat)"
  - "web_server.py SessionManager architecture"
---

# Live Streaming and Mobile Reconnection Resilience

## Problem Statement
When running large reasoning or multi-billion parameter models (such as `ornith-1.5:35b` or DeepSeek-R1) on shared host memory, inference can take 60 to 120+ seconds for complex tasks like code generation.

Under standard non-streaming HTTP requests (`stream: false`), zero bytes are transmitted across the network while the model is thinking and generating. Mobile 5G connections and reverse proxies (Home Assistant Ingress, Nginx, Cloudflare tunnels) enforce a 60-second idle read timeout. If no packet arrives within 60 seconds, the proxy aborts the TCP socket, causing the browser frontend to reject the fetch promise with `TypeError: Failed to fetch`.

## Dual-Layer Solution

### 1. HTTP/1.1 Chunked Streaming (`web_server.py`)
- The web UI proxies `/api/chat` using HTTP/1.1 chunked transfer encoding (`Transfer-Encoding: chunked`).
- As Ollama produces tokens, `web_server.py` emits line-delimited JSON chunks in real time.
- The first token (or reasoning thinking token) arrives at the client within 1-2 seconds of invocation.
- Continuous network packet flow keeps the TCP session active, completely preventing 60-second idle proxy drops.
- Thinking tokens (`chunk.message.thinking`) are rendered live into a collapsible thought card (`🧠 Denkproces`) before content tokens begin.

### 2. Session Manager with Background Worker & Resume Endpoint
- When a user submits a prompt, the browser attaches a unique `message_id`.
- `SessionManager` in `web_server.py` creates a tracking session and dispatches an asynchronous worker thread to read from Ollama.
- **Client Disconnection Resilience:** If the client experiences a transient network drop (e.g., cell tower handoff, elevator signal loss, or browser backgrounding), the client socket closes, but the backend worker thread **does not abort**. It continues buffering chunks on the host until generation completes.
- **Auto-Reconnect (`GET /api/chat_resume`):**
  - The frontend detects socket termination before `done: true` and enters an exponential backoff retry loop.
  - As soon as connectivity returns, the frontend calls `GET /api/chat_resume?id=<message_id>&offset=<token_count>`.
  - The server replays any missed tokens from `offset` and continues streaming until completion.
- **LocalStorage State Persistence:** Active message IDs and conversation history are persisted in browser `localStorage`, allowing generation to resume even across page reloads.
