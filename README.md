# OLLMStudio — Ollama → LM Studio Proxy

A lightweight local proxy that sits on the standard **Ollama port (11434)** and transparently translates requests to **LM Studio's OpenAI-compatible API (port 1234)**.

This lets any tool that speaks to Ollama (VS Code Copilot, Open WebUI, Continue, etc.) use models loaded in LM Studio without any reconfiguration.

---

## How it works

```
Your client  →  localhost:11434 (this proxy)  →  localhost:1234 (LM Studio)
    Ollama API                                      OpenAI-compat API
```

| Ollama endpoint | Translated to |
|---|---|
| `GET /api/version` | Returns a synthetic version string |
| `GET /api/tags` | `GET /v1/models` + `/api/v0/models` (enriched metadata) |
| `POST /api/show` | `GET /v1/models/{id}` + `/api/v0/models` |
| `POST /api/chat` | `POST /v1/chat/completions` (streaming & non-streaming) |
| `* /v1/*` | Transparent passthrough to LM Studio |

---

## Requirements

- Python 3.11+
- [LM Studio](https://lmstudio.ai/) with the local server enabled (local or remote)

---

## Setup

```bash
# 1. Clone / copy the project
cd OLLMStudio

# 2. Create and activate a virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure the proxy (see Configuration below)
cp .env.example .env
# Edit .env with your LM Studio URL and API key

# 5. Start LM Studio and load at least one model

# 6. Run the proxy
python main.py
```

The proxy will log to stdout and is ready when you see:

```
HH:MM:SS  INFO      Proxy listening on 0.0.0.0:11434  →  http://192.168.1.50:1234/  (key configured)
```

---

## Configuration

Settings are loaded from a `.env` file in the project root (gitignored), with
environment variables as a fallback.  Copy `.env.example` to `.env` to get started.

| Variable | Default | Description |
|---|---|---|
| `LMS_BASE_URL` | `http://localhost:1234/` | LM Studio server URL |
| `LMS_API_KEY` | _(empty)_ | Bearer token for LM Studio authentication |
| `PROXY_HOST` | `0.0.0.0` | Bind address |
| `PROXY_PORT` | `11434` | Listen port (standard Ollama port) |
| `PROXY_REQUEST_TIMEOUT` | `300.0` | Per-request timeout in seconds |
| `PROXY_CONNECT_TIMEOUT` | `5.0` | Initial connection timeout in seconds |
| `OLLAMA_VERSION` | `0.6.4` | Ollama version reported to clients |

---

## Remote LM Studio

You can point the proxy at an LM Studio instance running on another machine.

**1. Enable the LM Studio server on the remote host**

In LM Studio: *Developer* → *Start Server* → ensure it binds to `0.0.0.0` (not just localhost).

**2. Enable API key authentication (recommended)**

In LM Studio: *Developer* → *API Keys* → create a key and copy it.

> Without an API key, anyone on the network who can reach the LM Studio port can send requests directly.  The proxy enforces nothing on its own inbound side — if you expose the proxy itself beyond localhost, protect it separately (firewall, reverse proxy with TLS, etc.).

**3. Configure `.env`**

```dotenv
LMS_BASE_URL=http://192.168.1.50:1234/
LMS_API_KEY=lms-abc123yourkeyhere
```

The proxy injects `Authorization: Bearer <LMS_API_KEY>` on every outbound request to LM Studio.  Incoming client `Authorization` headers are stripped before forwarding, so your key is never exposed to clients and client tokens cannot interfere.

---

## Project structure

```
OLLMStudio/
├── main.py              # Entry point — run this
├── requirements.txt
├── README.md
├── .gitignore
└── proxy/
    ├── __init__.py      # Exposes the FastAPI `app`
    ├── config.py        # All configuration constants
    ├── models.py        # Ollama ↔ OpenAI model translation helpers
    └── routes.py        # FastAPI app, middleware, and all route handlers
```

---

## Troubleshooting

**`502 LM Studio server is not reachable`**
LM Studio is not running or its local server is not enabled. Open LM Studio → Developer → Start Server.

**`404 Model '…' is not currently loaded`**
The requested model is installed but not loaded. Load it in LM Studio before sending requests.

**Client sees no models**
LM Studio may have no models loaded. Check the LM Studio UI and ensure at least one model is active.
