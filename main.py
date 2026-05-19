"""
Entry point for the Ollama → LM Studio proxy.

Usage:
    python main.py

Environment variables (all optional):
    PROXY_HOST              Bind address          (default: 0.0.0.0)
    PROXY_PORT              Listen port           (default: 11434)
    LMS_BASE_URL            LM Studio base URL    (default: http://localhost:1234/)
    PROXY_REQUEST_TIMEOUT   Per-request timeout   (default: 300.0 seconds)
    PROXY_CONNECT_TIMEOUT   Connection timeout    (default: 5.0 seconds)
    OLLAMA_VERSION          Reported version      (default: 0.6.4)
"""

import logging

import uvicorn

from proxy.config import LISTEN_HOST, LISTEN_PORT

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)

if __name__ == "__main__":
    uvicorn.run(
        "proxy:app",
        host=LISTEN_HOST,
        port=LISTEN_PORT,
        log_level="info",
    )
