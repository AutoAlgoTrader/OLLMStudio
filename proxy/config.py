"""
Runtime configuration for the Ollama → LM Studio proxy.
Override any value via environment variables or a .env file before starting.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()  # loads .env from the working directory (silently ignored if absent)

# ── Network ───────────────────────────────────────────────────────────────────
LISTEN_HOST: str = os.getenv("PROXY_HOST", "0.0.0.0")
LISTEN_PORT: int = int(os.getenv("PROXY_PORT", "11434"))

LM_STUDIO_BASE: str = os.getenv("LMS_BASE_URL", "http://localhost:1234/")

# API key sent to LM Studio as "Authorization: Bearer <key>".
# Leave unset (or empty) when LM Studio's auth is disabled.
LMS_API_KEY: str = os.getenv("LMS_API_KEY", "")

# ── Timeouts (seconds) ────────────────────────────────────────────────────────
REQUEST_TIMEOUT: float = float(os.getenv("PROXY_REQUEST_TIMEOUT", "300.0"))
CONNECT_TIMEOUT: float = float(os.getenv("PROXY_CONNECT_TIMEOUT", "5.0"))

# ── Ollama compatibility ───────────────────────────────────────────────────────
# Reported in GET /api/version.  Bump if a client requires a newer handshake.
OLLAMA_VERSION: str = os.getenv("OLLAMA_VERSION", "0.6.4")
